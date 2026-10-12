import SwiftUI

struct Author: Decodable, Hashable { let login: String }
struct LabelRef: Decodable, Hashable { let name: String }
struct IssueRef: Decodable, Hashable { let number: Int; let title: String? }

/// One entry of statusCheckRollup: a CheckRun (name/status/conclusion) or a StatusContext (context/state).
struct Check: Decodable, Hashable {
    let name: String?
    let context: String?
    let status: String?
    let conclusion: String?
    let state: String?

    var title: String { name ?? context ?? "check" }
    enum Outcome { case pass, fail, pending, skipped }
    var outcome: Outcome {
        let c = (conclusion ?? state ?? "").uppercased()
        if ["SUCCESS", "NEUTRAL"].contains(c) { return .pass }
        if c == "SKIPPED" { return .skipped }
        if ["FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"].contains(c) { return .fail }
        return .pending
    }
}

struct PullRequest: Decodable, Identifiable, Hashable {
    let number: Int
    let title: String
    let url: String
    let headRefName: String
    let isDraft: Bool
    let mergeable: String
    let mergeStateStatus: String
    let reviewDecision: String?
    let author: Author
    let body: String
    let statusCheckRollup: [Check]
    let closingIssuesReferences: [IssueRef]
    let updatedAt: String
    var id: Int { number }

    var checks: (pass: Int, fail: Int, pending: Int) {
        statusCheckRollup.reduce(into: (0, 0, 0)) { acc, c in
            switch c.outcome {
            case .pass, .skipped: acc.0 += 1
            case .fail: acc.1 += 1
            case .pending: acc.2 += 1
            }
        }
    }
    var canMerge: Bool { !isDraft && ["CLEAN", "HAS_HOOKS"].contains(mergeStateStatus) }
    var behind: Bool { mergeStateStatus == "BEHIND" }

    /// What GitHub's merge box would say, in plain words.
    var mergeSummary: (String, Color) {
        if isDraft { return ("Draft", .secondary) }
        switch mergeStateStatus {
        case "CLEAN", "HAS_HOOKS": return ("Ready to merge", Brand.ok)
        case "BEHIND": return ("Behind main: update the branch", Brand.warn)
        case "DIRTY": return ("Merge conflicts", Brand.bad)
        case "BLOCKED": return (checks.fail > 0 ? "Checks failing" : (checks.pending > 0 ? "Checks running" : "Blocked"), checks.fail > 0 ? Brand.bad : Brand.warn)
        case "UNSTABLE": return ("Checks failing", Brand.bad)
        default: return ("Checking…", .secondary)
        }
    }

    /// The "Note for the next release" section of the PR template ("None" counts as no note).
    var releaseNote: String? { Markdown.section("Note for the next release", in: body) }

    /// Squash commit title: Conventional Commit title plus the PR number.
    var squashTitle: String { title.pullRequestNumber == nil ? "\(title) (#\(number))" : title }
}

struct Issue: Decodable, Identifiable, Hashable {
    let number: Int
    let title: String
    let state: String
    let stateReason: String?
    let labels: [LabelRef]
    let url: String
    let updatedAt: String
    let closedAt: String?
    var id: Int { number }

    var names: Set<String> { Set(labels.map(\.name)) }
    var isOpen: Bool { state == "OPEN" }

    /// Same order as issue_status() in src/astracore/core/community.py.
    var status: (String, Color) {
        if names.contains(Labels.released) { return ("Released", Brand.ok) }
        if !isOpen { return stateReason == "COMPLETED" ? ("Completed", Brand.ok) : ("Closed", .secondary) }
        if names.contains(Labels.inProgress) { return ("In progress", Brand.signal) }
        if names.contains(Labels.planned) || names.contains("roadmap") { return ("Planned", .blue) }
        return ("Under review", .secondary)
    }
    var type: String? { names.contains(Labels.bug) ? "Bug" : (names.contains(Labels.idea) ? "Idea" : nil) }

