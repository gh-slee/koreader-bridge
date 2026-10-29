import SwiftUI
import AppKit
import Foundation

@MainActor enum NativeChecks {
    static func require(_ condition: Bool, _ message: String) throws {
        if !condition { throw Failure(code: "native_test", message: message) }
    }
    static func snapshot(_ name: String, root: URL) async throws {
        try await Task.sleep(nanoseconds: 800_000_000)
        guard let window = NSApp.windows.first(where: { $0.isVisible && $0.contentView != nil }),
              let view = window.contentView else { throw Failure(code: "snapshot", message: "No rendered app window.") }
        window.makeKeyAndOrderFront(nil)
        window.orderFrontRegardless()
        window.displayIfNeeded()
        view.layoutSubtreeIfNeeded()
        let target = root.appendingPathComponent(name)
        if let ownImage = KBCreateOwnWindowImage(UInt32(window.windowNumber)),
           let png = NSBitmapImageRep(cgImage: ownImage).representation(using: .png, properties: [:]) {
            try png.write(to: target)
            return
        }
        let capture = Process()
        capture.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
        capture.arguments = ["-x", "-o", "-r", "-l" + String(window.windowNumber), target.path]
        let captureErrors = Pipe()
        capture.standardError = captureErrors
        try capture.run()
        capture.waitUntilExit()
        if capture.terminationStatus == 0 && FileManager.default.fileExists(atPath: target.path) {
            return
        }
        let diagnostic = String(data: captureErrors.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        try diagnostic.write(to: root.appendingPathComponent("CAPTURE_DIAGNOSTIC.txt"), atomically: true, encoding: .utf8)
        // Fallback is recorded separately; materials may be incomplete in an NSView cache.
        try "Native window capture unavailable; NSView cache fallback used.".write(to: root.appendingPathComponent("CAPTURE_LIMITATION.txt"), atomically: true, encoding: .utf8)
        guard let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) else {
            throw Failure(code: "snapshot", message: "Could not allocate a native view snapshot.")
        }
        view.cacheDisplay(in: view.bounds, to: rep)
        guard let png = rep.representation(using: .png, properties: [:]) else { throw Failure(code: "snapshot", message: "Snapshot encoding failed.") }
        try png.write(to: root.appendingPathComponent(name))
    }
    static func run(_ model: AppModel) async {
        guard let root = model.testRoot else { return }
        var cases: [String] = []
        do {
            if let window = NSApp.windows.first(where: { $0.isVisible }) {
                window.setFrameAutosaveName("")
                window.setContentSize(NSSize(width: 1120, height: 800))
            }
            try require(model.health?.protocolVersion == 1, "Bundled protocol health check failed.")
            cases.append("bundled-runtime-health")
            model.section = .backups
            try await snapshot("empty-backups.png", root: root)
            model.section = .migration
            model.config.sourceModel = "Sample Source"; model.config.targetModel = "Sample Target"; model.config.mode = "full"
            try model.store.save(model.config)
            var obj = try JSONSerialization.jsonObject(with: Data(contentsOf: model.store.file)) as! [String: Any]
            obj["unknownFutureField"] = ["keep": true]
            var nested = obj["configuration"] as! [String: Any]; nested["unknownChoice"] = "preserved"; obj["configuration"] = nested
            try JSONSerialization.data(withJSONObject: obj).write(to: model.store.file, options: .atomic)
            try model.store.save(model.config)
            let reopened = try model.store.load()
            let retained = try JSONSerialization.jsonObject(with: Data(contentsOf: model.store.file)) as! [String: Any]
            try require(reopened.mode == "full" && retained["unknownFutureField"] != nil &&
                        (retained["configuration"] as? [String: Any])?["unknownChoice"] as? String == "preserved", "Preference preservation failed.")
            cases.append("save-reopen-unknown-preferences")
            let malformed = PreferenceStore(folder: root.appendingPathComponent("MalformedPreferences"))
            try malformed.save(model.config)
            let bad = Data("{\"schemaVersion\":1,\"configuration\":42}".utf8)
            try bad.write(to: malformed.file)
            var refused = false
            do { try malformed.save(model.config) } catch { refused = true }
            try require(refused && (try Data(contentsOf: malformed.file)) == bad, "Malformed preferences were overwritten.")
            cases.append("malformed-preferences-protected")
            await model.createSample()
            try require(model.sample != nil && model.runs.count == 3, "Sample reader creation failed.")
            model.autoReply = true
            let preview = await model.execute(model.config.workflow(dryRun: true))
            try require(preview && model.runs.contains { $0.status == "audited" }, "FULL preview failed.")
            cases.append("full-preview")
            let transferred = await model.execute(model.config.workflow(dryRun: false))
            try require(transferred, "FULL transfer failed.")
            guard let captured = model.runs.first(where: { $0.canRestore && $0.canReuse && $0.status == "success" }) else { throw Failure(code: "native_test", message: "No captured snapshot.") }
            cases.append("full-transfer")
            let rp = await model.execute(model.config.workflow(action: "restore", dryRun: true, runID: captured.id))
            try require(rp, "Restore preview failed."); cases.append("restore-preview")
            let restored = await model.execute(model.config.workflow(action: "restore", dryRun: false, runID: captured.id))
            try require(restored, "Exact restore failed."); cases.append("exact-restore")
            let reuse = await model.execute(model.config.workflow(action: "reuse", dryRun: false, runID: captured.id))
            try require(reuse, "Saved-source migration failed."); cases.append("saved-source")
            model.config.mode = "library"
            for policy in ["overwrite", "keep-target"] {
                model.config.conflict = policy
                let ok = await model.execute(model.config.workflow(dryRun: false))
                try require(ok, "Library policy failed."); cases.append("library-" + policy)
            }
            if let eligible = model.runs.first(where: { $0.eligible && $0.operation == "sample" }) {
                let deleted = await model.execute(model.config.workflow(action: "delete", dryRun: false, runID: eligible.id))
                try require(deleted && !model.runs.contains(where: { $0.id == eligible.id }), "Typed cleanup failed.")
                cases.append("explicit-synthetic-cleanup")
            } else { throw Failure(code: "native_test", message: "No eligible synthetic batch.") }
            model.config.mode = "koreader"; model.declineFinal = true
            let cancelled = await model.execute(model.config.workflow(dryRun: false))
            try require(cancelled && model.runs.contains(where: { $0.status == "cancelled" }) && model.notice.hasPrefix("Cancelled."), "Default-No cancellation failed.")
            cases.append("final-decline")
            model.config.mode = "unsupported"
            let rejected = await model.execute(model.config.workflow(dryRun: true))
            try require(!rejected && model.problem != nil, "Invalid workflow was not presented as an error.")
            cases.append("native-error-presentation")
            try await snapshot("error-state.png", root: root)
            model.problem = nil
            model.declineFinal = false; model.autoReply = false
            model.notice = "Synthetic end-to-end checks passed. No physical readers were accessed."
            model.phase = "Sample session complete"; model.config.mode = "full"
            model.section = .migration; NSApp.appearance = NSAppearance(named: .aqua)
            try await snapshot("migration-light.png", root: root)
            model.section = .backups
            try await snapshot("backups-light.png", root: root)
            model.section = .migration; NSApp.appearance = NSAppearance(named: .darkAqua)
            try await snapshot("migration-dark.png", root: root)
            if let window = NSApp.windows.first(where: { $0.isVisible }) {
                window.setContentSize(NSSize(width: 940, height: 680))
                try await snapshot("migration-compact.png", root: root)
                cases.append("minimum-window-resize")
            }
            let result: [String: Any] = ["passed": true, "cases": cases, "physicalReadersAccessed": false, "source": "actual native app and bundled helper/runtime", "screenshots": ["migration-light.png", "backups-light.png", "migration-dark.png", "empty-backups.png", "error-state.png", "migration-compact.png"]]
            try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys]).write(to: root.appendingPathComponent("NATIVE_TEST_RESULTS.json"))
            NSApp.terminate(nil)
        } catch {
            let result: [String: Any] = ["passed": false, "cases": cases, "error": error.localizedDescription, "logs": model.logs]
            try? JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted]).write(to: root.appendingPathComponent("NATIVE_TEST_RESULTS.json"))
            model.problem = error.localizedDescription
            model.busy = false
            NSApp.terminate(nil)
        }
    }
}
