import SwiftUI
import AppKit
import Foundation
import CoreFoundation

// Explicit bundle lookup lets the in-app language change without restarting macOS.
enum NativeLanguage {
    static let supported = ["en", "zh-Hant", "zh-Hans"]
    private static let lock = NSLock()
    private static var selected = "en"
    static var locale: String {
        get { lock.lock(); defer { lock.unlock() }; return selected }
        set { lock.lock(); defer { lock.unlock() }; selected = supported.contains(newValue) ? newValue : "en" }
    }
    static func text(_ key: String, values: [String: String] = [:]) -> String {
        let language = locale
        let bundle = Bundle.main.path(forResource: language, ofType: "lproj").flatMap(Bundle.init(path:)) ?? Bundle.main
        var result = bundle.localizedString(forKey: key, value: key, table: "Localizable")
        for (name, value) in values { result = result.replacingOccurrences(of: "{" + name + "}", with: value) }
        return result
    }
}
func native(_ key: String, _ values: [String: String] = [:]) -> String { NativeLanguage.text(key, values: values) }

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
    var readers: [String: ReaderSelection]? = nil
    var review: MigrationReview? = nil
}
struct MigrationReview: Codable, Sendable {
    let rolesConfirmed: Bool; let compatible: Bool; let identity: String; let cloneConfirmed: Bool
}
struct ReaderSelection: Codable, Sendable { let id: String; let model: String }
struct Request: Encodable, Sendable {
    let version = 1
    let id = UUID().uuidString
    var operation: String
    var workspace: String?
    var config: Workflow?
    var runID: String?
    var keepSuccessful: Int?
    var fixtureRoot: String?
    var readerSession: String?
}
struct RunEntry: Decodable, Identifiable, Hashable, Sendable {
    let id: String; let status: String; let operation: String; let bytes: Int64; let endedAt: String
    let targetModified: Bool; let eligible: Bool; let protection: String; let canReuse: Bool; let canRestore: Bool
    var protectionKey: String? = nil
    var protectionText: String { protectionKey.map { native($0) } ?? protection }
    var operationText: String { native(["migration": "Migration", "saved-source": "Saved source", "restore-target": "Restore target", "sample": "Sample", "unknown": "Unknown"][operation] ?? operation) }
}
struct RunCatalog: Decodable { let runs: [RunEntry]; let reclaimableBytes: Int64 }
struct ConnectedReaders: Decodable {
    let count: Int
    let modelHint: String?
    let status: String
    let synthetic: Bool
    var readers: [ConnectedReader]? = nil
    var models: [String]? = nil
    var message: String {
        switch status {
        case "connected": return count == 1 ? "One Kobo connected. Choose its role below." : native("{count} Kobos connected. Choose source and target below.", ["count": String(count)])
        case "multiple": return "Multiple Kobos connected. Connect one reader at a time."
        case "unknown": return "Kobo connected. Model hint unavailable; enter the model below."
        case "unavailable": return "Kobo connected. Its model hint cannot be read safely."
        default: return "No Kobo connected. Plug in a reader and choose Connect on its screen."
        }
    }
}
struct ConnectedReader: Decodable, Identifiable {
    let id: String; let volume: String; let model: String?; let nativeModel: String?
    let modelCode: String?; let usbModel: String?; let usbVerified: Bool
    var warningCodes: [String]? = nil
    var warningText: String { warningCodes.map { $0.map { native("warning." + $0) }.joined(separator: " ") } ?? warning }
    let warning: String; let selectable: Bool; let freeBytes: Int64; let totalBytes: Int64
    var label: String { (model ?? native("Unknown Kobo model")) + " — " + volume }
}
struct ReaderCorrection: Identifiable {
    let role: String; let readerID: String
    var id: String { role + readerID }
}
struct Health: Decodable { let protocolVersion: Int; let coreVersion: String; let pythonVersion: String }
struct DemoSession: Decodable { let fixtureRoot: String; let workspace: String }
struct Choice: Decodable, Identifiable, Sendable { let value: String; let label: String; var id: String { value } }
struct Failure: Decodable, Error, LocalizedError, Sendable {
    let code: String; let message: String
    var errorDescription: String? {
        let translated = native(message)
        if translated != message || NativeLanguage.locale == "en" { return translated }
        if ["invalid_request", "backend_error", "cancelled"].contains(code) {
            return native("The request could not complete. Diagnostic detail:") + "\n" + message
        }
        return message
    }
}
struct Packet: Decodable, Sendable {
    let version: Int; let id: String; let event: String
    var ok: Bool?; var data: JSONValue?; var error: Failure?
    var role: String?; var model: String?
    var messageKey: String?; var values: [String: String]?; var warningCodes: [String]?
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
                            guard packet.version == 1, packet.id == request.id, ["log", "prompt", "device", "result"].contains(packet.event) else {
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
    @Published var config = Configuration() { didSet { NativeLanguage.locale = config.locale } }
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
    @Published var activeWorkflow: Workflow?
    @Published var health: Health?
    @Published var sample: DemoSession?
    @Published var reclaimable: Int64 = 0
    @Published var connected: ConnectedReaders?
    @Published var checkingReaders = false
    @Published var readerProblem: String?
    @Published var discoveredModels: [String] = []
    @Published var useConnectedReaders = true
    @Published var sourceReaderID = ""
    @Published var targetReaderID = ""
    @Published var readerCorrection: ReaderCorrection?
    @Published var readerApprovals: [String: String] = [:]
    let readerSession = UUID().uuidString
    let deviceBackend = BackendClient()
    private(set) var preferencesWritable = true
    let backend = BackendClient()
    let store: PreferenceStore
    let testRoot: URL?
    var autoReply = false
    var declineFinal = false
    var holdFinal = false
    var testPrompts: [String] = []
    var workspace: String { sample?.workspace ?? config.outputRoot }
    var modelOptions: [String] {
        Array(Set((connected?.models ?? []) + discoveredModels + [config.sourceModel, config.targetModel]).filter { !$0.isEmpty }).sorted()
    }
    var readers: [ConnectedReader] { connected?.readers ?? [] }
    func reviewLabel(_ selection: ReaderSelection) -> String {
        let volume = readers.first { $0.id == selection.id }?.volume
        return selection.model + (volume.map { " — " + $0 } ?? "")
    }
    func readerID(_ role: String) -> String { role == "source" ? sourceReaderID : targetReaderID }
    func chosenModel(_ role: String) -> String { role == "source" ? config.sourceModel : config.targetModel }
    func reader(_ role: String) -> ConnectedReader? { readers.first { $0.id == readerID(role) } }
    func selectReader(_ id: String, role: String) {
        guard !busy else { return }
        let other = role == "source" ? targetReaderID : sourceReaderID
        guard id.isEmpty || id != other else { readerProblem = "Source and target must be different readers."; return }
        if role == "source" { sourceReaderID = id } else { targetReaderID = id }
        readerApprovals[role] = nil
        guard let row = reader(role) else { return }
        if role == "source" { config.sourceModel = row.model ?? "" } else { config.targetModel = row.model ?? "" }
        if !row.warning.isEmpty || row.model == nil { readerCorrection = ReaderCorrection(role: role, readerID: id) }
    }
    func correctModel(_ role: String) {
        guard let row = reader(role), row.selectable, !busy else { return }
        readerCorrection = ReaderCorrection(role: role, readerID: row.id)
    }
    func confirmModel(_ correction: ReaderCorrection, model: String) {
        guard let row = reader(correction.role), row.id == correction.readerID, row.selectable else {
            readerCorrection = nil; readerProblem = "The reader changed. Refresh and choose it again."; return
        }
        let value = model.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty, value.count <= 80 else { return }
        if correction.role == "source" { config.sourceModel = value } else { config.targetModel = value }
        readerApprovals[correction.role] = row.id + "|" + value
        readerCorrection = nil
    }
    func boundWorkflow(_ workflow: Workflow) throws -> Workflow {
        guard useConnectedReaders, workflow.action != "delete" else { return workflow }
        var result = workflow
        var roles: [String: ReaderSelection] = [:]
        for role in workflow.action == "migration" ? ["source", "target"] : ["target"] {
            guard let row = reader(role), row.selectable else {
                throw Failure(code: "reader_choice", message: native("Choose a connected {role} reader. Reconnect and select again if it is offline.", ["role": native(role)]))
            }
            let value = chosenModel(role)
            guard !value.isEmpty else { throw Failure(code: "reader_model", message: native("Choose and confirm the {role} model.", ["role": native(role)])) }
            if !row.warning.isEmpty || row.model?.caseInsensitiveCompare(value) != .orderedSame {
                guard readerApprovals[role] == row.id + "|" + value else {
                    readerCorrection = ReaderCorrection(role: role, readerID: row.id)
                    throw Failure(code: "reader_confirmation", message: native("Confirm the physical {role} model before continuing.", ["role": native(role)]))
                }
            }
            roles[role] = ReaderSelection(id: row.id, model: value)
        }
        if roles["source"]?.id == roles["target"]?.id { throw Failure(code: "same_reader", message: "Source and target must be different readers.") }
        result.readers = roles
        return result
    }
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
        NativeLanguage.locale = config.locale
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
        panel.message = native("Choose a private Mac folder for migration batches. Existing CLI batches can be reopened here.")
        if panel.runModal() == .OK, let url = panel.url { config.outputRoot = url.path; save(); Task { await refresh() } }
    }
    func baseRequest(_ operation: String) -> Request {
        Request(operation: operation, workspace: workspace, keepSuccessful: config.keepSuccessful, fixtureRoot: sample?.fixtureRoot, readerSession: readerSession)
    }
    func startup() async {
        do { health = try await backend.call(Request(operation: "health")).decode(Health.self) }
        catch { problem = error.localizedDescription }
        await refresh()
        await refreshConnected()
    }
    func refreshConnected() async {
        guard !busy && !checkingReaders else { return }
        // Automated verification may never probe physical volumes.
        if testRoot != nil && sample == nil {
            connected = ConnectedReaders(count: 0, modelHint: nil, status: "none", synthetic: true)
            return
        }
        checkingReaders = true
        let fixture = sample?.fixtureRoot
        defer { checkingReaders = false }
        do {
            let request = Request(operation: "devices", workspace: sample?.workspace, fixtureRoot: fixture, readerSession: readerSession)
            let response = try await deviceBackend.call(request).decode(ConnectedReaders.self)
            guard !busy && fixture == sample?.fixtureRoot else { return }
            connected = response; readerProblem = nil
            if let hint = response.modelHint, !discoveredModels.contains(hint) { discoveredModels.append(hint) }
        } catch { readerProblem = "Could not check connected readers. Try refreshing."; connected = nil }
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
            let inventory = try await backend.call(baseRequest("catalog")).decode(RunCatalog.self)
            runs = inventory.runs; reclaimable = inventory.reclaimableBytes
            connected = nil; discoveredModels = []; sourceReaderID = ""; targetReaderID = ""; readerApprovals = [:]
            section = .migration
        } catch { problem = error.localizedDescription }
    }
    func leaveSample() { guard !busy else { return }; sample = nil; connected = nil; discoveredModels = []; sourceReaderID = ""; targetReaderID = ""; readerApprovals = [:]; logs = []; notice = ""; Task { await refresh(); await refreshConnected() } }
    func review(_ workflow: Workflow) {
        guard !busy else { return }
        do {
            var value = try boundWorkflow(workflow); problem = nil
            if value.readers != nil && value.dryRun && ["migration", "reuse"].contains(value.action) {
                value.review = MigrationReview(rolesConfirmed: true, compatible: false, identity: "preserve", cloneConfirmed: false)
                Task { await execute(value) }
            } else { pendingWorkflow = value }
        }
        catch { problem = error.localizedDescription }
    }
    func receive(_ event: Packet) {
        if event.event == "log", let raw = event.text {
            let text = event.messageKey.map { native($0, event.values ?? [:]) } ?? raw
            let visible = sample.map { text.replacingOccurrences(of: $0.fixtureRoot, with: "Sample Readers") } ?? text
            logs.append(visible); if logs.count > 400 { logs.removeFirst(logs.count - 400) }
            phase = visible
        } else if event.event == "device", let name = event.model, name.count <= 100 {
            if event.role == "source" { config.sourceModel = name }
            else if event.role == "target" { config.targetModel = name }
        } else if event.event == "prompt" {
            if testRoot != nil && sample != nil { testPrompts.append(event.key ?? "") }
            if autoReply && sample != nil && !(holdFinal && event.key == "confirm.migration") {
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
        busy = true; pendingWorkflow = nil; activeWorkflow = workflow; logs = []; testPrompts = []; problem = nil; notice = ""; phase = "Starting…"
        defer { busy = false; prompt = nil; activeWorkflow = nil }
        do {
            var request = baseRequest("execute"); request.config = workflow
            let result = try await backend.call(request) { [weak self] packet in Task { @MainActor in self?.receive(packet) } }
            if let data = result.object["runs"] { runs = try data.decode([RunEntry].self) }
            if let bytes = result.object["reclaimableBytes"] { reclaimable = Int64(bytes.number) }
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
        alert.messageText = native("An operation is still active")
        alert.informativeText = native("Request a safe stop and wait for recovery before quitting or disconnecting a reader.")
        alert.addButton(withTitle: native("Keep Working")); alert.addButton(withTitle: native("Request Safe Stop"))
        if alert.runModal() == .alertSecondButtonReturn { cancel() }
        return false
    }
}

struct PromptView: View {
    @ObservedObject var model: AppModel
    let prompt: CorePrompt
    @State private var input = ""
    var displayedText: String {
        guard let key = prompt.packet.messageKey else { return prompt.packet.text ?? native("Continue?") }
        var values = prompt.packet.values ?? [:]
        if let role = values["role"] { values["role"] = native(role) }
        return native(key, values) + " " + (prompt.packet.warningCodes ?? []).map { native("warning." + $0) }.joined(separator: " ")
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Label(native(prompt.packet.key == "confirm.migration" ? "Ready to migrate" : "Your confirmation is needed"), systemImage: "person.crop.circle.badge.questionmark").font(.title2)
            if prompt.packet.key == "confirm.migration", let workflow = model.activeWorkflow, workflow.review != nil {
                LabeledContent(native("Mode"), value: workflow.mode.uppercased())
                if let source = workflow.readers?["source"] { LabeledContent(native("Source"), value: model.reviewLabel(source)) }
                else if let id = workflow.runID { LabeledContent(native("Saved source"), value: id) }
                if let target = workflow.readers?["target"] { LabeledContent(native("Target"), value: model.reviewLabel(target)) }
                if ["full", "koreader"].contains(workflow.mode), let review = workflow.review {
                    LabeledContent(native("Target identity"), value: native(review.identity == "clone" ? "Clone source identity" : review.identity == "new" ? "Generate a new identity" : "Keep target identity; create one if missing"))
                }
                Text(native("Required recovery backups are ready. The target has not been changed. Continue to apply the reviewed migration; identity will be checked again before writing."))
                    .fixedSize(horizontal: false, vertical: true)
            }
            Text(displayedText).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
            if let context = prompt.packet.context, !context.isEmpty {
                DisclosureGroup(native("Show preparation details")) {
                    ScrollView { Text(context.joined(separator: "\n")).font(.callout).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }
                        .frame(maxHeight: 180).padding(12).background(.quaternary, in: RoundedRectangle(cornerRadius: 8))
                }
            }
            if prompt.packet.kind == "choice" {
                ForEach(prompt.packet.choices ?? []) { choice in Button(choice.label) { model.answer(choice.value) }.frame(maxWidth: .infinity, alignment: .leading) }
            } else if prompt.packet.kind == "text" {
                if let required = prompt.packet.requiredText, !required.isEmpty {
                    Text(native("Type exactly: {text}", ["text": required])).font(.callout).textSelection(.enabled)
                }
                TextField(native("Response"), text: $input).textFieldStyle(.roundedBorder)
            }
            HStack {
                if prompt.packet.key != "confirm.migration" {
                    Button(native("Stop operation"), role: .cancel) { model.cancel() }.keyboardShortcut(.cancelAction)
                }
                Spacer()
                if prompt.packet.kind == "boolean" {
                    Button(native(prompt.packet.key == "confirm.migration" ? "Cancel migration" : "No")) { model.answer("n") }.keyboardShortcut(.defaultAction)
                    Button(native(prompt.packet.key == "confirm.migration" ? "Migrate now" : "Yes, continue")) { model.answer("y") }
                } else if prompt.packet.kind != "choice" {
                    Button(native("Continue")) { model.answer(input) }
                        .disabled(prompt.packet.kind == "text" && !(prompt.packet.requiredText ?? "").isEmpty && input != prompt.packet.requiredText)
                        .keyboardShortcut(.defaultAction)
                }
            }
        }.padding(24).frame(width: 560).interactiveDismissDisabled()
            .onExitCommand { if prompt.packet.kind == "boolean" { model.answer("n") } else { model.cancel() } }
    }
}
struct ReviewView: View {
    @ObservedObject var model: AppModel
    let workflow: Workflow
    @State private var compatible = false
    @State private var identity = "preserve"
    @State private var cloneConfirmed = false
    var simplified: Bool { workflow.readers != nil && ["migration", "reuse"].contains(workflow.action) && !workflow.dryRun }
    var requiresCompatibility: Bool { ["full", "koreader"].contains(workflow.mode) }
    var ready: Bool { !simplified || ((!requiresCompatibility || compatible) && (identity != "clone" || cloneConfirmed)) }
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Label(native(workflow.dryRun ? "Review preview" : workflow.action == "delete" ? "Review batch deletion" : "Review operation"), systemImage: workflow.dryRun ? "magnifyingglass" : "exclamationmark.shield").font(.title2)
            Text(native(workflow.action == "delete" ? "Only the selected eligible batch can be deleted. The core will recheck protection and require exact typed confirmation." :
                 workflow.action == "restore" ? "Restore returns the recorded TARGET state and can remove listed added files. Verified undo backups are retained." :
                 workflow.mode == "audit" ? "Inspect and report without changing reader files or creating backup ZIPs." :
                 workflow.mode == "koreader" ? "Replace only the entire target KOReader directory after verified backups. External books and fonts are excluded." :
                 workflow.mode == "full" ? "Replace the entire target KOReader directory and copy supported books, reading data and root fonts. Matching paths can be overwritten; unrelated external target books are retained." :
                 "Copy only the selected library content under the chosen conflict policy. Target KOReader stays installed."))
                .fixedSize(horizontal: false, vertical: true)
            LabeledContent(native("Mode"), value: workflow.mode.uppercased())
            LabeledContent(native("Action"), value: native(workflow.dryRun ? "Read-only device preview" : workflow.action.capitalized))
            if let roles = workflow.readers {
                if let source = roles["source"] { LabeledContent(native("Source"), value: model.reviewLabel(source)) }
                if let target = roles["target"] { LabeledContent(native("Target"), value: model.reviewLabel(target)) }
            }
            if let id = workflow.runID { LabeledContent(native("Batch"), value: id) }
            if model.sample != nil { Label(native("Synthetic sample readers only"), systemImage: "testtube.2").foregroundStyle(.teal) }
            if simplified {
                Text(native("Confirm these source and target roles. The app will prepare backups automatically, then ask once before writing. Unusual model or identity problems still require attention."))
                    .font(.callout).fixedSize(horizontal: false, vertical: true)
                if requiresCompatibility {
                    Toggle(native("I confirm the source KOReader build can run on the target reader."), isOn: $compatible)
                    DisclosureGroup(native("KOReader identity options")) {
                        Picker(native("Target identity"), selection: $identity) {
                            Text(native("Keep target identity; create one if missing")).tag("preserve")
                            Text(native("Generate a new identity")).tag("new")
                            Text(native("Clone source identity")).tag("clone")
                        }
                        if identity == "clone" { Toggle(native("I understand both readers will share the source KOReader identity."), isOn: $cloneConfirmed) }
                    }
                }
            }
            Text(native(workflow.readers != nil ? "These choices apply only to this operation and the selected USB connections. Keep the target connected until safe eject. Device, space, archive and recovery checks remain active." : "Keep readers disconnected until requested. Connect one at a time and confirm the physical roles and source-build compatibility. A full dry-run may create private local reports, but does not change readers or create backup ZIPs."))
                .font(.callout).foregroundStyle(.secondary)
            HStack {
                Button(native("Not now"), role: .cancel) { model.pendingWorkflow = nil }.keyboardShortcut(.defaultAction)
                Spacer()
                Button(native(workflow.dryRun ? "Start preview" : simplified ? "Back up and prepare" : "Continue to core confirmations")) {
                    var value = workflow
                    if simplified { value.review = MigrationReview(rolesConfirmed: true, compatible: compatible, identity: identity, cloneConfirmed: cloneConfirmed) }
                    Task { await model.execute(value) }
                }.disabled(!ready)
            }
        }.padding(24).frame(width: 560)
            .onExitCommand { model.pendingWorkflow = nil }
    }
}
struct ReaderCorrectionView: View {
    @ObservedObject var model: AppModel
    let correction: ReaderCorrection
    @State private var choice = ""
    @State private var custom = ""
    var value: String {
        let text = (choice == "__custom" ? custom : choice).trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty || text.lowercased().hasPrefix("kobo ") ? text : "Kobo " + text
    }
    var valid: Bool { value.count <= 80 && value.range(of: "^Kobo [A-Za-z0-9][A-Za-z0-9 ._()+-]*$", options: .regularExpression) != nil }
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Label(native("Confirm the physical reader model"), systemImage: "exclamationmark.triangle").font(.title2)
            Text(native("Check the {role} reader itself before confirming. A wrong model label can hide a compatibility problem.", ["role": native(correction.role)]))
                .fixedSize(horizontal: false, vertical: true)
            if let row = model.reader(correction.role) {
                LabeledContent(native("Volume"), value: row.volume)
                LabeledContent(native("Native identification"), value: row.nativeModel ?? native("Unknown"))
                LabeledContent(native("USB model"), value: row.usbModel ?? native("Not uniquely identified"))
                if !row.warning.isEmpty { Text(row.warningText).font(.callout).fixedSize(horizontal: false, vertical: true) }
            }
            Picker(native("Correct model"), selection: $choice) {
                Text(native("Choose a model")).tag("")
                ForEach(model.modelOptions, id: \.self) { Text($0).tag($0) }
                Text(native("Other Kobo model…")).tag("__custom")
            }
            if choice == "__custom" { TextField(native("Model name"), text: $custom, prompt: Text(native("Kobo model name"))).textFieldStyle(.roundedBorder) }
            Text(native("This correction applies only to this reader selection. It does not change Kobo files or bypass USB identity, backups or write-time checks."))
                .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            HStack {
                Button(native("Cancel"), role: .cancel) { model.readerCorrection = nil }.keyboardShortcut(.cancelAction)
                Spacer()
                Button(native("Confirm physical model")) { model.confirmModel(correction, model: value) }.disabled(!valid)
            }
        }.padding(24).frame(width: 560).interactiveDismissDisabled()
            .onAppear { choice = model.chosenModel(correction.role) }
    }
}
struct ReaderRoleView: View {
    @ObservedObject var model: AppModel
    let role: String
    var title: String { role == "source" ? "Source reader" : "Target reader" }
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Picker(native(title), selection: Binding(get: { model.readerID(role) }, set: { model.selectReader($0, role: role) })) {
                    Text(native("Choose {role} reader", ["role": native(role)])).tag("")
                    if !model.readerID(role).isEmpty && model.reader(role) == nil {
                        Text(native("Disconnected — select again")).tag(model.readerID(role)).disabled(true)
                    }
                    ForEach(model.readers) { row in
                        Text(row.label).tag(row.id)
                            .disabled(!row.selectable || row.id == model.readerID(role == "source" ? "target" : "source"))
                    }
                }
                Button(native("Correct model…")) { model.correctModel(role) }.disabled(model.reader(role)?.selectable != true)
            }
            if let row = model.reader(role) {
                Text(native("Selected model: {model}", ["model": model.chosenModel(role).isEmpty ? native("Confirmation needed") : model.chosenModel(role)]))
                    .font(.callout).textSelection(.enabled)
                Label(native("{identity} · {bytes} available", ["identity": native(row.usbVerified ? "USB identity verified" : "USB identity not verified"), "bytes": formattedBytes(row.freeBytes)]),
                      systemImage: row.usbVerified ? "checkmark.shield" : "exclamationmark.triangle")
                    .font(.callout).foregroundStyle(.secondary)
                if !row.warning.isEmpty { Text(row.warningText).font(.callout).fixedSize(horizontal: false, vertical: true) }
            }
        }
    }
}
extension Workflow: Identifiable { var id: String { action + mode + String(dryRun) + (runID ?? "") } }

