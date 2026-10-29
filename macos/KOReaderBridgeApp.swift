import SwiftUI
import AppKit
import Foundation
import CoreFoundation

enum JSONValue: Codable, Sendable {
    case object([String: JSONValue]), array([JSONValue]), string(String), number(Double), bool(Bool), null
    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(Double.self) { self = .number(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode([String: JSONValue].self) { self = .object(v) }
        else { self = .array(try c.decode([JSONValue].self)) }
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .object(let v): try c.encode(v)
        case .array(let v): try c.encode(v)
        case .string(let v): try c.encode(v)
        case .number(let v): try c.encode(v)
        case .bool(let v): try c.encode(v)
        case .null: try c.encodeNil()
        }
    }
    func decode<T: Decodable>(_ type: T.Type) throws -> T { try JSONDecoder().decode(type, from: JSONEncoder().encode(self)) }
    var object: [String: JSONValue] { if case .object(let v) = self { return v }; return [:] }
    var string: String { if case .string(let v) = self { return v }; return "" }
    var number: Double { if case .number(let v) = self { return v }; return 0 }
}
struct Configuration: Codable {
    var mode = "koreader"
    var sourceModel = ""
    var targetModel = ""
    var locale = "en"
    var books = true
    var fonts = true
    var readingData = true
    var conflict = "overwrite"
    var includePaths = ""
    var excludePaths = ""
    var extensions = ""
    var keepSuccessful = 2
    var outputRoot = ""
    func workflow(action: String = "migration", dryRun: Bool, runID: String? = nil) -> Workflow {
        Workflow(action: action, mode: mode, dryRun: dryRun, sourceModel: sourceModel, targetModel: targetModel,
                 locale: locale, books: books, fonts: fonts, readingData: readingData, conflict: conflict,
                 runID: runID, includeDirs: lines(includePaths), excludeDirs: lines(excludePaths), extensions: lines(extensions))
    }
    private func lines(_ value: String) -> [String] { value.split(separator: "\n").map(String.init).filter { !$0.isEmpty } }
}
struct Workflow: Codable, Sendable {
    var action: String; var mode: String; var dryRun: Bool; var sourceModel: String; var targetModel: String
    var locale: String; var books: Bool; var fonts: Bool; var readingData: Bool; var conflict: String
    var runID: String?; var includeDirs: [String]; var excludeDirs: [String]; var extensions: [String]
}
struct Request: Encodable, Sendable {
    let version = 1
    let id = UUID().uuidString
    var operation: String
    var workspace: String?
    var config: Workflow?
    var runID: String?
    var keepSuccessful: Int?
    var fixtureRoot: String?
}
struct RunEntry: Decodable, Identifiable, Hashable, Sendable {
    let id: String; let status: String; let operation: String; let bytes: Int64; let endedAt: String
    let targetModified: Bool; let eligible: Bool; let protection: String; let canReuse: Bool; let canRestore: Bool
}
struct RunCatalog: Decodable { let runs: [RunEntry]; let reclaimableBytes: Int64 }
struct Health: Decodable { let protocolVersion: Int; let coreVersion: String; let pythonVersion: String }
struct DemoSession: Decodable { let fixtureRoot: String; let workspace: String }
struct Choice: Decodable, Identifiable, Sendable { let value: String; let label: String; var id: String { value } }
struct Failure: Decodable, Error, LocalizedError, Sendable {
    let code: String; let message: String
    var errorDescription: String? { message }
}
struct Packet: Decodable, Sendable {
    let version: Int; let id: String; let event: String
    var ok: Bool?; var data: JSONValue?; var error: Failure?
    var text: String?; var key: String?; var promptID: String?; var kind: String?
    var choices: [Choice]?; var context: [String]?; var requiredText: String?
}
struct CorePrompt: Identifiable {
    let packet: Packet
    var id: String { packet.promptID ?? packet.id }
}
enum AppSection: String, CaseIterable, Identifiable, Hashable {
    case migration = "Migration", backups = "Backups", cleanup = "Cleanup", settings = "Settings"
    var id: String { rawValue }
    var symbol: String {
        switch self {
        case .migration: return "arrow.triangle.swap"
        case .backups: return "archivebox"
        case .cleanup: return "tray.and.arrow.up"
        case .settings: return "slider.horizontal.3"
        }
    }
}
func formattedBytes(_ value: Int64) -> String { ByteCountFormatter.string(fromByteCount: value, countStyle: .file) }

