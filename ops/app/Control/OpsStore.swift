import SwiftUI

/// `./astracore status --json`
struct OpsStatus: Decodable {
    struct App: Decodable { let running: Bool; let mode: String?; let pid: Int?; let healthy: Bool; let url: String? }
    struct Tunnel: Decodable { let running: Bool; let pid: Int? }
    struct Urls: Decodable { let production: String; let local: String }
    struct Production: Decodable {
        let checkout: String; let exists: Bool; let commit: String?; let build: String?; let subject: String?
        let edited: Bool; let undeployed: Int?
    }
    let home: String
    let app: App
    let tunnel: Tunnel
    let urls: Urls
    let production: Production

    var productionRunning: Bool { app.running && app.mode == "production" }
    var localRunning: Bool { app.running && app.mode == "local" }
}

struct Commit: Identifiable, Hashable {
    let id: String          // full sha
    let short: String
    let subject: String
    var pr: Int? { subject.pullRequestNumber }
}

struct Deploy: Identifiable {
    let id = UUID()
    let date: Date?
    let commit: String
    let build: String
    let kind: String        // deploy | rollback
}

struct Backup: Identifiable {
    var id: String { path }
    let path: String
    let mode: String
    let date: Date
    let size: Int64
}

@MainActor
final class OpsStore: ObservableObject {
    @Published var status: OpsStatus?
    @Published var error: String?
    @Published var undeployed: [Commit] = []
    @Published var deploys: [Deploy] = []
    @Published var backups: [Backup] = []
    @Published var publicHealthy: Bool?
    @Published var repoURL: String?           // https://github.com/owner/repo
    @Published var lastFetch: Date?
    @Published var loading = false

    private var timer: Timer?

