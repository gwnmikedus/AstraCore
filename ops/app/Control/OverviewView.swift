import SwiftUI

struct OverviewView: View {
    @EnvironmentObject var ops: OpsStore
    @EnvironmentObject var runner: Runner

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if let err = ops.error {
                    Card(title: "Can't read the status", systemImage: "exclamationmark.triangle") {
                        Text(err).font(.callout).textSelection(.enabled)
                    }
                }
                if wrongCheckout, let s = ops.status {
                    Card(title: "This copy of the app may be in the wrong checkout", systemImage: "exclamationmark.triangle") {
                        Text("It works on \(s.home), but there's no production checkout at \(s.production.checkout) and nothing runs here. If production runs from another checkout (for example ~/Eve), build and open the app there: ops/app/build.sh in that checkout. Production actions are off here; for a genuine first deploy, run ./astracore deploy in Terminal.")
                            .font(.callout).textSelection(.enabled)
                        Button("Show this app in Finder") { reveal(Bundle.main.bundlePath) }
                    }
                }
                production
                undeployedCard
                HStack(alignment: .top, spacing: 16) {
                    localCard
                    historyCard
                }
            }
            .padding(20)
        }
        .navigationTitle("Production")
    }

    /// Nothing runs from this checkout and it has no production checkout: likely a copy built in another clone.
    private var wrongCheckout: Bool {
        guard let s = ops.status else { return false }
        return !s.production.exists && !s.app.running && !s.tunnel.running
    }

    // MARK: production

    private var state: (String, String, Color) {
        guard let s = ops.status else { return ("Checking…", "", .secondary) }
        if s.productionRunning {
            if !s.app.healthy { return ("Not answering", "The app runs but /healthz doesn't answer. Check the logs, or restart.", Brand.bad) }
            if ops.publicHealthy == false { return ("Online locally, not reachable publicly", "The app is healthy, but the public URL doesn't answer. Check the tunnel log.", Brand.warn) }
            return ("Online", "The public site is up\(s.tunnel.running ? " through the Cloudflare tunnel" : "").", Brand.ok)
        }
        if s.localRunning { return ("Offline: local test is running", "Local test uses the same port, so production is stopped.", Brand.warn) }
        return ("Offline", "Production isn't running. Visitors see Cloudflare's offline page.", Brand.bad)
    }

    private var production: some View {
        let s = ops.status
        let (title, detail, color) = state
        return Card(title: "Production", systemImage: "globe") {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                StatusDot(color: color)
                Text(title).font(.title2.weight(.semibold))
                Spacer()
                if let url = s?.urls.production {
                    Button { openURL(url) } label: { Label(url.replacingOccurrences(of: "https://", with: ""), systemImage: "arrow.up.right.square") }
                        .buttonStyle(.link)
                }
            }
            Text(detail).foregroundStyle(.secondary)
            Divider()
            Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 6) {
                GridRow {
                    Text("Build").foregroundStyle(.secondary)
                    if let p = s?.production, p.exists {
                        HStack(spacing: 8) {
                            Text(p.build ?? "?").font(.body.monospaced())
                            Text(p.subject ?? "").lineLimit(1)
                            if p.edited { Pill(text: "edited by hand", color: Brand.bad) }
                        }
                    } else {
                        Text("No production checkout yet: deploy once to create it.")
                    }
                }
                GridRow {
                    Text("Processes").foregroundStyle(.secondary)
                    Text(processes(s))
                }
                if let last = ops.deploys.first {
                    GridRow {
                        Text("Last deploy").foregroundStyle(.secondary)
                        Text("\(last.date.map(Self.relative) ?? "?") · \(last.kind) · \(String(last.commit.prefix(7)))")
                    }
                }
            }
            if s?.production.edited == true {
                Text("Someone changed files in the production checkout by hand. The next deploy discards that; ship fixes through a pull request instead.")
                    .font(.callout).foregroundStyle(Brand.bad)
            }
            HStack(spacing: 10) {
                Button {
                    ops.deploy(runner)
                } label: {
                    Label(ops.undeployed.isEmpty ? "Redeploy latest" : "Deploy \(ops.undeployed.count) change\(ops.undeployed.count == 1 ? "" : "s")",
                          systemImage: "arrow.up.circle.fill")
                }
                .buttonStyle(.borderedProminent)
                .help("./astracore deploy: pin production to the tip of origin/main and restart")
                Button { ops.rollback(runner) } label: { Label("Roll back", systemImage: "arrow.uturn.backward") }
                    .disabled(ops.deploys.count < 2)
                    .help("./astracore rollback: back to the previously deployed commit")
                Spacer()
                if s?.productionRunning == true {
                    Button { ops.restartProduction(runner) } label: { Label("Restart", systemImage: "arrow.clockwise") }
                    Button(role: .destructive) { ops.stop(runner) } label: { Label("Take offline", systemImage: "stop.circle") }
                } else {
                    Button { ops.startProduction(runner) } label: { Label("Start production", systemImage: "play.circle") }
                        .disabled(s?.production.exists != true)
                }
            }
            .disabled(runner.busy || s == nil || wrongCheckout)
        }
    }

    private func processes(_ s: OpsStatus?) -> String {
        guard let s else { return "?" }
        var parts: [String] = []
        parts.append(s.app.running ? "app pid \(s.app.pid ?? 0) (\(s.app.mode ?? "?"))" : "app stopped")
        parts.append(s.tunnel.running ? "tunnel pid \(s.tunnel.pid ?? 0)" : "tunnel stopped")
        return parts.joined(separator: " · ")
    }

    // MARK: undeployed

    private var undeployedCard: some View {
        Card(title: ops.undeployed.isEmpty ? "Everything merged is deployed" : "Merged, not deployed yet", systemImage: "tray.and.arrow.up") {
            if ops.undeployed.isEmpty {
                Text("Production runs the tip of main\(ops.lastFetch.map { " (checked \(Self.relative($0)))" } ?? "").")
                    .foregroundStyle(.secondary)
            } else {
                ForEach(ops.undeployed) { c in
                    HStack(spacing: 8) {
                        Text(c.short).font(.body.monospaced()).foregroundStyle(.secondary)
                        Text(c.subject).lineLimit(1)
                        Spacer()
                        if let pr = c.pr, let repo = ops.repoURL {
                            Button("#\(pr)") { openURL("\(repo)/pull/\(pr)") }.buttonStyle(.link)
                        }
                    }
                    .contextMenu {
                        Button("Deploy up to this commit…") { ops.deploy(runner, ref: c.id, label: "\(c.short) \(c.subject)") }
                    }
                }
                Text("Deploy ships all of them. Right-click a commit to deploy only up to it.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    // MARK: local

    private var localCard: some View {
        let s = ops.status
        return Card(title: "Local test", systemImage: "laptopcomputer") {
            HStack(spacing: 8) {
                StatusDot(color: s?.localRunning == true ? Brand.ok : .secondary.opacity(0.5))
                Text(s?.localRunning == true ? "Running (\(s?.urls.local ?? ""))" : "Stopped")
            }
            Text("Runs this checkout with .env.local and data/local, for trying things before they're merged. It shares production's port.")
                .font(.callout).foregroundStyle(.secondary)
            HStack {
                if s?.localRunning == true {
                    Button("Open") { openURL(s?.urls.local) }
                    Button("Stop") { ops.stop(runner) }
                } else {
                    Button("Start local test") { ops.startLocal(runner) }
                }
            }
            .disabled(runner.busy || s == nil)
        }
    }

    // MARK: history

    private var historyCard: some View {
        Card(title: "Deploy history", systemImage: "clock.arrow.circlepath") {
            if ops.deploys.isEmpty {
                Text("No deploys recorded yet (data/deploys.log).").foregroundStyle(.secondary)
            } else {
                ForEach(ops.deploys.prefix(8)) { d in
                    HStack(spacing: 8) {
                        Image(systemName: d.kind == "rollback" ? "arrow.uturn.backward.circle" : "arrow.up.circle")
                            .foregroundStyle(d.kind == "rollback" ? Brand.warn : Brand.ok)
                        Text(d.build).font(.callout.monospaced())
                        Spacer()
                        Text(d.date.map(Self.relative) ?? "").font(.caption).foregroundStyle(.secondary)
                    }
                    .contextMenu {
                        Button("Deploy this build again…") { ops.deploy(runner, ref: d.commit, label: d.build) }
                        Button("Copy commit") {
                            NSPasteboard.general.clearContents()
                            NSPasteboard.general.setString(d.commit, forType: .string)
                        }
                    }
                }
            }
        }
    }

    static func relative(_ d: Date) -> String {
        if abs(d.timeIntervalSinceNow) < 60 { return "just now" }
        let f = RelativeDateTimeFormatter()
        f.locale = Locale(identifier: "en_GB")   // the app's text is English
        f.unitsStyle = .short
        return f.localizedString(for: d, relativeTo: Date())
    }
}
