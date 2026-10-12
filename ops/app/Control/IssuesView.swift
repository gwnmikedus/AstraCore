import SwiftUI

struct IssuesView: View {
    @EnvironmentObject var github: GitHubStore
    @EnvironmentObject var runner: Runner
    enum Filter: String, CaseIterable, Identifiable { case open = "Open", attention = "Needs labels", closed = "Closed", all = "All"; var id: String { rawValue } }
    @State private var filter: Filter = .open
    @State private var selected: Int?

    private var shown: [Issue] {
        let list: [Issue]
        switch filter {
        case .open: list = github.issues.filter(\.isOpen)
        case .attention: list = github.issues.filter { !$0.labelProblems.isEmpty }
        case .closed: list = github.issues.filter { !$0.isOpen }
        case .all: list = github.issues
        }
        return list.sorted { $0.number > $1.number }
    }

    var body: some View {
        HSplitView {
            VStack(spacing: 0) {
                Picker("Show", selection: $filter) {
                    ForEach(Filter.allCases) { f in Text(f.rawValue).tag(f) }
                }
                .pickerStyle(.segmented).labelsHidden().padding(10)
                List(selection: $selected) {
                    if shown.isEmpty {
                        Text(filter == .attention ? "Every issue follows the label scheme." : "No issues here.").foregroundStyle(.secondary)
                    }
                    ForEach(shown) { issue in IssueRow(issue: issue).tag(issue.number) }
                }
            }
            .frame(minWidth: 280, idealWidth: 340)
            Group {
                if let issue = github.issues.first(where: { $0.number == selected }) {
                    IssueDetail(issue: issue)
                } else {
                    VStack(spacing: 8) {
                        Image(systemName: "exclamationmark.bubble").font(.largeTitle).foregroundStyle(.secondary)
                        Text("Select an issue").foregroundStyle(.secondary)
                        if let e = github.error { Text(e).font(.callout).foregroundStyle(Brand.bad).padding() }
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
            .frame(minWidth: 380, maxWidth: .infinity, maxHeight: .infinity)
        }
        .navigationTitle("Issues")
        .onAppear { if selected == nil { selected = shown.first?.number } }
        .toolbar {
            ToolbarItem {
                Button {
                    openURL((github.issues.first?.url).map { String($0[..<($0.range(of: "/issues/")?.upperBound ?? $0.endIndex)]) + "new/choose" })
                } label: { Label("New issue", systemImage: "plus") }
                .help("Open GitHub's new-issue forms")
            }
        }
    }
}

struct IssueRow: View {
    let issue: Issue
    var body: some View {
        let (status, color) = issue.status
        VStack(alignment: .leading, spacing: 3) {
            Text("#\(issue.number) \(issue.title)").lineLimit(2)
            HStack(spacing: 6) {
                Pill(text: status, color: color)
                if let t = issue.type { Pill(text: t, color: t == "Bug" ? Brand.bad : .blue) }
                if !issue.labelProblems.isEmpty {
                    Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(Brand.warn).help(issue.labelProblems.joined(separator: "\n"))
                }
            }
        }
        .padding(.vertical, 3)
    }
}

struct IssueDetail: View {
    @EnvironmentObject var github: GitHubStore
    @EnvironmentObject var runner: Runner
    let issue: Issue

    var body: some View {
        let (status, color) = issue.status
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .firstTextBaseline) {
                    Text(issue.title).font(.title2.weight(.semibold)).textSelection(.enabled)
                    Spacer()
                    Button { openURL(issue.url) } label: { Label("GitHub", systemImage: "arrow.up.right.square") }
                }
                HStack(spacing: 8) {
                    Pill(text: "#\(issue.number)")
                    Pill(text: status, color: color)
                    Text("Shown on the Community page as “\(status)”.").font(.callout).foregroundStyle(.secondary)
                }
                if !issue.labelProblems.isEmpty {
                    Card(title: "Doesn't follow the label scheme", systemImage: "exclamationmark.triangle") {
                        ForEach(issue.labelProblems, id: \.self) { Text("• " + $0) }
                        Button("Fix labels") { github.fixLabels(issue, runner) }.disabled(runner.busy)
                    }
                }
                Card(title: "Labels", systemImage: "tag") {
                    Text(issue.labels.map(\.name).sorted().joined(separator: "  ·  ")).font(.callout.monospaced())
                    HStack {
                        Text("Type").frame(width: 60, alignment: .leading).foregroundStyle(.secondary)
                        Button("Bug") { github.setType(issue, Labels.bug, runner) }
                            .disabled(issue.names.contains(Labels.bug) && !issue.names.contains("bug"))
                        Button("Idea") { github.setType(issue, Labels.idea, runner) }
                            .disabled(issue.names.contains(Labels.idea) && !issue.names.contains("enhancement"))
                    }
                    if issue.isOpen {
                        HStack {
                            Text("Status").frame(width: 60, alignment: .leading).foregroundStyle(.secondary)
                            ForEach([(Labels.underReview, "Under review"), (Labels.planned, "Planned"), (Labels.inProgress, "In progress")], id: \.0) { label, name in
                                Button(name) { github.setStatus(issue, label, runner) }
                                    .disabled(issue.names.intersection(Labels.openStatuses) == [label])
                            }
                        }
                    }
                }
                .disabled(runner.busy)
                Card(title: issue.isOpen ? "Close" : "Closed", systemImage: issue.isOpen ? "checkmark.circle" : "archivebox") {
                    if issue.isOpen {
                        Text("A pull request with “Closes #\(issue.number)” closes it when merged. Close it here when it's done some other way or won't be done.")
                            .font(.callout).foregroundStyle(.secondary)
                        HStack {
                            Button("Close as completed") { github.close(issue, completed: true, runner) }
                            Button("Close as not planned") {
                                runner.ask("Close #\(issue.number) as not planned?", "It shows as Closed on the Community page. You can reopen it later.", button: "Close as not planned") {
                                    github.close(issue, completed: false, runner)
                                }
                            }
                        }
                    } else {
                        Text("Closed as \(issue.stateReason == "COMPLETED" ? "completed" : "not planned")\(issue.names.contains(Labels.released) ? " and released" : ""). `status:released` is added by the Release page when a minor release ships it.")
                            .font(.callout).foregroundStyle(.secondary)
                        Button("Reopen") { github.reopen(issue, runner) }
                    }
                }
                .disabled(runner.busy)
            }
            .padding(20)
        }
    }
}