    /// Ways this issue breaks docs/releases.md#issue-labels.
    var labelProblems: [String] {
        var out: [String] = []
        if type == nil { out.append("no type: label") }
        if names.contains("bug") || names.contains("enhancement") { out.append("uses GitHub's default bug/enhancement") }
        let open = names.intersection(Labels.openStatuses)
        if isOpen && open.isEmpty { out.append("open without a status label") }
        if isOpen && open.count > 1 { out.append("more than one status label") }
        if !isOpen && !open.isEmpty { out.append("closed but still has \(open.sorted().joined(separator: ", "))") }
        if isOpen && names.contains(Labels.released) { out.append("open but marked released") }
        return out
    }
}

enum Labels {
    static let bug = "type:bug", idea = "type:idea"
    static let underReview = "status:under-review", planned = "status:planned", inProgress = "status:in-progress"
    static let released = "status:released"
    static let openStatuses: Set<String> = [underReview, planned, inProgress]
}

enum Markdown {
    static func section(_ heading: String, in body: String) -> String? {
        let lines = body.components(separatedBy: .newlines)
        guard let start = lines.firstIndex(where: { $0.trimmingCharacters(in: .whitespaces).hasPrefix("## ") && $0.contains(heading) }) else { return nil }
        let rest = lines[(start + 1)...].prefix { !$0.hasPrefix("## ") }
        let text = rest.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
        // "None" (also "None. This only changes deploys.") means the PR has no pilot-facing note
        let first = text.lowercased().prefix { $0.isLetter }
        if text.isEmpty || first == "none" { return nil }
        return text
    }

