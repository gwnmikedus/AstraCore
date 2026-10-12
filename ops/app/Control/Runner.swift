import SwiftUI

/// One command in a job. `outputFile` saves the command's output (e.g. generated release notes).
struct Step {
    var label: String
    var tool: String
    var args: [String]
    var cwd: String? = Paths.repo
    var outputFile: String? = nil

    static func astracore(_ label: String, _ args: String...) -> Step {
        Step(label: label, tool: Paths.repo + "/astracore", args: args)
    }
    static func gh(_ label: String, _ args: String...) -> Step { Step(label: label, tool: "gh", args: args) }
    static func git(_ label: String, _ args: String...) -> Step { Step(label: label, tool: "git", args: args) }
}

struct Confirmation: Identifiable {
    let id = UUID()
    var title: String
    var message: String
    var button: String
    var destructive = false
    var action: () -> Void
}

/// Runs jobs (a list of steps) one at a time and shows their output in a console sheet.
@MainActor
final class Runner: ObservableObject {
    struct Job: Identifiable {
        let id = UUID()
        let title: String
        var log = ""
        var running = true
        var ok: Bool? = nil
        var summary = ""
    }

    @Published var job: Job?
    @Published var confirmation: Confirmation?
    var busy: Bool { job?.running == true }

    func ask(_ title: String, _ message: String, button: String, destructive: Bool = false, action: @escaping () -> Void) {
        confirmation = Confirmation(title: title, message: message, button: button, destructive: destructive, action: action)
    }

    /// Runs `steps` in order and stops at the first failure; `cleanup` always runs. `done` gets the outcome.
    func run(_ title: String, _ steps: [Step], cleanup: [Step] = [], success: String = "Done.",
             done: ((Bool) async -> Void)? = nil) {
        guard !busy else { return }
        job = Job(title: title)
        Task {
            var ok = true
            for step in steps {
                if !(await execute(step)) { ok = false; break }
            }
            for step in cleanup { _ = await execute(step) }
            job?.running = false
            job?.ok = ok
            job?.summary = ok ? success : "Stopped: a step failed. Nothing after it was run."
            await done?(ok)
        }
    }

    private func append(_ s: String) { job?.log += s }

    private func execute(_ step: Step) async -> Bool {
        let shown = ([URL(fileURLWithPath: step.tool).lastPathComponent] + step.args.map(Self.quote)).joined(separator: " ")
        append("\n▸ \(step.label)\n$ \(shown)\n")
        var stream: (@Sendable (String) -> Void)? = nil
        if step.outputFile == nil {
            stream = { [weak self] chunk in
                MainActor.assumeIsolated { self?.append(chunk) }   // Shell delivers chunks on the main queue
            }
        }
        let result = await Shell.run(step.tool, step.args, cwd: step.cwd, onOutput: stream)
        if let file = step.outputFile {
            do {
                try result.output.write(toFile: file, atomically: true, encoding: .utf8)
                append("(saved \(result.output.count) characters to \(file))\n")
            } catch {
                append("Couldn't save \(file): \(error.localizedDescription)\n")
                return false
            }
        }
        if !result.ok { append("✗ exit code \(result.status)\n") }
        return result.ok
    }

    private static func quote(_ s: String) -> String {
        s.rangeOfCharacter(from: .whitespaces) == nil && !s.isEmpty ? s : "'\(s)'"
    }
}

struct JobSheet: View {
    @EnvironmentObject var runner: Runner
    let job: Runner.Job

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                if job.running {
                    ProgressView().controlSize(.small)
                } else {
                    Image(systemName: job.ok == true ? "checkmark.circle.fill" : "xmark.octagon.fill")
                        .foregroundStyle(job.ok == true ? Brand.ok : Brand.bad)
                }
                Text(job.title).font(.headline)
                Spacer()
            }
            ScrollViewReader { proxy in
                ScrollView {
                    Text(job.log.isEmpty ? "Starting…" : job.log)
                        .font(.system(.callout, design: .monospaced))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(10)
                    Color.clear.frame(height: 1).id("end")
                }
                .background(Color(nsColor: .textBackgroundColor))
                .clipShape(RoundedRectangle(cornerRadius: 6))
                .onChange(of: job.log) { _ in proxy.scrollTo("end", anchor: .bottom) }
            }
            HStack {
                Text(job.running ? "Working… keep this window open." : job.summary)
                    .foregroundStyle(job.ok == false ? Brand.bad : .secondary)
                Spacer()
                Button("Copy output") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(job.log, forType: .string)
                }
                Button("Close") { runner.job = nil }
                    .keyboardShortcut(.defaultAction)
                    .disabled(job.running)
            }
        }
        .padding(18)
        .frame(minWidth: 640, minHeight: 420)
        .interactiveDismissDisabled(job.running)
    }
}