// Shared widths keep content centered while preserving native form/table behavior.
enum PageLayout {
    static let contentWidth: CGFloat = 1000
    static let inset: CGFloat = 24
}
struct PageColumn<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        content
            .frame(maxWidth: PageLayout.contentWidth)
            .padding(.horizontal, PageLayout.inset)
            .frame(maxWidth: .infinity)
    }
}
struct MigrationView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        VStack(spacing: 0) {
            Form {
                Section(native("Migration scope")) {
                    Picker(native("Mode"), selection: $model.config.mode) {
                        Text(native("KOReader directory only")).tag("koreader")
                        Text(native("Full setup and library")).tag("full")
                        Text(native("Library content only")).tag("library")
                        Text(native("Audit only")).tag("audit")
                    }
                    Text(native(model.config.mode == "koreader" ? "Settings, plugins and reading data inside KOReader. External books and fonts are untouched." :
                         model.config.mode == "full" ? "Complete KOReader plus supported ebooks, reading data and root fonts. Target-only external books are retained." :
                         model.config.mode == "library" ? "Keep the installed target runtime and choose which library content to copy." : "Inspect and report without changing reader files."))
                        .font(.callout).foregroundStyle(.secondary)
                }
                Section(native("Reader roles")) {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Label(native(model.readerProblem ?? model.connected?.message ?? "Checking connected readers…"), systemImage: "externaldrive")
                                .font(.callout).lineLimit(3)
                            Spacer()
                            if model.checkingReaders { ProgressView().controlSize(.small) }
                            Button(native("Refresh readers")) { Task { await model.refreshConnected() } }
                                .disabled(model.checkingReaders)
                        }
                    }
                    Toggle(native("Choose from connected readers"), isOn: $model.useConnectedReaders)
                    if model.useConnectedReaders {
                        ForEach(model.readers.filter { !$0.selectable }) { row in
                            Label(row.volume + ": " + row.warningText, systemImage: "exclamationmark.triangle")
                                .font(.callout).fixedSize(horizontal: false, vertical: true)
                        }
                        ReaderRoleView(model: model, role: "source")
                        ReaderRoleView(model: model, role: "target")
                        Text(native("Both readers may stay connected. Choose each role explicitly. Use Correct model if automatic identification is wrong; confirm the physical model in the warning window."))
                            .font(.callout).foregroundStyle(.secondary)
                    } else {
                        TextField(native("Source model"), text: $model.config.sourceModel, prompt: Text(native("Optional model name")))
                        TextField(native("Target model"), text: $model.config.targetModel, prompt: Text(native("Optional model name")))
                        Text(native("Sequential mode: connect only the requested reader, one at a time. Physical-model confirmations remain required."))
                            .font(.callout).foregroundStyle(.secondary)
                    }
                }
                if model.config.mode == "library" {
                    Section(native("Library options")) {
                        Toggle(native("Books and adjacent reading data"), isOn: $model.config.books)
                        Toggle(native("Root fonts"), isOn: $model.config.fonts)
                        Toggle(native("Include reading data"), isOn: $model.config.readingData)
                        Picker(native("Matching paths"), selection: $model.config.conflict) {
                            Text(native("Overwrite from source")).tag("overwrite"); Text(native("Keep target file and metadata")).tag("keep-target")
                        }
                        TextField(native("Include directories (one per line)"), text: $model.config.includePaths, axis: .vertical)
                        TextField(native("Exclude directories (one per line)"), text: $model.config.excludePaths, axis: .vertical)
                        TextField(native("Additional extensions (one per line)"), text: $model.config.extensions, axis: .vertical)
                    }
                }
                Section(native("Output")) {
                    LabeledContent(native("Private backup folder")) { Text(native(model.sample == nil ? model.workspace : "Sample Readers / Workspace")).lineLimit(2).textSelection(.enabled).foregroundStyle(.secondary) }
                    Text(native("Backups may include plugin credentials and reading history. They stay in this folder; the app has no upload or telemetry action.")).font(.callout).foregroundStyle(.secondary)
                }
            }.formStyle(.grouped).disabled(model.busy)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            PageColumn {
                HStack {
                Button(native("Save choices")) { model.save() }.disabled(model.busy || !model.preferencesWritable)
                Spacer()
                Button(native("Preview changes")) { model.review(model.config.workflow(dryRun: true)) }.disabled(model.busy).keyboardShortcut("p", modifiers: [.command, .shift])
                Button(native(model.config.mode == "audit" ? "Start audit" : "Start migration")) { model.review(model.config.workflow(dryRun: model.config.mode == "audit")) }
                    .buttonStyle(.borderedProminent).disabled(model.busy)
                }.padding(.vertical, 16)
            }
            ActivityView(model: model)
        }.frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
