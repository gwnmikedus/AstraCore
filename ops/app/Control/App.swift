import SwiftUI

@main
struct AstraCoreControlApp: App {
    @StateObject private var ops = OpsStore()
    @StateObject private var github = GitHubStore()
    @StateObject private var release = ReleaseStore()
    @StateObject private var runner = Runner()

    var body: some Scene {
        Window("AstraCore Control", id: "main") {
            ContentView()
                .environmentObject(ops).environmentObject(github).environmentObject(release).environmentObject(runner)
                .tint(Brand.signal)
                .frame(minWidth: 940, minHeight: 620)
        }
        .defaultSize(width: 1120, height: 760)
        .commands {
            CommandGroup(after: .toolbar) {
                Button("Refresh") { Task { await refreshAll() } }.keyboardShortcut("r")
            }
        }

        MenuBarExtra {
            MenuBarContent()
                .environmentObject(ops).environmentObject(runner)
        } label: {
            Image(nsImage: Brand.menuBarImage)
        }
    }

    @MainActor private func refreshAll() async {
        await ops.refresh(fetch: true)
        await github.refresh()
        await release.refresh(ops: ops, issues: github.issues)
    }
}

enum Section: String, CaseIterable, Identifiable {
    case overview = "Production", pulls = "Pull requests", issues = "Issues", release = "Release", logs = "Logs & backups"
    var id: String { rawValue }
    var icon: String {
        switch self {
        case .overview: return "server.rack"
        case .pulls: return "arrow.triangle.pull"
        case .issues: return "exclamationmark.bubble"
        case .release: return "shippingbox"
        case .logs: return "doc.text.magnifyingglass"
        }
    }
}

struct ContentView: View {
    @EnvironmentObject var ops: OpsStore
    @EnvironmentObject var github: GitHubStore
    @EnvironmentObject var release: ReleaseStore
    @EnvironmentObject var runner: Runner
    @State private var section: Section? = .overview
    @State private var started = false

    var body: some View {
        NavigationSplitView {
            List(selection: $section) {
                ForEach(Section.allCases) { s in
                    Label(s.rawValue, systemImage: s.icon)
                        .badge(badge(s))
                        .tag(s)
                }
            }
            .navigationSplitViewColumnWidth(min: 220, ideal: 230, max: 300)
            .safeAreaInset(edge: .top) {
                HStack(spacing: 10) {
                    MarkView(size: 30)
                    VStack(alignment: .leading, spacing: 0) {
                        Text("AstraCore").font(.headline)
                        Text("Control").font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                }
                .padding(.horizontal, 14).padding(.vertical, 10)
            }
            .safeAreaInset(edge: .bottom) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(Paths.repo).font(.caption2).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
                    if let a = github.account { Text("GitHub: \(a)").font(.caption2).foregroundStyle(.secondary) }
                }
                .padding(12)
            }
        } detail: {
            Group {
                switch section ?? .overview {
                case .overview: OverviewView()
                case .pulls: PullRequestsView()
                case .issues: IssuesView()
                case .release: ReleaseView()
                case .logs: LogsView()
                }
            }
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button {
                        Task {
                            await ops.refresh(fetch: true)
                            await github.refresh()
                            await release.refresh(ops: ops, issues: github.issues)
                        }
                    } label: {
                        if ops.loading || github.loading || release.loading {
                            ProgressView().controlSize(.small)
                        } else {
                            Label("Refresh", systemImage: "arrow.clockwise")
                        }
                    }
                    .help("Fetch from GitHub and refresh everything (⌘R)")
                }
            }
        }
        .sheet(item: $runner.job) { job in JobSheet(job: job).environmentObject(runner) }
        .alert(item: $runner.confirmation) { c in
            Alert(title: Text(c.title), message: Text(c.message),
                  primaryButton: c.destructive ? .destructive(Text(c.button), action: c.action) : .default(Text(c.button), action: c.action),
                  secondaryButton: .cancel())
        }
        .task {
            guard !started else { return }
            started = true
            ops.start()
            await github.refresh()
            await release.refresh(ops: ops, issues: github.issues)
            await Snapshot.run(runner: runner) { section = $0 }
        }
    }

    private func badge(_ s: Section) -> Int {
        switch s {
        case .overview: return ops.undeployed.count
        case .pulls: return github.pulls.count
        case .issues: return github.issues.filter { !$0.labelProblems.isEmpty }.count
        case .release: return release.inProgress ? 1 : 0
        case .logs: return 0
        }
    }
}

struct MenuBarContent: View {
    @EnvironmentObject var ops: OpsStore
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        let s = ops.status
        Text(s == nil ? "Status unknown" :
             s!.productionRunning ? (s!.app.healthy ? "Production online" : "Production not answering") :
             s!.localRunning ? "Local test running (site offline)" : "AstraCore offline")
        if let build = s?.production.build { Text("Build \(build)") }
        if !ops.undeployed.isEmpty { Text("\(ops.undeployed.count) merged change(s) not deployed") }
        Divider()
        Button("Open AstraCore Control") {
            openWindow(id: "main")
            NSApp.activate(ignoringOtherApps: true)
        }
        Button("Open site") { openURL(s?.productionRunning == true ? s?.urls.production : s?.urls.local) }
            .disabled(s?.app.running != true)
        Button("Refresh") { Task { await ops.refresh(fetch: true) } }
        Divider()
        Button("Quit AstraCore Control") { NSApp.terminate(nil) }
    }
}
