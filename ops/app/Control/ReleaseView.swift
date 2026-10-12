import SwiftUI

struct ReleaseView: View {
    @EnvironmentObject var release: ReleaseStore
    @EnvironmentObject var ops: OpsStore
    @EnvironmentObject var github: GitHubStore
    @EnvironmentObject var runner: Runner

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Every merged pull request is a patch build. A minor release (0.x.0) is the curated update with release notes on the site's What's new page, a tag and a GitHub Release. See docs/releases.md.")
                    .foregroundStyle(.secondary)
                if let e = release.error {
                    Card(title: "Can't read the release data", systemImage: "exclamationmark.triangle") { Text(e) }
                }
                if let version = release.version, let tag = release.tag {
                    current(version: version, tag: tag)
                    next
                }
            }
            .padding(20)
        }
        .navigationTitle("Release")
    }

    // MARK: the release in release_data.json on main

    private func current(version: String, tag: String) -> some View {
        Card(title: release.inProgress ? "Release \(version): steps to finish" : "Release \(version) is out", systemImage: "shippingbox") {
            if !release.title.isEmpty { Text("“\(release.title)”").font(.title3) }
            StepRow(done: release.releaseCommit != nil, title: "Release pull request merged",
                    detail: release.releaseCommit.map { "release_data.json says \(version) on main (commit \($0.prefix(7)))." }
                        ?? "Open a release PR (chore(release): \(version)) that sets the version and adds the notes.")
            StepRow(done: release.tagExists && release.releaseExists, title: "Tag \(tag) and publish the GitHub Release",
                    detail: release.tagExists && release.releaseExists ? "Tagged and published." :
                        "Checks the metadata at the release commit, tags it, pushes the tag and publishes the notes from release_data.json.") {
                Button("Publish \(tag)…") { release.publish(runner, ops: ops, github: github) }
                    .buttonStyle(.borderedProminent)
            }
            StepRow(done: release.deployed, title: "Deploy it",
                    detail: release.deployed ? "Production runs a build that includes \(tag)." : "Production doesn't include the release commit yet.") {
                if let rc = release.releaseCommit, release.canDeployForward {
                    Button("Deploy \(tag)…") { ops.deploy(runner, ref: rc, label: "\(tag) (\(rc.prefix(7)))") }
                }
                if !ops.undeployed.isEmpty { Button("Deploy latest…") { ops.deploy(runner) } }
            }
            StepRow(done: release.unreleasedIssues.isEmpty, title: "Mark the shipped issues released",
                    detail: release.previousTag == nil ? "No earlier release to compare with." :
                        release.unreleasedIssues.isEmpty ? "Every issue closed by the \(release.shipped.count) pull request(s) in this release has status:released." :
                        "Closed by pull requests in this release, still without status:released: " + release.unreleasedIssues.map { "#\($0)" }.joined(separator: ", ")) {
                Button("Add status:released") { release.markReleased(runner, ops: ops, github: github) }
            }
        }
        .disabled(runner.busy)
    }

    // MARK: what the next release will contain

    private var next: some View {
        Card(title: "Since \(release.tag ?? "the last release"): material for \(release.nextVersion)", systemImage: "square.and.pencil") {
            if release.upcoming.isEmpty {
                Text(release.loading ? "Loading…" : "Nothing merged since the release.").foregroundStyle(.secondary)
            } else {
                ForEach(release.upcoming) { pr in
                    VStack(alignment: .leading, spacing: 2) {
                        HStack {
                            Text("#\(pr.number)").font(.body.monospaced()).foregroundStyle(.secondary)
                            Text(pr.title).lineLimit(1)
                            Spacer()
                            Button("Open") { openURL(pr.url) }.buttonStyle(.link)
                        }
                        if let note = pr.note {
                            Text(Markdown.attributed(note)).font(.callout).foregroundStyle(.secondary).padding(.leading, 40)
                        }
                    }
                }
                Divider()
                Text("When you're ready to release \(release.nextVersion): open a release pull request (chore(release): \(release.nextVersion)) that bumps pyproject.toml and release_data.json and turns these notes into changes, limitations and technical details. An agent can write it from this list. Merge it, then come back here to tag, publish and deploy.")
                    .font(.callout).foregroundStyle(.secondary)
                Button("Copy notes for the release PR") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(release.draftNotes, forType: .string)
                }
            }
        }
    }
}

struct StepRow<Actions: View>: View {
    let done: Bool
    let title: String
    let detail: String
    @ViewBuilder var actions: Actions

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: done ? "checkmark.circle.fill" : "circle.dashed")
                .foregroundStyle(done ? Brand.ok : Brand.signal).font(.title3)
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.body.weight(.semibold))
                Text(detail).font(.callout).foregroundStyle(.secondary)
                if !done { HStack { actions } }
            }
            Spacer()
        }
        .padding(.vertical, 4)
    }
}

extension StepRow where Actions == EmptyView {
    init(done: Bool, title: String, detail: String) {
        self.init(done: done, title: title, detail: detail) { EmptyView() }
    }
}
