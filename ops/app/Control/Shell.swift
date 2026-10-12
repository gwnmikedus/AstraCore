import Foundation

/// Where things are. The app normally sits in the repo root; otherwise it uses the path it was built from.
enum Paths {
    static let repo: String = {
        let env = ProcessInfo.processInfo.environment
        if let override = env["ASTRACORE_CONTROL_REPO"], !override.isEmpty { return override }
        let appDir = Bundle.main.bundleURL.deletingLastPathComponent().path
        if FileManager.default.isExecutableFile(atPath: appDir + "/astracore") { return appDir }
        if let built = Bundle.main.object(forInfoDictionaryKey: "AstraCoreRepo") as? String, !built.isEmpty { return built }
        return NSHomeDirectory() + "/Eve"
    }()
    static var data: String { repo + "/data" }
    static var python: String { repo + "/.venv/bin/python" }
}

struct CommandResult {
    let status: Int32
    let output: String
    var ok: Bool { status == 0 }
    var trimmed: String { output.trimmingCharacters(in: .whitespacesAndNewlines) }
}

private final class OutputBuffer: @unchecked Sendable {
    private var data = Data()
    private let lock = NSLock()
    func append(_ d: Data) { lock.lock(); data.append(d); lock.unlock() }
    var string: String { lock.lock(); defer { lock.unlock() }; return String(decoding: data, as: UTF8.self) }
}

/// Runs command-line tools the way a terminal would (a GUI app's PATH doesn't include ~/.local/bin or Homebrew).
enum Shell {
    static var environment: [String: String] {
        var env = ProcessInfo.processInfo.environment
        let home = NSHomeDirectory()
        env["PATH"] = "\(home)/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        env["GH_PROMPT_DISABLED"] = "1"
        env["GH_NO_UPDATE_NOTIFIER"] = "1"
        env["NO_COLOR"] = "1"
        env["CLICOLOR"] = "0"
        env["GIT_TERMINAL_PROMPT"] = "0"
        env.removeValue(forKey: "ASTRACORE_CONTROL_REPO")
        return env
    }

    /// `onOutput` gets chunks of combined stdout/stderr on the main queue while the command runs.
    static func run(_ tool: String, _ args: [String], cwd: String? = Paths.repo,
                    onOutput: (@Sendable (String) -> Void)? = nil) async -> CommandResult {
        await withCheckedContinuation { (cont: CheckedContinuation<CommandResult, Never>) in
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            p.arguments = [tool] + args
            if let cwd { p.currentDirectoryURL = URL(fileURLWithPath: cwd) }
            p.environment = environment
            let pipe = Pipe()
            p.standardOutput = pipe
            p.standardError = pipe
            p.standardInput = FileHandle.nullDevice
            let buf = OutputBuffer()
            let reader = pipe.fileHandleForReading
            reader.readabilityHandler = { h in
                let d = h.availableData
                guard !d.isEmpty else { return }
                buf.append(d)
                if let onOutput {
                    let s = String(decoding: d, as: UTF8.self)
                    DispatchQueue.main.async { onOutput(s) }
                }
            }
            p.terminationHandler = { proc in
                reader.readabilityHandler = nil
                if let rest = try? reader.readToEnd(), !rest.isEmpty {
                    buf.append(rest)
                    if let onOutput {
                        let s = String(decoding: rest, as: UTF8.self)
                        DispatchQueue.main.async { onOutput(s) }
                    }
                }
                cont.resume(returning: CommandResult(status: proc.terminationStatus, output: buf.string))
            }
            do {
                try p.run()
            } catch {
                reader.readabilityHandler = nil
                cont.resume(returning: CommandResult(status: 127, output: "Couldn't run \(tool): \(error.localizedDescription)"))
            }
        }
    }

    static func astracore(_ args: String...) async -> CommandResult {
        await run(Paths.repo + "/astracore", args)
    }

    static func git(_ args: String...) async -> CommandResult { await run("git", args) }
    static func gh(_ args: [String]) async -> CommandResult { await run("gh", args) }
}

extension String {
    /// "fix: something (#42)" -> 42
    var pullRequestNumber: Int? {
        guard let r = range(of: #"\(#(\d+)\)\s*$"#, options: .regularExpression) else { return nil }
        return Int(self[r].filter(\.isNumber))
    }
}