final class BackendClient: @unchecked Sendable {
    private let queue = DispatchQueue(label: "KOReaderBridge.backend", qos: .userInitiated)
    private let lock = NSLock()
    private var process: Process?
    private var input: FileHandle?
    private var requestID = ""
    private var cancellationRequested = false
    func cancel() {
        lock.lock(); cancellationRequested = true; let p = process; lock.unlock()
        if p?.isRunning == true { p?.interrupt() }
    }
    func reply(_ prompt: Packet, text: String) {
        lock.lock(); defer { lock.unlock() }
        guard let handle = input, prompt.id == requestID, let promptID = prompt.promptID else { return }
        let packet: [String: Any] = ["version": 1, "id": requestID, "operation": "reply", "promptID": promptID, "text": text]
        do { var bytes = try JSONSerialization.data(withJSONObject: packet); bytes.append(10); try handle.write(contentsOf: bytes) }
        catch { if process?.isRunning == true { process?.interrupt() } }
    }
    func call(_ request: Request, onEvent: @escaping @Sendable (Packet) -> Void = { _ in }) async throws -> JSONValue {
        try await withCheckedThrowingContinuation { continuation in
            queue.async {
                let output = Pipe(), input = Pipe(), errors = Pipe()
                let p = Process()
                var resolved: JSONValue?
                var failure: Error?
                var stderrBytes = Data()
                let stderrLock = NSLock()
                do {
                    guard let resources = Bundle.main.resourceURL else { throw Failure(code: "installation", message: "Application resources are missing.") }
                    let python = resources.appendingPathComponent("python/bin/python3")
                    let helper = resources.appendingPathComponent("backend/bridge_desktop_helper.py")
                    guard FileManager.default.isExecutableFile(atPath: python.path), FileManager.default.fileExists(atPath: helper.path) else {
                        throw Failure(code: "installation", message: "The bundled backend is missing. Rebuild or reinstall the complete app.")
                    }
                    p.executableURL = python
                    p.arguments = ["-I", "-B", helper.path]
                    p.currentDirectoryURL = resources
                    p.environment = ["PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": FileManager.default.homeDirectoryForCurrentUser.path,
                                     "TMPDIR": NSTemporaryDirectory(), "LC_CTYPE": "UTF-8"]
                    p.standardInput = input; p.standardOutput = output; p.standardError = errors
                    errors.fileHandleForReading.readabilityHandler = { handle in
                        let bytes = handle.availableData
                        stderrLock.lock()
                        if stderrBytes.count < 32768 { stderrBytes.append(bytes.prefix(32768 - stderrBytes.count)) }
                        stderrLock.unlock()
                    }
                    self.lock.lock()
                    self.requestID = request.id; self.process = p; self.input = input.fileHandleForWriting
                    self.cancellationRequested = false
                    self.lock.unlock()
                    try p.run()
                    var payload = try JSONEncoder().encode(request)
                    guard payload.count < 65536 else { throw Failure(code: "request", message: "The request is too large.") }
                    payload.append(10)
                    try input.fileHandleForWriting.write(contentsOf: payload)
                    let timer = DispatchSource.makeTimerSource(queue: DispatchQueue.global())
                    timer.schedule(deadline: .now() + (request.operation == "execute" ? 86400 : 60))
                    timer.setEventHandler { [weak self] in self?.cancel() }
                    timer.resume()
                    defer { timer.cancel() }
                    var buffer = Data(); var total = 0
                    while true {
                        let bytes = output.fileHandleForReading.availableData
                        if bytes.isEmpty { break }
                        total += bytes.count; buffer.append(bytes)
                        if buffer.count > 524288 || total > 64 * 1024 * 1024 {
                            failure = Failure(code: "protocol", message: "Backend output exceeded its safety limit.")
                            self.cancel(); break
                        }
                        while let newline = buffer.firstIndex(of: 10) {
                            let line = Data(buffer[..<newline]); buffer.removeSubrange(...newline)
                            let packet = try JSONDecoder().decode(Packet.self, from: line)
                            guard packet.version == 1, packet.id == request.id, ["log", "prompt", "result"].contains(packet.event) else {
                                throw Failure(code: "protocol", message: "Unexpected response from the bundled backend.")
                            }
                            if packet.event == "result" {
                                guard resolved == nil, failure == nil else { throw Failure(code: "protocol", message: "Duplicate backend result.") }
                                if packet.ok == true { resolved = packet.data ?? .null }
                                else { failure = packet.error ?? Failure(code: "backend", message: "The operation failed.") }
                            } else { onEvent(packet) }
                        }
                    }
                    input.fileHandleForWriting.closeFile()
                    p.waitUntilExit()
                    if !buffer.isEmpty { failure = Failure(code: "protocol", message: "The backend response was incomplete.") }
                    if resolved == nil && failure == nil {
                        failure = Failure(code: "process", message: "The backend exited without a result. Keep any recovery files and inspect Backups.")
                    }
                    if p.terminationStatus != 0 && failure == nil {
                        failure = Failure(code: "process", message: "The backend could not complete the request.")
                    }
                } catch {
                    failure = error
                    if p.isRunning { p.interrupt(); p.waitUntilExit() }
                }
                errors.fileHandleForReading.readabilityHandler = nil
                self.lock.lock(); self.process = nil; self.input = nil; self.requestID = ""; self.lock.unlock()
                if let failure { continuation.resume(throwing: failure) }
                else { continuation.resume(returning: resolved ?? .null) }
            }
        }
    }
}

