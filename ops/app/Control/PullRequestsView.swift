import SwiftUI

struct PullRequestsView: View {
    @EnvironmentObject var github: GitHubStore
    @State private var selected: Int?

    var body: some View {
        HSplitView {
            List(selection: $selected) {
                if github.pulls.isEmpty {
                    Text(github.loading ? "Loading…" : "No open pull requests.").foregroundStyle(.secondary)
                }
                ForEach(github.pulls) { pr in
                    PRRow(pr: pr).tag(pr.number)
                }
            }
            .frame(minWidth: 260, idealWidth: 320)
            Group {
                if let pr = github.pulls.first(where: { $0.number == selected }) {
                    PRDetail(pr: pr)
                } else {
                    VStack(spacing: 8) {
                        Image(systemName: "arrow.triangle.pull").font(.largeTitle).foregroundStyle(.secondary)
                        Text("Select a pull request").foregroundStyle(.secondary)
                        if let e = github.error { Text(e).font(.callout).foregroundStyle(Brand.bad).padding() }
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
            .frame(minWidth: 400, maxWidth: .infinity, maxHeight: .infinity)
        }
        .navigationTitle("Pull requests")
        .onAppear { if selected == nil { selected = github.pulls.first?.number } }
    }
}

struct PRRow: View {
    let pr: PullRequest
    var body: some View {
        let (summary, color) = pr.mergeSummary
        VStack(alignment: .leading, spacing: 3) {
            Text("#\(pr.number) \(pr.title)").lineLimit(2)
            HStack(spacing: 6) {
                ChecksBadge(pr: pr)
                Text(summary).font(.caption).foregroundStyle(color)
                Spacer()
                Text(pr.author.login).font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 3)
    }
}

struct ChecksBadge: View {
    let pr: PullRequest
    var body: some View {
        let c = pr.checks
        if c.fail > 0 {
            Label("\(c.fail) failing", systemImage: "xmark.circle.fill").font(.caption).foregroundStyle(Brand.bad)
        } else if c.pending > 0 {
            Label("\(c.pending) running", systemImage: "clock.fill").font(.caption).foregroundStyle(Brand.warn)
        } else if c.pass > 0 {
            Label("\(c.pass) passed", systemImage: "checkmark.circle.fill").font(.caption).foregroundStyle(Brand.ok)
        } else {
            Label("no checks", systemImage: "questionmark.circle").font(.caption).foregroundStyle(.secondary)
        }
    }
}

struct PRDetail: View {
    @EnvironmentObject var github: GitHubStore
    @EnvironmentObject var ops: OpsStore
    @EnvironmentObject var runner: Runner
    let pr: PullRequest
    @State private var merging = false

    var body: some View {
        let (summary, color) = pr.mergeSummary
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .firstTextBaseline) {
                    Text(pr.title).font(.title2.weight(.semibold)).textSelection(.enabled)
                    Spacer()
                    Button { openURL(pr.url) } label: { Label("GitHub", systemImage: "arrow.up.right.square") }
                }
                HStack(spacing: 8) {
                    Pill(text: "#\(pr.number)")
                    Pill(text: summary, color: color)
                    Text("\(pr.author.login) · \(pr.headRefName)").font(.callout).foregroundStyle(.secondary)
                }
                Card(title: "Merge", systemImage: "arrow.triangle.merge") {
                    Text(mergeHelp).font(.callout).foregroundStyle(.secondary)
                    HStack {
                        Button { merging = true } label: { Label("Squash and merge…", systemImage: "arrow.triangle.merge") }
                            .buttonStyle(.borderedProminent)
                            .disabled(!pr.canMerge || runner.busy)
                        if pr.behind {
                            Button { github.updateBranch(pr, runner) } label: { Label("Update branch", systemImage: "arrow.triangle.2.circlepath") }
                                .disabled(runner.busy)
                        }
                    }
                }
                Card(title: "Checks", systemImage: "checklist") {
                    if pr.statusCheckRollup.isEmpty { Text("No checks reported yet.").foregroundStyle(.secondary) }
                    ForEach(pr.statusCheckRollup, id: \.self) { c in
                        HStack(spacing: 6) {
                            switch c.outcome {
                            case .pass: Image(systemName: "checkmark.circle.fill").foregroundStyle(Brand.ok)
                            case .fail: Image(systemName: "xmark.circle.fill").foregroundStyle(Brand.bad)
                            case .pending: Image(systemName: "clock.fill").foregroundStyle(Brand.warn)
                            case .skipped: Image(systemName: "minus.circle").foregroundStyle(.secondary)
                            }
                            Text(c.title)
                        }
                    }
                }
                if !pr.closingIssuesReferences.isEmpty || pr.releaseNote != nil {
                    Card(title: "Closes and release note", systemImage: "link") {
                        if !pr.closingIssuesReferences.isEmpty {
                            Text("Closes " + pr.closingIssuesReferences.map { "#\($0.number)" + ($0.title.map { " \($0)" } ?? "") }.joined(separator: ", "))
                        }
                        if let note = pr.releaseNote {
                            Text(Markdown.attributed(note)).foregroundStyle(.secondary).textSelection(.enabled)
                        } else {
                            Text("No pilot-facing release note.").foregroundStyle(.secondary)
                        }
                    }
                }
                Card(title: "Description", systemImage: "text.alignleft") {
                    Text(Markdown.attributed(pr.body.isEmpty ? "_No description._" : pr.body))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .padding(20)
        }
        .sheet(isPresented: $merging) { MergeSheet(pr: pr) }
    }

    private var mergeHelp: String {
        if pr.isDraft { return "This is a draft. Mark it ready on GitHub first." }
        switch pr.mergeStateStatus {
        case "CLEAN", "HAS_HOOKS": return "Checks passed and the branch is up to date. Squash-merging adds one commit to main; production changes only when you deploy."
        case "BEHIND": return "main moved on since this branch was made. Update the branch, wait for the checks, then merge."
        case "DIRTY": return "The branch conflicts with main. It has to be fixed in the branch (ask the agent or author)."
        case "BLOCKED": return "GitHub won't merge yet: required checks must pass and conversations must be resolved."
        default: return "GitHub is still working out whether this can be merged. Refresh in a moment."
        }
    }
}

struct MergeSheet: View {
    @EnvironmentObject var github: GitHubStore
    @EnvironmentObject var ops: OpsStore
    @EnvironmentObject var runner: Runner
    @Environment(\.dismiss) private var dismiss
    let pr: PullRequest
    @State private var title = ""
    @State private var deployAfter = true

    static let conventional = #"^(feat|fix|docs|chore|refactor|perf|test|build|ci|style|revert)(\([^)]+\))?!?: \S.*\(#\d+\)$"#
    private var valid: Bool { title.range(of: Self.conventional, options: .regularExpression) != nil }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Squash and merge #\(pr.number)").font(.title3.weight(.semibold))
            Text("The title becomes the commit on main and the patch changelog entry, so write it for a reader.")
                .foregroundStyle(.secondary)
            TextField("Commit title", text: $title).textFieldStyle(.roundedBorder).font(.body.monospaced())
            if !valid {
                Text("Use a Conventional Commit title ending in the PR number, e.g. fix: keep restocks within storage (#\(pr.number)).")
                    .font(.caption).foregroundStyle(Brand.bad)
            }
            Toggle("Deploy to production right after merging", isOn: $deployAfter)
            Text(deployAfter ? "You'll confirm the deploy next; it ships everything merged so far (\(ops.undeployed.count) other change\(ops.undeployed.count == 1 ? "" : "s") waiting)."
                             : "It stays on main until you deploy from the Production page.")
                .font(.caption).foregroundStyle(.secondary)
            HStack {
                Spacer()
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Merge") {
                    dismiss()
                    github.merge(pr, title: title, runner, ops: ops, deployAfter: deployAfter)
                }
                .keyboardShortcut(.defaultAction)
                .disabled(!valid)
            }
        }
        .padding(20)
        .frame(width: 560)
        .onAppear { title = pr.squashTitle }
    }
}