struct ActivityView: View {
    @ObservedObject var model: AppModel
    @State private var showDetails = false
    var body: some View {
        VStack(spacing: 0) {
            Divider()
            PageColumn {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        if model.busy { ProgressView().controlSize(.small) }
                        Text(native(model.busy ? "Operation in progress" : "Activity")).font(.headline)
                        Spacer()
                        if model.busy { Button(native("Request safe stop"), role: .destructive) { model.cancel() } }
                    }
                    if model.logs.isEmpty {
                        Text(native("Preview the plan before writing. Progress and core confirmations appear here."))
                            .foregroundStyle(.secondary).font(.callout)
                    } else {
                        Text(native(model.phase)).font(.callout).lineLimit(2).textSelection(.enabled)
                        DisclosureGroup(native("Show activity details"), isExpanded: $showDetails) {
                            ScrollView {
                                Text(model.logs.suffix(100).joined(separator: "\n")).font(.system(.caption, design: .monospaced))
                                    .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                            }.frame(height: 105)
                        }
                    }
                }.frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 16)
            }
        }.frame(maxWidth: .infinity).background(Color(nsColor: .controlBackgroundColor))
    }
}
struct BackupsView: View {
    @ObservedObject var model: AppModel
    var cleanup = false
    var body: some View {
        VStack(spacing: 0) {
            PageColumn {
                if model.runs.isEmpty {
                    ContentUnavailableView(native(cleanup ? "No batches to review" : "Your backups will appear here"), systemImage: "archivebox",
                        description: Text(native("Complete a migration or choose an existing CLI backup folder in Settings. Sample readers let you explore safely.")))
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    VStack(alignment: .leading, spacing: 16) {
                        if cleanup {
                            VStack(alignment: .leading, spacing: 8) {
                                HStack {
                                    Text(native("Eligible to reclaim")).font(.headline)
                                    Spacer()
                                    Text(formattedBytes(model.reclaimable)).monospacedDigit()
                                }
                                Text(native("Recent successes, dependencies, recovery points and uncertain batches stay protected. Select an eligible batch; deletion still requires core confirmation."))
                                    .font(.callout).foregroundStyle(.secondary)
                            }
                        }
                        GeometryReader { area in
                            let usable = max(450, area.size.width - 100)
                            Table(model.runs, selection: $model.selectedRun) {
                                TableColumn(native("Batch")) { row in Text(row.id).lineLimit(1).truncationMode(.middle).help(row.id) }.width(usable * 0.29)
                                TableColumn(native("Status")) { row in
                                    Label(native(row.status), systemImage: row.status == "success" ? "checkmark.circle" : row.status == "needs-recovery" ? "exclamationmark.triangle" : "doc.text")
                                        .foregroundStyle(row.status == "needs-recovery" ? Color.orange : Color.primary)
                                        .lineLimit(1).help(native(row.status))
                                }.width(usable * 0.17)
                                TableColumn(native("Operation")) { row in Text(row.operationText).lineLimit(1).help(row.operationText) }.width(usable * 0.16)
                                TableColumn(native("Size")) { row in Text(formattedBytes(row.bytes)).monospacedDigit() }.width(usable * 0.11)
                                TableColumn(native("Retention")) { row in Text(native(row.eligible ? native("Eligible") : row.protectionText)).lineLimit(2).help(row.protectionText) }.width(usable * 0.27)
                            }
                            .frame(width: area.size.width, height: area.size.height)
                            .clipped()
                            .id(cleanup)
                        }
                        .frame(minHeight: 140)
                        .onChange(of: model.selectedRun) { _, _ in Task { await model.details() } }
                        if let row = model.currentRun {
                            VStack(alignment: .leading, spacing: 12) {
                                HStack {
                                    Text(row.id).font(.headline).lineLimit(1).truncationMode(.middle).textSelection(.enabled).help(row.id)
                                    Spacer()
                                    Button(native("Show in Finder")) { model.revealSelected() }
                                }
                                if !model.summary.isEmpty {
                                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 110), alignment: .leading)], alignment: .leading, spacing: 12) {
                                        ForEach(model.summary.keys.sorted(), id: \.self) { key in
                                            VStack(alignment: .leading, spacing: 4) {
                                                Text(native(key.replacingOccurrences(of: "_", with: " ").capitalized)).foregroundStyle(.secondary)
                                                Text(native("{count} files", ["count": String(Int(model.summary[key]?.object["count"]?.number ?? 0))])).monospacedDigit()
                                            }.font(.callout)
                                        }
                                    }
                                }
                                if cleanup {
                                    HStack(alignment: .top) {
                                        Text(native(row.eligible ? native("This batch is eligible. Review it before deleting.") : row.protectionText))
                                            .font(.callout).foregroundStyle(.secondary).lineLimit(3).help(row.protectionText)
                                        Spacer()
                                        Button(native("Delete selected batch…"), role: .destructive) { model.review(model.config.workflow(action: "delete", dryRun: false, runID: row.id)) }
                                            .disabled(!row.eligible || model.busy)
                                    }
                                } else {
                                    ViewThatFits(in: .horizontal) {
                                        HStack(spacing: 20) { sourceActions(row); restoreActions(row) }
                                        VStack(alignment: .leading, spacing: 12) { sourceActions(row); restoreActions(row) }
                                    }
                                    if !row.canReuse && !row.canRestore {
                                        Text(native("This batch has no reusable source or exact target snapshot. Its recovery files are retained."))
                                            .font(.callout).foregroundStyle(.secondary)
                                    }
                                }
                            }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
                                .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 8))
                        } else {
                            Text(native(cleanup ? "Select a batch to review its protection and deletion options." : "Select a batch to inspect its snapshots and available actions."))
                                .font(.callout).foregroundStyle(.secondary).padding(.vertical, 8)
                        }
                    }.padding(.vertical, PageLayout.inset)
                }
            }.frame(maxWidth: .infinity, maxHeight: .infinity)
            ActivityView(model: model)
        }.frame(maxWidth: .infinity, maxHeight: .infinity)
    }
    private func sourceActions(_ row: RunEntry) -> some View {
        HStack {
            Button(native("Preview saved source")) { model.review(model.config.workflow(action: "reuse", dryRun: true, runID: row.id)) }
            Button(native("Migrate saved source…")) { model.review(model.config.workflow(action: "reuse", dryRun: false, runID: row.id)) }
        }.disabled(!row.canReuse || model.busy)
    }
    private func restoreActions(_ row: RunEntry) -> some View {
        HStack {
            Button(native("Preview target restore")) { model.review(model.config.workflow(action: "restore", dryRun: true, runID: row.id)) }
            Button(native("Restore target…")) { model.review(model.config.workflow(action: "restore", dryRun: false, runID: row.id)) }
        }.disabled(!row.canRestore || model.busy)
    }
}
struct SettingsView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        Form {
            Section(native("Private storage")) {
                LabeledContent(native("Backup folder")) { Text(model.config.outputRoot).textSelection(.enabled).lineLimit(3) }
                Button(native("Choose folder…")) { model.chooseFolder() }
                Text(native("Choose an existing CLI output folder to reopen its batches. Existing archives and unknown metadata are preserved.")).font(.callout).foregroundStyle(.secondary)
            }
            Section(native("Workflow")) {
                Picker(native("Language"), selection: $model.config.locale) {
                    Text(native("English")).tag("en"); Text(native("繁體中文")).tag("zh-Hant"); Text(native("简体中文")).tag("zh-Hans")
                }
                Stepper(native("Protect at least {count} recent successful batches", ["count": String(model.config.keepSuccessful)]), value: $model.config.keepSuccessful, in: 1...100)
                Text(native("The interface and new operations use this language immediately. Existing activity keeps its original language. Recovery protections always apply.")).font(.callout).foregroundStyle(.secondary)
            }
            Section(native("Application")) {
                LabeledContent(native("Core"), value: model.health?.coreVersion ?? native("Checking…"))
                LabeledContent(native("Bundled Python"), value: model.health?.pythonVersion ?? native("Checking…"))
                Text(native("Offline operation. No shell Python, AI service or account required. Local builds are ad-hoc signed and are not notarized.")).font(.callout).foregroundStyle(.secondary)
                Button(native("Save preferences")) { model.save() }.disabled(!model.preferencesWritable)
                Button(native("Open usage guide")) { if let url = Bundle.main.resourceURL?.appendingPathComponent("backend/docs/MACOS.md") { NSWorkspace.shared.open(url) } }
            }
        }.formStyle(.grouped).disabled(model.busy)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
