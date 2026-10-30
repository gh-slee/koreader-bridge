import SwiftUI
import AppKit
import Foundation

@MainActor enum NativeChecks {
    static func require(_ condition: Bool, _ message: String) throws {
        if !condition { throw Failure(code: "native_test", message: message) }
    }
    static func snapshot(_ name: String, root: URL) async throws {
        guard let window = NSApp.windows.first(where: { $0.isVisible && $0.contentView != nil }),
              let view = window.contentView else { throw Failure(code: "snapshot", message: "No rendered app window.") }
        window.deminiaturize(nil)
        NSApp.unhide(nil)
        window.collectionBehavior.insert(.moveToActiveSpace)
        window.makeKeyAndOrderFront(nil)
        window.orderFrontRegardless()
        NSRunningApplication.current.activate(options: [.activateAllWindows, .activateIgnoringOtherApps])
        try await Task.sleep(nanoseconds: 800_000_000)
        window.displayIfNeeded()
        view.layoutSubtreeIfNeeded()
        let target = root.appendingPathComponent(name)
        func verifyBounds(_ node: NSView) throws {
            if let split = node as? NSSplitView {
                try require(split.frame.height <= view.bounds.height + 1, "Page content escaped the visible window: " + name)
            }
            if let table = node as? NSTableView, table.numberOfColumns == 5,
               let scroll = table.enclosingScrollView {
                try require(table.bounds.width <= scroll.contentSize.width + 2, "A table column escaped the visible viewport: " + name)
            }
            for child in node.subviews { try verifyBounds(child) }
        }
        try verifyBounds(view)
        if let ownImage = KBCreateOwnWindowImage(UInt32(window.windowNumber)),
           ownImage.width >= Int(window.frame.width * 0.9),
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
        var captures: [String] = []
        var layouts: [[String: Any]] = []
        func capture(_ name: String) async throws {
            try await snapshot(name, root: root)
            captures.append(name)
            if let window = NSApp.windows.first(where: { $0.isVisible && $0.contentView != nil }) {
                let size = window.contentLayoutRect.size
                layouts.append(["capture": name, "width": size.width, "height": size.height, "page": model.section.rawValue])
            }
        }
        func resize(_ width: CGFloat, _ height: CGFloat) {
            NSApp.windows.first(where: { $0.isVisible })?.setContentSize(NSSize(width: width, height: height))
        }
        do {
            if let window = NSApp.windows.first(where: { $0.isVisible }) {
                window.setFrameAutosaveName("")
                window.setContentSize(NSSize(width: 1120, height: 800))
            }
            try require(model.health?.protocolVersion == 1, "Bundled protocol health check failed.")
            cases.append("bundled-runtime-health")
            for dark in [false, true] {
                NSApp.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
                for compact in [false, true] {
                    resize(compact ? 940 : 1120, compact ? 680 : 800)
                    for page in [AppSection.backups, .cleanup] {
                        model.section = page
                        try await capture("empty-" + page.rawValue.lowercased() + (compact ? "-compact" : "") + (dark ? "-dark" : "") + ".png")
                    }
                }
            }
            cases.append("empty-page-layout-matrix")
            resize(1120, 800); NSApp.appearance = NSAppearance(named: .aqua)
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
            try require(model.sample != nil && model.runs.count == 3 && model.reclaimable > 0, "Sample reader creation or cleanup total failed.")
            await model.refreshConnected()
            try require(model.connected?.modelHint == "Kobo Sample Source" &&
                        model.modelOptions.contains("Kobo Sample Source"), "Connected reader discovery failed.")
            let savedTarget = model.config.targetModel
            model.config.sourceModel = model.connected!.modelHint!
            try require(model.config.targetModel == savedTarget, "Selecting a source changed the target.")
            cases.append("connected-reader-model-options")
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
            model.config.mode = "koreader"
            try await capture("error-state.png")
            model.problem = nil
            model.declineFinal = false; model.autoReply = false
            model.notice = ""; model.logs = []
            model.phase = "Sample session complete"; model.config.mode = "full"
            model.selectedRun = captured.id
            await model.details()
            let storedOutput = model.config.outputRoot
            // Display a synthetic path during Settings captures; no operation uses it.
            model.config.outputRoot = "/Sample/Private Backups"
            await model.refreshConnected()
            for dark in [false, true] {
                NSApp.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
                for (suffix, width, height) in [("", CGFloat(1120), CGFloat(800)), ("-compact", 940, 680), ("-wide", 1440, 900)] {
                    resize(width, height)
                    for page in AppSection.allCases {
                        model.section = page
                        try await capture(page.rawValue.lowercased() + suffix + (dark ? "-dark" : "-light") + ".png")
                    }
                    model.section = .migration; model.config.mode = "library"
                    try await capture("library" + suffix + (dark ? "-dark" : "-light") + ".png")
                    model.config.mode = "full"
                }
            }
            cases.append("four-page-layout-matrix")
            cases.append("minimum-window-resize")
            let originalRuns = model.runs
            let longRow = RunEntry(id: "sample-long-batch-name-for-reading-setup-migration-and-recovery-2024-01-01",
                status: "needs-recovery", operation: "restore-target", bytes: 1234567, endedAt: "",
                targetModified: true, eligible: false,
                protection: "Protected recovery point. Keep this batch until the target has been checked and all dependent operations have completed successfully.",
                canReuse: false, canRestore: false)
            guard let sample = model.sample else { throw Failure(code: "layout", message: "Missing isolated sample workspace.") }
            let longFolder = URL(fileURLWithPath: sample.workspace).appendingPathComponent("runs").appendingPathComponent(longRow.id)
            try FileManager.default.createDirectory(at: longFolder, withIntermediateDirectories: true)
            try JSONSerialization.data(withJSONObject: ["run_id": longRow.id, "status": longRow.status,
                "operation": longRow.operation, "target_modified": true]).write(to: longFolder.appendingPathComponent("run.json"))
            model.runs = [longRow] + model.runs; model.selectedRun = longRow.id; model.summary = [:]
            resize(940, 680)
            for page in [AppSection.backups, .cleanup] {
                model.section = page
                try await capture("long-" + page.rawValue.lowercased() + ".png")
            }
            cases.append("long-batch-and-retention-layout")
            model.runs = originalRuns; model.selectedRun = captured.id
            model.config.outputRoot = storedOutput
            let result: [String: Any] = ["passed": true, "cases": cases, "physicalReadersAccessed": false,
                "source": "actual native app and bundled helper/runtime", "screenshots": captures, "layouts": layouts]
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
