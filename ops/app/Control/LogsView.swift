import SwiftUI

struct LogsView: View {
    @EnvironmentObject var ops: OpsStore
    enum Source: String, CaseIterable, Identifiable {
        case production = "Production app", local = "Local app", tunnel = "Tunnel", deploys = "Deploys"
        var id: String { rawValue }
        var file: String {
            switch self {
            case .production: return Paths.data + "/logs/app-production.out"
            case .local: return Paths.data + "/logs/app-local.out"
            case .tunnel: return Paths.data + "/logs/tunnel.out"
            case .deploys: return Paths.data + "/deploys.log"
            }
        }
    }
    @State private var source: Source = .production
    @State private var text = ""
    @State private var follow = true
    private let tick = Timer.publish(every: 2, on: .main, in: .common).autoconnect()

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Picker("Log", selection: $source) {
                    ForEach(Source.allCases) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented).labelsHidden().frame(maxWidth: 480)
                Toggle("Follow", isOn: $follow)
                Spacer()
                Button { reveal(source.file) } label: { Label("Show in Finder", systemImage: "folder") }
            }
            ScrollViewReader { proxy in
                ScrollView {
                    Text(text.isEmpty ? "(empty or missing: \(source.file))" : text)
                        .font(.system(.caption, design: .monospaced))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(10)
                    Color.clear.frame(height: 1).id("end")
                }
                .background(Color(nsColor: .textBackgroundColor))
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .onChange(of: text) { _ in if follow { proxy.scrollTo("end", anchor: .bottom) } }
            }
            backups
        }
        .padding(20)
        .navigationTitle("Logs & backups")
        .onAppear(perform: load)
        .onChange(of: source) { _ in load() }
        .onReceive(tick) { _ in if follow { load() } }
    }

    private var backups: some View {
        Card(title: "Database backups", systemImage: "externaldrive") {
            Text("Taken automatically before every start and deploy; the newest 14 per mode are kept. To restore one, stop AstraCore and copy it over data/<mode>/astracore.sqlite3.")
                .font(.callout).foregroundStyle(.secondary)
            ForEach(ops.backups.prefix(5)) { b in
                HStack {
                    Pill(text: b.mode, color: b.mode == "production" ? Brand.signal : .secondary)
                    Text(URL(fileURLWithPath: b.path).lastPathComponent).font(.callout.monospaced())
                    Spacer()
                    Text(ByteCountFormatter.string(fromByteCount: b.size, countStyle: .file)).font(.caption).foregroundStyle(.secondary)
                    Button("Show") { reveal(b.path) }.buttonStyle(.link)
                }
            }
            if ops.backups.isEmpty { Text("No backups yet.").foregroundStyle(.secondary) }
        }
    }

    /// The last ~128 KB of the file, so huge logs stay fast.
    private func load() {
        guard let h = FileHandle(forReadingAtPath: source.file) else { text = ""; return }
        defer { try? h.close() }
        let size = (try? h.seekToEnd()) ?? 0
        let start = size > 131_072 ? size - 131_072 : 0
        try? h.seek(toOffset: start)
        var s = String(decoding: h.readDataToEndOfFile(), as: UTF8.self)
        if start > 0, let nl = s.firstIndex(of: "\n") { s = "…\n" + s[s.index(after: nl)...] }
        if s != text { text = s }
    }
}
