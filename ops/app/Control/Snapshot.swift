import SwiftUI

/// Development aid: `ASTRACORE_CONTROL_SNAPSHOT=<folder>` makes the app save a PNG of each page (of its own
/// window, which needs no screen-recording permission) and quit. Used for screenshots in pull requests.
enum Snapshot {
    static let folder = ProcessInfo.processInfo.environment["ASTRACORE_CONTROL_SNAPSHOT"]

    @MainActor
    static func run(runner: Runner, select: @escaping (Section) -> Void) async {
        guard let folder else { return }
        try? FileManager.default.createDirectory(atPath: folder, withIntermediateDirectories: true)
        try? await Task.sleep(nanoseconds: 4_000_000_000)
        for (i, section) in Section.allCases.enumerated() {
            select(section)
            try? await Task.sleep(nanoseconds: 1_500_000_000)
            // the main window (its title follows the page; the menu-bar item's window is tiny)
            guard let window = NSApp.windows.filter({ $0.isVisible }).max(by: { $0.frame.width < $1.frame.width }),
                  let image = CGWindowListCreateImage(.null, .optionIncludingWindow, CGWindowID(window.windowNumber),
                                                      [.boundsIgnoreFraming, .bestResolution]) else { continue }
            let rep = NSBitmapImageRep(cgImage: image)
            let name = section.rawValue.lowercased().replacingOccurrences(of: " ", with: "-").replacingOccurrences(of: "&", with: "and")
            try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: "\(folder)/\(i + 1)-\(name).png"))
        }
        // The job console, with a read-only job
        select(.overview)
        runner.run("Snapshot: read-only job", [.git("Git version", "--version"), .astracore("Status", "status")])
        while runner.busy { try? await Task.sleep(nanoseconds: 200_000_000) }
        try? await Task.sleep(nanoseconds: 1_000_000_000)
        if let sheet = NSApp.windows.compactMap(\.attachedSheet).first,
           let image = CGWindowListCreateImage(.null, .optionIncludingWindow, CGWindowID(sheet.windowNumber), [.boundsIgnoreFraming, .bestResolution]) {
            try? NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: "\(folder)/6-job.png"))
        }
        runner.job = nil   // an open sheet would block quitting
        try? await Task.sleep(nanoseconds: 500_000_000)
        NSApp.terminate(nil)
    }
}