    /// First status load (awaited, so pages that need the production commit have it), then every 20 s.
    func start() async {
        await refresh(fetch: true)
        timer = Timer.scheduledTimer(withTimeInterval: 20, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                let stale = (self.lastFetch.map { Date().timeIntervalSince($0) > 300 }) ?? true
                await self.refresh(fetch: stale)
            }
        }
    }

    func refresh(fetch: Bool = false) async {
        loading = true
        defer { loading = false }
        if fetch {
            _ = await Shell.git("fetch", "--quiet", "--tags", "--prune", "origin")
            lastFetch = Date()
        }
        if repoURL == nil { repoURL = await Self.githubURL() }
        let r = await Shell.astracore("status", "--json")
        if r.ok, let data = r.trimmed.data(using: .utf8), let s = try? JSONDecoder().decode(OpsStatus.self, from: data) {
            status = s
            error = nil
        } else {
            error = r.ok ? "Couldn't read the status (is ./astracore up to date in \(Paths.repo)?)" : r.trimmed
        }
        if let commit = status?.production.commit {
            let log = await Shell.git("log", "--format=%H%x09%h%x09%s", "\(commit)..origin/main")
            undeployed = log.ok ? Self.commits(log.output) : []
        } else {
            undeployed = []
        }
        deploys = Self.readDeploys()
        backups = Self.readBackups()
        if let s = status, s.productionRunning {
            publicHealthy = await Self.healthy(s.urls.production)
        } else {
            publicHealthy = nil
        }
    }

    // MARK: actions

    func deploy(_ runner: Runner, ref: String? = nil, label: String? = nil) {
        let what = label ?? (ref == nil ? "the latest merged commit (\(undeployed.count) not deployed yet)" : ref!)
        runner.ask("Deploy to production?", "Production will run \(what). The site restarts and is unreachable for a few seconds. If the new build doesn't start, the previous one is put back automatically.", button: "Deploy") {
            var args = ["deploy"]
            if let ref { args.append(ref) }
            runner.run("Deploy to production", [Step(label: "Deploy", tool: Paths.repo + "/astracore", args: args)],
                       success: "Deployed. Check the site footer for the new build.") { _ in await self.refresh(fetch: true) }
        }
    }

    func rollback(_ runner: Runner) {
        runner.ask("Roll back production?", "Production goes back to the previously deployed commit. Database migrations are not undone; a backup from before each start is in data/backups/production.", button: "Roll back", destructive: true) {
            runner.run("Roll back production", [.astracore("Roll back", "rollback")]) { _ in await self.refresh(fetch: true) }
        }
    }

    func restartProduction(_ runner: Runner) {
        runner.ask("Restart production?", "Restarts the build that's deployed now (no new code). The site is unreachable for a few seconds.", button: "Restart") {
            runner.run("Restart production", [.astracore("Restart", "restart", "--prod")]) { _ in await self.refresh() }
        }
    }

    func startProduction(_ runner: Runner) {
        let local = status?.localRunning == true
        runner.ask("Put AstraCore online?", (local ? "Local test mode is running and will be stopped first. " : "") + "Starts the deployed build and the Cloudflare tunnel; anyone on the invite list can log in.", button: "Start production") {
            var steps: [Step] = []
            if local { steps.append(.astracore("Stop local test", "stop")) }
            steps.append(.astracore("Start production", "start", "--prod"))
            runner.run("Start production", steps) { _ in await self.refresh() }
        }
    }

    func stop(_ runner: Runner) {
        let prod = status?.productionRunning == true
        runner.ask(prod ? "Take AstraCore offline?" : "Stop local test?",
                   prod ? "Stops the tunnel (visitors get Cloudflare's offline page) and then the app." : "Stops the local app.",
                   button: prod ? "Take offline" : "Stop", destructive: prod) {
            runner.run(prod ? "Stop production" : "Stop local test", [.astracore("Stop", "stop")]) { _ in await self.refresh() }
        }
    }

    func startLocal(_ runner: Runner) {
        let prod = status?.productionRunning == true
        let go = {
            var steps: [Step] = []
            if prod { steps.append(.astracore("Stop production", "stop")) }
            steps.append(.astracore("Start local test", "start"))
            runner.run("Start local test", steps, success: "Local test is running.") { ok in
                await self.refresh()
                if ok { openURL(self.status?.urls.local) }
            }
        }
        if prod {
            runner.ask("Take the public site offline?", "Local test and production use the same port, so production stops while you test locally. Start production again when you're done.", button: "Stop production and test locally", destructive: true, action: go)
        } else {
            go()
        }
    }

    // MARK: helpers

    static func commits(_ out: String) -> [Commit] {
        out.split(separator: "\n").compactMap { line in
            let f = line.split(separator: "\t", maxSplits: 2, omittingEmptySubsequences: false).map(String.init)
            return f.count == 3 ? Commit(id: f[0], short: f[1], subject: f[2]) : nil
        }
    }

    static func readDeploys() -> [Deploy] {
        guard let text = try? String(contentsOfFile: Paths.data + "/deploys.log", encoding: .utf8) else { return [] }
        let iso = ISO8601DateFormatter()
        return text.split(separator: "\n").reversed().compactMap { line in
            let f = line.split(separator: "\t", omittingEmptySubsequences: false).map(String.init)
            guard f.count >= 4 else { return nil }
            return Deploy(date: iso.date(from: f[0]), commit: f[1], build: f[2], kind: f[3])
        }
    }

    static func readBackups() -> [Backup] {
        let fm = FileManager.default
        var out: [Backup] = []
        for mode in ["production", "local"] {
            let dir = Paths.data + "/backups/" + mode
            for name in (try? fm.contentsOfDirectory(atPath: dir)) ?? [] where name.hasSuffix(".sqlite3") {
                let path = dir + "/" + name
                let attrs = try? fm.attributesOfItem(atPath: path)
                out.append(Backup(path: path, mode: mode, date: attrs?[.modificationDate] as? Date ?? .distantPast,
                                  size: (attrs?[.size] as? NSNumber)?.int64Value ?? 0))
            }
        }
        return out.sorted { $0.date > $1.date }
    }

    static func healthy(_ base: String) async -> Bool {
        guard let url = URL(string: base.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/healthz") else { return false }
        var req = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 8)
        req.httpMethod = "GET"
        guard let (_, resp) = try? await URLSession.shared.data(for: req) else { return false }
        return (resp as? HTTPURLResponse)?.statusCode == 200
    }

    static func githubURL() async -> String? {
        let r = await Shell.git("remote", "get-url", "origin")
        guard r.ok else { return nil }
        var s = r.trimmed
        if s.hasPrefix("git@github.com:") { s = "https://github.com/" + s.dropFirst("git@github.com:".count) }
        if s.hasSuffix(".git") { s.removeLast(4) }
        return s.hasPrefix("https://") ? s : nil
    }
}