struct PreferenceStore {
    let folder: URL
    var file: URL { folder.appendingPathComponent("Preferences.json") }
    func load() throws -> Configuration {
        var defaults = Configuration()
        defaults.outputRoot = folder.appendingPathComponent("Migration Data").path
        guard FileManager.default.fileExists(atPath: file.path) else { return defaults }
        let values = try contents()
        var dictionary = try JSONSerialization.jsonObject(with: JSONEncoder().encode(defaults)) as! [String: Any]
        for (key, value) in values["configuration"] as? [String: Any] ?? [:] { dictionary[key] = value }
        return try JSONDecoder().decode(Configuration.self, from: JSONSerialization.data(withJSONObject: dictionary))
    }
    private func contents() throws -> [String: Any] {
        let attributes = try FileManager.default.attributesOfItem(atPath: file.path)
        guard attributes[.type] as? FileAttributeType == .typeRegular, ((attributes[.size] as? NSNumber)?.intValue ?? 0) < 65536 else {
            throw Failure(code: "preferences", message: "The preferences file is unsafe or too large.")
        }
        guard let obj = try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as? [String: Any],
              let schema = obj["schemaVersion"] as? NSNumber,
              CFGetTypeID(schema) != CFBooleanGetTypeID(), schema.doubleValue == 1,
              obj["configuration"] == nil || obj["configuration"] is [String: Any] else {
            throw Failure(code: "preferences", message: "Preferences use an unsupported format. The original file has been kept.")
        }
        return obj
    }
    func save(_ config: Configuration) throws {
        guard config.outputRoot.hasPrefix("/"), config.outputRoot != "/", config.outputRoot != "/Volumes", !config.outputRoot.hasPrefix("/Volumes/"),
              config.sourceModel.count <= 100, config.targetModel.count <= 100,
              (1...100).contains(config.keepSuccessful) else {
            throw Failure(code: "preferences", message: "Choose a Mac backup folder, short model labels and retention between 1 and 100.")
        }
        if FileManager.default.fileExists(atPath: folder.path) {
            let a = try FileManager.default.attributesOfItem(atPath: folder.path)
            guard a[.type] as? FileAttributeType == .typeDirectory else { throw Failure(code: "preferences", message: "Preferences cannot follow symbolic links.") }
        }
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        var values: [String: Any] = ["schemaVersion": 1]
        if FileManager.default.fileExists(atPath: file.path) { values = try contents() }
        var stored = values["configuration"] as? [String: Any] ?? [:]
        let fresh = try JSONSerialization.jsonObject(with: JSONEncoder().encode(config)) as! [String: Any]
        for (key, value) in fresh { stored[key] = value }
        values["configuration"] = stored
        try JSONSerialization.data(withJSONObject: values, options: [.prettyPrinted, .sortedKeys]).write(to: file, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
    }
}

@MainActor final class AppModel: ObservableObject {
    @Published var section: AppSection = .migration
    @Published var config = Configuration()
    @Published var runs: [RunEntry] = []
    @Published var selectedRun: String?
    @Published var summary: [String: JSONValue] = [:]
    @Published var logs: [String] = []
    @Published var busy = false
    @Published var phase = "Ready"
    @Published var notice = ""
    @Published var problem: String?
    @Published var prompt: CorePrompt?
    @Published var pendingWorkflow: Workflow?
    @Published var health: Health?
    @Published var sample: DemoSession?
    @Published var reclaimable: Int64 = 0
    private(set) var preferencesWritable = true
    let backend = BackendClient()
    let store: PreferenceStore
    let testRoot: URL?
    var autoReply = false
    var declineFinal = false
    var workspace: String { sample?.workspace ?? config.outputRoot }
    var currentRun: RunEntry? { runs.first { $0.id == selectedRun } }
    init() {
        let args = CommandLine.arguments
        if let i = args.firstIndex(of: "--test-root"), args.count > i + 1 {
            testRoot = URL(fileURLWithPath: args[i + 1], isDirectory: true)
        } else { testRoot = nil }
        let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        store = PreferenceStore(folder: testRoot ?? appSupport.appendingPathComponent("KOReader Bridge", isDirectory: true))
        do { config = try store.load() }
        catch { config.outputRoot = store.folder.appendingPathComponent("Migration Data").path; problem = error.localizedDescription; preferencesWritable = false }
    }
    func save() {
        guard !busy && preferencesWritable else { return }
        do { try store.save(config); notice = "Preferences saved."; problem = nil }
        catch { problem = error.localizedDescription }
    }
    func chooseFolder() {
        guard !busy else { return }
        let panel = NSOpenPanel()
        panel.canChooseFiles = false; panel.canChooseDirectories = true; panel.canCreateDirectories = true
        panel.message = "Choose a private Mac folder for migration batches. Existing CLI batches can be reopened here."
        if panel.runModal() == .OK, let url = panel.url { config.outputRoot = url.path; save(); Task { await refresh() } }
    }
    func baseRequest(_ operation: String) -> Request {
        Request(operation: operation, workspace: workspace, keepSuccessful: config.keepSuccessful, fixtureRoot: sample?.fixtureRoot)
    }
    func startup() async {
        do { health = try await backend.call(Request(operation: "health")).decode(Health.self) }
        catch { problem = error.localizedDescription }
        await refresh()
    }
    func refresh() async {
        guard !busy else { return }
        busy = true; defer { busy = false }
        do {
            let data = try await backend.call(baseRequest("catalog")).decode(RunCatalog.self)
            runs = data.runs; reclaimable = data.reclaimableBytes
            if !runs.contains(where: { $0.id == selectedRun }) { selectedRun = nil; summary = [:] }
        } catch { problem = error.localizedDescription }
    }
    func details() async {
        guard !busy, let id = selectedRun else { summary = [:]; return }
        busy = true; defer { busy = false }
        do { var req = baseRequest("details"); req.runID = id; summary = try await backend.call(req).object["summary"]?.object ?? [:] }
        catch { problem = error.localizedDescription }
    }
    func createSample() async {
        guard !busy else { return }
        busy = true; defer { busy = false }
        do {
            sample = try await backend.call(baseRequest("create_demo")).decode(DemoSession.self)
            notice = "Sample session: all readers and batches here are synthetic."
            runs = try await backend.call(baseRequest("catalog")).decode(RunCatalog.self).runs
            section = .migration
        } catch { problem = error.localizedDescription }
    }
    func leaveSample() { guard !busy else { return }; sample = nil; logs = []; notice = ""; Task { await refresh() } }
    func review(_ workflow: Workflow) { guard !busy else { return }; pendingWorkflow = workflow }
    func receive(_ event: Packet) {
        if event.event == "log", let text = event.text {
            let visible = sample.map { text.replacingOccurrences(of: $0.fixtureRoot, with: "Sample Readers") } ?? text
            logs.append(visible); if logs.count > 400 { logs.removeFirst(logs.count - 400) }
            phase = visible
        } else if event.event == "prompt" {
            if autoReply && sample != nil {
                let answer: String
                if event.kind == "boolean" { answer = declineFinal && event.key == "confirm.migration" ? "n" : "y" }
                else if event.kind == "choice" { answer = event.choices?.first?.value ?? "1" }
                else if !(event.requiredText ?? "").isEmpty { answer = event.requiredText! }
                else { answer = "" }
                backend.reply(event, text: answer)
            } else {
                var visible = event
                if let sample {
                    visible.text = event.text?.replacingOccurrences(of: sample.fixtureRoot, with: "Sample Readers")
                    visible.context = event.context?.map { $0.replacingOccurrences(of: sample.fixtureRoot, with: "Sample Readers") }
                }
                prompt = CorePrompt(packet: visible)
            }
        }
    }
    func answer(_ text: String) { guard let p = prompt else { return }; backend.reply(p.packet, text: text); prompt = nil }
    func cancel() { guard busy else { return }; phase = "Stopping safely. Keep the current reader connected until recovery finishes."; prompt = nil; backend.cancel() }
    @discardableResult func execute(_ workflow: Workflow) async -> Bool {
        guard !busy else { return false }
        busy = true; pendingWorkflow = nil; logs = []; problem = nil; notice = ""; phase = "Starting…"
        defer { busy = false; prompt = nil }
        do {
            var request = baseRequest("execute"); request.config = workflow
            let result = try await backend.call(request) { [weak self] packet in Task { @MainActor in self?.receive(packet) } }
            if let data = result.object["runs"] { runs = try data.decode([RunEntry].self) }
            let exit = Int(result.object["exitCode"]?.number ?? 1)
            if exit == 0 {
                let status = result.object["status"]?.string ?? ""
                if status == "cancelled" { notice = "Cancelled. Target files were not modified."; phase = "Cancelled" }
                else if workflow.action == "delete" {
                    let deleted = !runs.contains { $0.id == workflow.runID }
                    notice = deleted ? "Selected batch deleted." : "Cleanup cancelled. No batch was deleted."
                    phase = deleted ? "Cleanup complete" : "Cancelled"
                } else { notice = workflow.dryRun ? "Preview complete. Reader files were not changed." : "Operation finished. Review its retained batch."; phase = "Finished" }
            }
            else {
                problem = exit == 3 ? "Recovery needs attention. Keep the reader connected and preserve all backups." :
                          exit == 2 ? "The operation failed and rolled back. Recovery backups were retained." :
                          exit == 130 ? "Operation interrupted. Review the latest batch before retrying." :
                          "The operation could not complete. Review the activity and retained batch."
                phase = "Stopped"
            }
            let createdID = result.object["runID"]?.string ?? ""
            selectedRun = createdID.isEmpty ? runs.first?.id : createdID
            return exit == 0
        } catch { problem = error.localizedDescription; phase = "Stopped"; return false }
    }
    func revealSelected() {
        guard let id = selectedRun, runs.contains(where: { $0.id == id }) else { return }
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: workspace).appendingPathComponent("runs").appendingPathComponent(id)])
    }
    func confirmClose() -> Bool {
        guard busy else { return true }
        let alert = NSAlert()
        alert.messageText = "An operation is still active"
        alert.informativeText = "Request a safe stop and wait for recovery before quitting or disconnecting a reader."
        alert.addButton(withTitle: "Keep Working"); alert.addButton(withTitle: "Request Safe Stop")
        if alert.runModal() == .alertSecondButtonReturn { cancel() }
        return false
    }
}