struct MainView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        NavigationSplitView {
            List(AppSection.allCases, selection: Binding<AppSection?>(get: { model.section }, set: { if let value = $0 { model.section = value } })) { item in Label(native(item.rawValue), systemImage: item.symbol).tag(item) }
                .navigationTitle("KOReader Bridge")
                .safeAreaInset(edge: .bottom) {
                    VStack(alignment: .leading, spacing: 8) {
                        Label(native(model.sample == nil ? "Private, offline workspace" : "Sample readers"), systemImage: model.sample == nil ? "lock.shield" : "testtube.2")
                            .font(.caption).foregroundStyle(.secondary)
                        if model.sample != nil { Button(native("Leave sample session")) { model.leaveSample() }.disabled(model.busy) }
                        else { Button(native("Try sample readers")) { Task { await model.createSample() } }.disabled(model.busy) }
                    }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
                }.navigationSplitViewColumnWidth(min: 190, ideal: 210, max: 250)
        } detail: {
            VStack(spacing: 0) {
                if model.sample != nil { HStack { Label(native("Sample data — no physical readers are used"), systemImage: "testtube.2"); Spacer() }.font(.callout).padding(12).background(.teal.opacity(0.12)) }
                if let problem = model.problem {
                    HStack(alignment: .top) { Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange); Text(native(problem)).textSelection(.enabled); Spacer(); Button(native("Dismiss")) { model.problem = nil } }.padding(12).background(.orange.opacity(0.1))
                } else if !model.notice.isEmpty {
                    HStack { Image(systemName: "checkmark.circle").foregroundStyle(.teal); Text(native(model.notice)); Spacer() }.font(.callout).padding(12)
                }
                switch model.section {
                case .migration: MigrationView(model: model)
                case .backups: BackupsView(model: model)
                case .cleanup: BackupsView(model: model, cleanup: true)
                case .settings: SettingsView(model: model)
                }
            }.frame(maxWidth: .infinity, maxHeight: .infinity)
                .navigationTitle(native(model.section.rawValue))
                .toolbar {
                    ToolbarItem { Button { Task { await model.refresh() } } label: { Label(native("Refresh batches"), systemImage: "arrow.clockwise") }.disabled(model.busy).keyboardShortcut("r", modifiers: .command) }
                }
        }.tint(.teal).frame(minWidth: 940, minHeight: 680)
            .environment(\.locale, Locale(identifier: model.config.locale))
            .onChange(of: model.config.locale) { _, _ in model.save() }
            .sheet(item: $model.prompt) { PromptView(model: model, prompt: $0) }
            .sheet(item: $model.pendingWorkflow) { ReviewView(model: model, workflow: $0) }
            .sheet(item: $model.readerCorrection) { ReaderCorrectionView(model: model, correction: $0) }
            .background(WindowLink(model: model))
            .onReceive(NSWorkspace.shared.notificationCenter.publisher(for: NSWorkspace.didMountNotification)) { _ in Task { await model.refreshConnected() } }
            .onReceive(NSWorkspace.shared.notificationCenter.publisher(for: NSWorkspace.didUnmountNotification)) { _ in Task { await model.refreshConnected() } }
            .task {
                while !Task.isCancelled {
                    await model.refreshConnected()
                    do { try await Task.sleep(nanoseconds: 3_000_000_000) } catch { break }
                }
            }
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
                CommandGroup(replacing: .saveItem) { Button(native("Save choices")) { model.save() }.keyboardShortcut("s", modifiers: .command).disabled(model.busy || !model.preferencesWritable) }
                CommandGroup(after: .appInfo) { Button(native("KOReader Bridge Settings")) { model.section = .settings }.keyboardShortcut(",", modifiers: .command) }
            }
    }
}
