import SwiftUI

/// A merged pull request as the release wizard needs it.
struct MergedPR: Identifiable, Decodable, Hashable {
    let number: Int
    let title: String
    let url: String
    let body: String
    let closingIssuesReferences: [IssueRef]
    var id: Int { number }
    var note: String? { Markdown.section("Note for the next release", in: body) }
}

/// The minor release flow of docs/releases.md, worked out from git and GitHub.
@MainActor
final class ReleaseStore: ObservableObject {
    @Published var version: String?           // current_version in release_data.json on origin/main, e.g. 0.2.0
    @Published var title = ""
    @Published var tagExists = false
    @Published var releaseExists = false
    @Published var releaseCommit: String?     // the release PR's squash commit (or what the tag points at)
    @Published var previousTag: String?
    @Published var deployed = false
    @Published var canDeployForward = false   // production is behind the release commit (deploying it isn't a rollback)
    @Published var shipped: [MergedPR] = []   // PRs in the release
    @Published var upcoming: [MergedPR] = []  // merged since the release: material for the next one
    @Published var unreleasedIssues: [Int] = []  // closed by shipped PRs, without status:released
    @Published var loading = false
    @Published var error: String?

    var tag: String? { version.map { "v" + $0 } }
    var inProgress: Bool { version != nil && (!tagExists || !releaseExists || !deployed || !unreleasedIssues.isEmpty) }
    var nextVersion: String {
        guard let v = version, case let parts = v.split(separator: "."), parts.count == 3, let minor = Int(parts[1]) else { return "0.?.0" }
        return "\(parts[0]).\(minor + 1).0"
    }

    func refresh(ops: OpsStore, issues: [Issue]) async {
        loading = true
        defer { loading = false }
        error = nil
        let data = await Shell.git("show", "origin/main:src/astracore/release_data.json")
        guard data.ok, let json = try? JSONSerialization.jsonObject(with: Data(data.output.utf8)) as? [String: Any],
              let current = json["current_version"] as? String else {
            error = "Couldn't read src/astracore/release_data.json on origin/main."
            return
        }
        version = current
        title = ((json["releases"] as? [[String: Any]])?.first { $0["version"] as? String == current }?["title"] as? String) ?? ""
        let tag = "v" + current
        tagExists = await Shell.git("rev-parse", "-q", "--verify", "refs/tags/\(tag)").ok
        let commit = tagExists ? await Shell.git("rev-list", "-n", "1", tag)
                               : await Shell.git("log", "-1", "--format=%H", "origin/main", "--", "src/astracore/release_data.json")
        releaseCommit = commit.ok ? commit.trimmed : nil
        releaseExists = await Shell.gh(["release", "view", tag, "--json", "tagName"]).ok
        guard let rc = releaseCommit else { return }
        let prev = await Shell.git("describe", "--tags", "--abbrev=0", "--match", "v0.*.0", "\(rc)^")
        previousTag = prev.ok ? prev.trimmed : nil
        if ops.status == nil { await ops.refresh() }
        if let prod = ops.status?.production.commit {
            deployed = await Shell.git("merge-base", "--is-ancestor", rc, prod).ok
            let behind = await Shell.git("merge-base", "--is-ancestor", prod, rc).ok
            canDeployForward = !deployed && behind
        } else {
            deployed = false
            canDeployForward = ops.status?.production.exists == false
        }
        // Pull requests in this release (needs the previous tag) and merged since.
        if let prevTag = previousTag {
            shipped = await Self.pulls(range: "\(prevTag)..\(rc)")
        } else {
            shipped = []
        }
        upcoming = await Self.pulls(range: "\(rc)..origin/main")
        let closed = Set(shipped.flatMap { $0.closingIssuesReferences.map(\.number) })
        let byNumber = Dictionary(uniqueKeysWithValues: issues.map { ($0.number, $0) })
        unreleasedIssues = closed.filter { n in
            guard let issue = byNumber[n] else { return false }
            return !issue.isOpen && issue.stateReason == "COMPLETED" && !issue.names.contains(Labels.released)
        }.sorted()
    }

    static func pulls(range: String) async -> [MergedPR] {
        let log = await Shell.git("log", "--format=%s", range)
        let numbers = log.ok ? log.output.split(separator: "\n").compactMap { String($0).pullRequestNumber } : []
        return await withTaskGroup(of: MergedPR?.self) { group in
            for n in numbers {
                group.addTask {
                    let r = await Shell.gh(["pr", "view", "\(n)", "--json", "number,title,url,body,closingIssuesReferences"])
                    return r.ok ? try? JSONDecoder().decode(MergedPR.self, from: Data(r.output.utf8)) : nil
                }
            }
            var out: [MergedPR] = []
            for await pr in group { if let pr { out.append(pr) } }
            return out.sorted { $0.number < $1.number }
        }
    }

    /// Draft text for the next release PR: every pilot-facing note since the last release.
    var draftNotes: String {
        var lines = ["Changes merged since \(tag ?? "the last release") (for \(nextVersion)):", ""]
        for pr in upcoming {
            lines.append("- #\(pr.number) \(pr.title)" + (pr.note.map { "\n  Note: " + $0.replacingOccurrences(of: "\n", with: " ") } ?? ""))
        }
        return lines.joined(separator: "\n")
    }

    // MARK: actions

    /// Checks the metadata at the release commit, tags it, pushes the tag and publishes the GitHub Release.
    func publish(_ runner: Runner, ops: OpsStore, github: GitHubStore) {
        guard let version, let tag, let rc = releaseCommit else { return }
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("astracore-release-\(version)-\(UUID().uuidString.prefix(6))").path
        let notes = dir + "-notes.md"
        var steps: [Step] = [
            .git("Check out the release commit (temporary)", "worktree", "add", "--detach", dir, rc),
            Step(label: "Check the release metadata", tool: Paths.python, args: ["scripts/check_release.py", "--tag", tag], cwd: dir),
            Step(label: "Write the release notes", tool: Paths.python, args: ["scripts/check_release.py", "--notes", version], cwd: dir, outputFile: notes),
        ]
        if !tagExists {
            steps += [
                .git("Tag the release commit", "tag", "-a", tag, "-m", "AstraCore \(version)", rc),
                .git("Push the tag", "push", "origin", tag),
            ]
        }
        if !releaseExists {
            steps.append(.gh("Publish the GitHub Release", "release", "create", tag, "--verify-tag",
                             "--title", "AstraCore \(version)" + (title.isEmpty ? "" : " · \(title)"), "--notes-file", notes))
        }
        runner.ask("Publish AstraCore \(version)?", "Tags \(String(rc.prefix(7))) as \(tag), pushes the tag and publishes the GitHub Release from release_data.json. Published tags are never moved or reused.", button: "Publish \(tag)") {
            runner.run("Publish \(tag)", steps, cleanup: [.git("Remove the temporary checkout", "worktree", "remove", "--force", dir)],
                       success: "Published \(tag). Next: deploy it and mark the shipped issues released.") { _ in
                await ops.refresh(fetch: true)
                await self.refresh(ops: ops, issues: github.issues)
            }
        }
    }

    func markReleased(_ runner: Runner, ops: OpsStore, github: GitHubStore) {
        let steps = unreleasedIssues.map { Step(label: "#\($0)", tool: "gh", args: ["issue", "edit", "\($0)", "--add-label", Labels.released]) }
        runner.run("Mark \(steps.count) issue(s) released", steps) { _ in
            await github.refresh()
            await self.refresh(ops: ops, issues: github.issues)
        }
    }
}