struct PromptView: View {
    @ObservedObject var model: AppModel
    let prompt: CorePrompt
    @State private var input = ""
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Label("Your confirmation is needed", systemImage: "person.crop.circle.badge.questionmark").font(.title2)
            Text(prompt.packet.text ?? "Continue?").textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
            if let context = prompt.packet.context, !context.isEmpty {
                ScrollView { Text(context.joined(separator: "\n")).font(.callout).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }
                    .frame(maxHeight: 180).padding(12).background(.quaternary, in: RoundedRectangle(cornerRadius: 8))
            }
            if prompt.packet.kind == "choice" {
                ForEach(prompt.packet.choices ?? []) { choice in Button(choice.label) { model.answer(choice.value) }.frame(maxWidth: .infinity, alignment: .leading) }
            } else if prompt.packet.kind == "text" {
                if let required = prompt.packet.requiredText, !required.isEmpty {
                    Text("Type exactly: \(required)").font(.callout).textSelection(.enabled)
                }
                TextField("Response", text: $input).textFieldStyle(.roundedBorder)
            }
            HStack {
                Button("Stop operation", role: .cancel) { model.cancel() }.keyboardShortcut(.cancelAction)
                Spacer()
                if prompt.packet.kind == "boolean" {
                    Button("No") { model.answer("n") }.keyboardShortcut(.defaultAction)
                    Button("Yes, continue") { model.answer("y") }
                } else if prompt.packet.kind != "choice" {
                    Button("Continue") { model.answer(input) }
                        .disabled(prompt.packet.kind == "text" && (!(prompt.packet.requiredText ?? "").isEmpty ? input != prompt.packet.requiredText : input.isEmpty))
                        .keyboardShortcut(.defaultAction)
                }
            }
        }.padding(24).frame(width: 560).interactiveDismissDisabled()
    }
}
struct ReviewView: View {
    @ObservedObject var model: AppModel
    let workflow: Workflow
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Label(workflow.dryRun ? "Review preview" : workflow.action == "delete" ? "Review batch deletion" : "Review operation", systemImage: workflow.dryRun ? "magnifyingglass" : "exclamationmark.shield").font(.title2)
            Text(workflow.action == "delete" ? "Only the selected eligible batch can be deleted. The core will recheck protection and require exact typed confirmation." :
                 workflow.action == "restore" ? "Restore returns the recorded TARGET state and can remove listed added files. Verified undo backups are retained." :
                 workflow.mode == "audit" ? "Inspect and report without changing reader files or creating backup ZIPs." :
                 workflow.mode == "koreader" ? "Replace only the entire target KOReader directory after verified backups. External books and fonts are excluded." :
                 workflow.mode == "full" ? "Replace the entire target KOReader directory and copy supported books, reading data and root fonts. Matching paths can be overwritten; unrelated external target books are retained." :
                 "Copy only the selected library content under the chosen conflict policy. Target KOReader stays installed.")
                .fixedSize(horizontal: false, vertical: true)
            LabeledContent("Mode", value: workflow.mode.uppercased())
            LabeledContent("Action", value: workflow.dryRun ? "Read-only device preview" : workflow.action.capitalized)
            if let id = workflow.runID { LabeledContent("Batch", value: id) }
            if model.sample != nil { Label("Synthetic sample readers only", systemImage: "testtube.2").foregroundStyle(.teal) }
            Text("Keep readers disconnected until requested. Connect one at a time and confirm the physical roles and source-build compatibility. A full dry-run may create private local reports, but does not change readers or create backup ZIPs.")
                .font(.callout).foregroundStyle(.secondary)
            HStack {
                Button("Not now", role: .cancel) { model.pendingWorkflow = nil }.keyboardShortcut(.defaultAction)
                Spacer()
                Button(workflow.dryRun ? "Start preview" : "Continue to core confirmations") { Task { await model.execute(workflow) } }
            }
        }.padding(24).frame(width: 560)
    }
}
extension Workflow: Identifiable { var id: String { action + mode + String(dryRun) + (runID ?? "") } }