    static func attributed(_ s: String) -> AttributedString {
        (try? AttributedString(markdown: s, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(s)
    }
}

@MainActor
final class GitHubStore: ObservableObject {
    @Published var pulls: [PullRequest] = []
    @Published var issues: [Issue] = []
    @Published var error: String?
    @Published var loading = false
    @Published var account: String?

    static let prFields = "number,title,url,headRefName,isDraft,mergeable,mergeStateStatus,reviewDecision,author,body,statusCheckRollup,closingIssuesReferences,updatedAt"
    static let issueFields = "number,title,state,stateReason,labels,url,updatedAt,closedAt"

    func refresh() async {
        loading = true
        defer { loading = false }
        if account == nil {
            let who = await Shell.gh(["api", "user", "--jq", ".login"])
            account = who.ok ? who.trimmed : nil
        }
        async let p = Shell.gh(["pr", "list", "--state", "open", "--limit", "50", "--json", Self.prFields])
        async let i = Shell.gh(["issue", "list", "--state", "all", "--limit", "200", "--json", Self.issueFields])
        let (pr, iss) = await (p, i)
        var problems: [String] = []
        if pr.ok, let d = pr.output.data(using: .utf8), let v = try? JSONDecoder().decode([PullRequest].self, from: d) {
            pulls = v.sorted { $0.number < $1.number }
        } else { problems.append("pull requests: " + pr.trimmed) }
        if iss.ok, let d = iss.output.data(using: .utf8), let v = try? JSONDecoder().decode([Issue].self, from: d) {
            issues = v
        } else { problems.append("issues: " + iss.trimmed) }
        error = problems.isEmpty ? nil : "GitHub (gh) didn't answer for " + problems.joined(separator: "; ")
            + "\nIs gh installed and logged in? Run `gh auth status` in Terminal."
    }

    // MARK: pull requests

    func updateBranch(_ pr: PullRequest, _ runner: Runner) {
        runner.run("Update #\(pr.number) with main", [.gh("Update branch", "pr", "update-branch", "\(pr.number)")],
                   success: "Branch updated. The checks run again; merge when they're green.") { _ in await self.refresh() }
    }

    /// Squash-merges; the repository deletes the head branch on GitHub. Never touches local checkouts.
    func merge(_ pr: PullRequest, title: String, _ runner: Runner, ops: OpsStore, deployAfter: Bool) {
        runner.run("Squash-merge #\(pr.number)", [.gh("Squash and merge", "pr", "merge", "\(pr.number)", "--squash", "--subject", title)],
                   success: deployAfter ? "Merged. Next: confirm the deploy." : "Merged into main. Not deployed yet.") { ok in
            await self.refresh()
            await ops.refresh(fetch: true)
            if ok && deployAfter {
                runner.job = nil
                ops.deploy(runner)
            }
        }
    }

    // MARK: issues

    func setStatus(_ issue: Issue, _ status: String, _ runner: Runner) {
        var args = ["issue", "edit", "\(issue.number)", "--add-label", status]
        for old in issue.names.intersection(Labels.openStatuses) where old != status { args += ["--remove-label", old] }
        runner.run("#\(issue.number): \(status)", [Step(label: "Set status", tool: "gh", args: args)]) { _ in await self.refresh() }
    }

    func setType(_ issue: Issue, _ type: String, _ runner: Runner) {
        var args = ["issue", "edit", "\(issue.number)", "--add-label", type]
        for old in issue.names.intersection([Labels.bug, Labels.idea, "bug", "enhancement"]) where old != type { args += ["--remove-label", old] }
        runner.run("#\(issue.number): \(type)", [Step(label: "Set type", tool: "gh", args: args)]) { _ in await self.refresh() }
    }

    func close(_ issue: Issue, completed: Bool, _ runner: Runner) {
        let args = ["issue", "close", "\(issue.number)", "--reason", completed ? "completed" : "not planned"]
        var steps = [Step(label: "Close", tool: "gh", args: args)]
        let stale = issue.names.intersection(Labels.openStatuses)
        if !stale.isEmpty {
            steps.append(Step(label: "Remove open-work status", tool: "gh",
                              args: ["issue", "edit", "\(issue.number)"] + stale.flatMap { ["--remove-label", $0] }))
        }
        runner.run("Close #\(issue.number)", steps) { _ in await self.refresh() }
    }

    func reopen(_ issue: Issue, _ runner: Runner) {
        var edit = ["issue", "edit", "\(issue.number)", "--add-label", Labels.underReview]
        if issue.names.contains(Labels.released) { edit += ["--remove-label", Labels.released] }
        runner.run("Reopen #\(issue.number)", [
            .gh("Reopen", "issue", "reopen", "\(issue.number)"),
            Step(label: "Back under review", tool: "gh", args: edit),
        ]) { _ in await self.refresh() }
    }

    /// Brings one issue in line with the label scheme (type kept as is when it can't be inferred).
    func fixLabels(_ issue: Issue, _ runner: Runner) {
        var add: [String] = [], remove: [String] = []
        if issue.names.contains("bug") { remove.append("bug"); if !issue.names.contains(Labels.bug) { add.append(Labels.bug) } }
        if issue.names.contains("enhancement") { remove.append("enhancement"); if !issue.names.contains(Labels.idea) { add.append(Labels.idea) } }
        let open = issue.names.intersection(Labels.openStatuses)
        if issue.isOpen {
            if open.isEmpty { add.append(Labels.underReview) }
            if open.count > 1, let keep = [Labels.inProgress, Labels.planned, Labels.underReview].first(where: open.contains) {
                remove += open.subtracting([keep]).sorted()   // keep the most advanced status
            }
            if issue.names.contains(Labels.released) { remove.append(Labels.released) }
        } else {
            remove += open.sorted()
        }
        guard !add.isEmpty || !remove.isEmpty else { return }
        let args = ["issue", "edit", "\(issue.number)"] + add.flatMap { ["--add-label", $0] } + remove.flatMap { ["--remove-label", $0] }
        runner.run("Fix labels on #\(issue.number)", [Step(label: "Fix labels", tool: "gh", args: args)]) { _ in await self.refresh() }
    }
}