struct MigrationView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        VStack(spacing: 0) {
            Form {
                Section("Migration scope") {
                    Picker("Mode", selection: $model.config.mode) {
                        Text("KOReader directory only").tag("koreader")
                        Text("Full setup and library").tag("full")
                        Text("Library content only").tag("library")
                        Text("Audit only").tag("audit")
                    }
                    Text(model.config.mode == "koreader" ? "Settings, plugins and reading data inside KOReader. External books and fonts are untouched." :
                         model.config.mode == "full" ? "Complete KOReader plus supported ebooks, reading data and root fonts. Target-only external books are retained." :
                         model.config.mode == "library" ? "Keep the installed target runtime and choose which library content to copy." : "Inspect and report without changing reader files.")
                        .font(.callout).foregroundStyle(.secondary)
                }
                Section("Reader roles") {
                    TextField("Source model label", text: $model.config.sourceModel, prompt: Text("Confirm when connected"))
                    TextField("Target model label", text: $model.config.targetModel, prompt: Text("Confirm when connected"))
                    Text("Model labels help you recognize the roles. The core still requires physical confirmation and different device fingerprints.")
                        .font(.callout).foregroundStyle(.secondary)
                }
                if model.config.mode == "library" {
                    Section("Library options") {
                        Toggle("Books and adjacent reading data", isOn: $model.config.books)
                        Toggle("Root fonts", isOn: $model.config.fonts)
                        Toggle("Include reading data", isOn: $model.config.readingData)
                        Picker("Matching paths", selection: $model.config.conflict) {
                            Text("Overwrite from source").tag("overwrite"); Text("Keep target file and metadata").tag("keep-target")
                        }
                        TextField("Include directories (one per line)", text: $model.config.includePaths, axis: .vertical)
                        TextField("Exclude directories (one per line)", text: $model.config.excludePaths, axis: .vertical)
                        TextField("Additional extensions (one per line)", text: $model.config.extensions, axis: .vertical)
                    }
                }
                Section("Output") {
                    LabeledContent("Private backup folder") { Text(model.sample == nil ? model.workspace : "Sample Readers / Workspace").lineLimit(2).textSelection(.enabled).foregroundStyle(.secondary) }
                    Text("Backups may include plugin credentials and reading history. They stay in this folder; the app has no upload or telemetry action.").font(.callout).foregroundStyle(.secondary)
                }
            }.formStyle(.grouped).disabled(model.busy)
            HStack {
                Button("Save choices") { model.save() }.disabled(model.busy || !model.preferencesWritable)
                Spacer()
                Button("Preview changes") { model.review(model.config.workflow(dryRun: true)) }.disabled(model.busy).keyboardShortcut("p", modifiers: [.command, .shift])
                Button(model.config.mode == "audit" ? "Start audit" : "Start migration") { model.review(model.config.workflow(dryRun: model.config.mode == "audit")) }
                    .buttonStyle(.borderedProminent).disabled(model.busy)
            }.padding(16)
            ActivityView(model: model)
        }
    }
}
struct ActivityView: View {
    @ObservedObject var model: AppModel
    @State private var showDetails = false
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                if model.busy { ProgressView().controlSize(.small) }
                Text(model.busy ? "Operation in progress" : "Activity").font(.headline)
                Spacer()
                if model.busy { Button("Request safe stop", role: .destructive) { model.cancel() } }
            }
            if model.logs.isEmpty {
                Text("Preview the plan before writing. Progress and core confirmations appear here.").foregroundStyle(.secondary).font(.callout)
            } else {
                Text(model.phase).font(.callout).lineLimit(2).textSelection(.enabled)
                DisclosureGroup("Show activity details", isExpanded: $showDetails) {
                    ScrollView {
                        Text(model.logs.suffix(100).joined(separator: "\n")).font(.system(.caption, design: .monospaced))
                            .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                    }.frame(height: 105)
                }
            }
        }.padding(16).background(Color(nsColor: .controlBackgroundColor))
    }
}
struct BackupsView: View {
    @ObservedObject var model: AppModel
    var cleanup = false
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if model.runs.isEmpty {
                ContentUnavailableView(cleanup ? "No batches to review" : "Your backups will appear here", systemImage: "archivebox",
                    description: Text("Complete a migration or choose an existing CLI backup folder in Settings. Sample readers let you explore safely."))
            } else {
                if cleanup {
                    HStack { Text("Eligible to reclaim").font(.headline); Spacer(); Text(formattedBytes(model.reclaimable)).monospacedDigit() }.padding(16)
                    Text("Recent successes, dependencies, recovery points and uncertain batches stay protected. Select an eligible batch; deletion still requires core confirmation.")
                        .font(.callout).foregroundStyle(.secondary).padding(.horizontal, 16).padding(.bottom, 12)
                }
                Table(model.runs, selection: $model.selectedRun) {
                    TableColumn("Batch") { row in Text(row.id).lineLimit(1) }.width(min: 190, ideal: 250)
                    TableColumn("Status") { row in Label(row.status, systemImage: row.status == "success" ? "checkmark.circle" : row.status == "needs-recovery" ? "exclamationmark.triangle" : "doc.text").foregroundStyle(row.status == "needs-recovery" ? Color.orange : Color.primary) }.width(min: 110, ideal: 140)
                    TableColumn("Operation") { row in Text(row.operation.replacingOccurrences(of: "-", with: " ").capitalized).help(row.operation) }.width(min: 90, ideal: 130)
                    TableColumn("Size") { row in Text(formattedBytes(row.bytes)).monospacedDigit() }.width(min: 70, ideal: 90)
                    TableColumn("Retention") { row in Text(row.eligible ? "Eligible" : row.protection).lineLimit(2).help(row.protection) }.width(min: 110, ideal: 180)
                }.onChange(of: model.selectedRun) { _, _ in Task { await model.details() } }
                if let row = model.currentRun {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack { Text(row.id).font(.headline).textSelection(.enabled); Spacer(); Button("Show in Finder") { model.revealSelected() } }
                        if !model.summary.isEmpty {
                            HStack(spacing: 22) {
                                ForEach(model.summary.keys.sorted(), id: \.self) { key in
                                    VStack(alignment: .leading) {
                                        Text(key.replacingOccurrences(of: "_", with: " ").capitalized).foregroundStyle(.secondary)
                                        Text("\(Int(model.summary[key]?.object["count"]?.number ?? 0)) files").monospacedDigit()
                                    }.font(.callout)
                                }
                            }
                        }
                        if cleanup {
                            Button("Delete selected batch…", role: .destructive) { model.review(model.config.workflow(action: "delete", dryRun: false, runID: row.id)) }
                                .disabled(!row.eligible || model.busy)
                        } else {
                            HStack {
                                Button("Preview saved source") { model.review(model.config.workflow(action: "reuse", dryRun: true, runID: row.id)) }
                                Button("Migrate saved source…") { model.review(model.config.workflow(action: "reuse", dryRun: false, runID: row.id)) }
                            }.disabled(!row.canReuse || model.busy)
                            HStack {
                                Button("Preview target restore") { model.review(model.config.workflow(action: "restore", dryRun: true, runID: row.id)) }
                                Button("Restore target…") { model.review(model.config.workflow(action: "restore", dryRun: false, runID: row.id)) }
                            }.disabled(!row.canRestore || model.busy)
                            if !row.canReuse && !row.canRestore { Text("This batch has no reusable source or exact target snapshot. Its recovery files are retained.").font(.callout).foregroundStyle(.secondary) }
                        }
                    }.padding(16)
                }
            }
            ActivityView(model: model)
        }
    }
}
struct SettingsView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        Form {
            Section("Private storage") {
                LabeledContent("Backup folder") { Text(model.config.outputRoot).textSelection(.enabled).lineLimit(3) }
                Button("Choose folder…") { model.chooseFolder() }
                Text("Choose an existing CLI output folder to reopen its batches. Existing archives and unknown metadata are preserved.").font(.callout).foregroundStyle(.secondary)
            }
            Section("Workflow") {
                Picker("Migration language", selection: $model.config.locale) {
                    Text("English").tag("en"); Text("繁體中文").tag("zh-Hant"); Text("简体中文").tag("zh-Hans")
                }
                Stepper("Protect at least \(model.config.keepSuccessful) recent successful batches", value: $model.config.keepSuccessful, in: 1...100)
                Text("The native app interface is English. Core prompts, progress and reports use the selected language. Additional dependency and recovery protections always apply.").font(.callout).foregroundStyle(.secondary)
            }
            Section("Application") {
                LabeledContent("Core", value: model.health?.coreVersion ?? "Checking…")
                LabeledContent("Bundled Python", value: model.health?.pythonVersion ?? "Checking…")
                Text("Offline operation. No shell Python, AI service or account required. Local builds are ad-hoc signed and are not notarized.").font(.callout).foregroundStyle(.secondary)
                Button("Save preferences") { model.save() }.disabled(!model.preferencesWritable)
                Button("Open usage guide") { if let url = Bundle.main.resourceURL?.appendingPathComponent("backend/docs/MACOS.md") { NSWorkspace.shared.open(url) } }
            }
        }.formStyle(.grouped).disabled(model.busy)
    }
}
struct MainView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        NavigationSplitView {
            List(AppSection.allCases, selection: Binding<AppSection?>(get: { model.section }, set: { if let value = $0 { model.section = value } })) { item in Label(item.rawValue, systemImage: item.symbol).tag(item) }
                .navigationTitle("KOReader Bridge")
                .safeAreaInset(edge: .bottom) {
                    VStack(alignment: .leading, spacing: 8) {
                        Label(model.sample == nil ? "Private, offline workspace" : "Sample readers", systemImage: model.sample == nil ? "lock.shield" : "testtube.2")
                            .font(.caption).foregroundStyle(.secondary)
                        if model.sample != nil { Button("Leave sample session") { model.leaveSample() }.disabled(model.busy) }
                        else { Button("Try sample readers") { Task { await model.createSample() } }.disabled(model.busy) }
                    }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
                }.navigationSplitViewColumnWidth(min: 190, ideal: 210, max: 250)
        } detail: {
            VStack(spacing: 0) {
                if model.sample != nil { HStack { Label("Sample data — no physical readers are used", systemImage: "testtube.2"); Spacer() }.font(.callout).padding(12).background(.teal.opacity(0.12)) }
                if let problem = model.problem {
                    HStack(alignment: .top) { Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange); Text(problem).textSelection(.enabled); Spacer(); Button("Dismiss") { model.problem = nil } }.padding(12).background(.orange.opacity(0.1))
                } else if !model.notice.isEmpty {
                    HStack { Image(systemName: "checkmark.circle").foregroundStyle(.teal); Text(model.notice); Spacer() }.font(.callout).padding(12)
                }
                switch model.section {
                case .migration: MigrationView(model: model)
                case .backups: BackupsView(model: model)
                case .cleanup: BackupsView(model: model, cleanup: true)
                case .settings: SettingsView(model: model)
                }
            }.navigationTitle(model.section.rawValue)
                .toolbar {
                    ToolbarItem { Button { Task { await model.refresh() } } label: { Label("Refresh batches", systemImage: "arrow.clockwise") }.disabled(model.busy).keyboardShortcut("r", modifiers: .command) }
                }
        }.tint(.teal).frame(minWidth: 940, minHeight: 680)
            .sheet(item: $model.prompt) { PromptView(model: model, prompt: $0) }
            .sheet(item: $model.pendingWorkflow) { ReviewView(model: model, workflow: $0) }
            .background(WindowLink(model: model))
            .task { await model.startup(); if CommandLine.arguments.contains("--integration-test") { await NativeChecks.run(model) } }
    }
}
@MainActor final class WindowGuard: NSObject, NSWindowDelegate {
    weak var model: AppModel?
    func windowShouldClose(_ sender: NSWindow) -> Bool { model?.confirmClose() ?? true }
}
struct WindowLink: NSViewRepresentable {
    let model: AppModel
    func makeNSView(context: Context) -> NSView { let v = BridgeWindowView(); v.model = model; return v }
    func updateNSView(_ view: NSView, context: Context) {}
}
@MainActor final class BridgeWindowView: NSView {
    weak var model: AppModel?
    let guardDelegate = WindowGuard()
    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        if let window { guardDelegate.model = model; window.delegate = guardDelegate }
    }
}
@MainActor final class AppDelegate: NSObject, NSApplicationDelegate {
    static weak var model: AppModel?
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply { Self.model?.confirmClose() == false ? .terminateCancel : .terminateNow }
}
@main @MainActor struct KOReaderBridgeApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var model = AppModel()
    var body: some Scene {
        Window("KOReader Bridge", id: "main") {
            MainView(model: model).onAppear { AppDelegate.model = model; NSApp.setActivationPolicy(.regular); NSApp.activate(ignoringOtherApps: true) }
        }.defaultSize(width: 1120, height: 800)
            .commands {
                CommandGroup(replacing: .newItem) {}
                CommandGroup(replacing: .saveItem) { Button("Save choices") { model.save() }.keyboardShortcut("s", modifiers: .command).disabled(model.busy || !model.preferencesWritable) }
                CommandGroup(after: .appInfo) { Button("KOReader Bridge Settings") { model.section = .settings }.keyboardShortcut(",", modifiers: .command) }
            }
    }
}
