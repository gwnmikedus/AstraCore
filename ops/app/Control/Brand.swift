import SwiftUI

/// AstraCore brand: graphite, bone and signal orange (the mark from src/astracore/static/img/mark.svg).
enum Brand {
    static let graphite = Color(red: 0x0b / 255, green: 0x0c / 255, blue: 0x0d / 255)
    static let bone = Color(red: 0xec / 255, green: 0xe8 / 255, blue: 0xdf / 255)
    static let signal = Color(red: 0xff / 255, green: 0x6a / 255, blue: 0x1a / 255)
    static let ok = Color(red: 0.20, green: 0.70, blue: 0.40)
    static let warn = Color(red: 0.95, green: 0.62, blue: 0.10)
    static let bad = Color(red: 0.86, green: 0.25, blue: 0.22)

    /// The mark's outline (a square with two cut corners), fitted to `rect`, from the SVG path M6 6H44L58 20V58H20L6 44Z.
    static func outline(in rect: CGRect) -> Path {
        let s = min(rect.width, rect.height) / 52, ox = rect.midX - 26 * s, oy = rect.midY - 26 * s
        func pt(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x: ox + (x - 6) * s, y: oy + (y - 6) * s) }
        var p = Path()
        p.move(to: pt(6, 6)); p.addLine(to: pt(44, 6)); p.addLine(to: pt(58, 20))
        p.addLine(to: pt(58, 58)); p.addLine(to: pt(20, 58)); p.addLine(to: pt(6, 44)); p.closeSubpath()
        return p
    }

    static func core(in rect: CGRect) -> CGRect {
        let s = min(rect.width, rect.height) / 52
        return CGRect(x: rect.midX - 26 * s + 18 * s, y: rect.midY - 26 * s + 18 * s, width: 16 * s, height: 16 * s)
    }

    /// Template image for the menu bar (macOS tints it for light/dark and highlight).
    static let menuBarImage: NSImage = {
        let size = NSSize(width: 18, height: 18)
        let img = NSImage(size: size, flipped: true) { rect in
            let box = rect.insetBy(dx: 1.5, dy: 1.5)
            let outline = Brand.outline(in: box)
            let ns = NSBezierPath()
            ns.lineWidth = 2.2
            ns.lineJoinStyle = .miter
            outline.forEach { el in
                switch el {
                case .move(let p): ns.move(to: p)
                case .line(let p): ns.line(to: p)
                case .closeSubpath: ns.close()
                default: break
                }
            }
            NSColor.black.setStroke(); ns.stroke()
            NSColor.black.setFill(); NSBezierPath(rect: Brand.core(in: box)).fill()
            return true
        }
        img.isTemplate = true
        return img
    }()
}

struct MarkView: View {
    var size: CGFloat = 28
    var body: some View {
        Canvas { ctx, sz in
            let rect = CGRect(origin: .zero, size: sz)
            ctx.fill(Path(roundedRect: rect, cornerRadius: sz.width * 0.22), with: .color(Brand.graphite))
            let box = rect.insetBy(dx: sz.width * 0.2, dy: sz.height * 0.2)
            ctx.stroke(Brand.outline(in: box), with: .color(Brand.bone),
                       style: StrokeStyle(lineWidth: sz.width * 0.075, lineJoin: .miter))
            ctx.fill(Path(Brand.core(in: box)), with: .color(Brand.signal))
        }
        .frame(width: size, height: size)
    }
}

/// A small coloured label, like the site's pills.
struct Pill: View {
    let text: String
    var color: Color = .secondary
    var body: some View {
        Text(text)
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 7).padding(.vertical, 2)
            .background(color.opacity(0.16), in: Capsule())
            .foregroundStyle(color)
    }
}

struct StatusDot: View {
    let color: Color
    var body: some View { Circle().fill(color).frame(width: 10, height: 10) }
}

/// A titled card section used across the app.
struct Card<Content: View>: View {
    let title: String
    var systemImage: String? = nil
    @ViewBuilder var content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                if let systemImage { Image(systemName: systemImage).foregroundStyle(Brand.signal) }
                Text(title).font(.headline)
            }
            content
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.08)))
    }
}

func openURL(_ s: String?) {
    guard let s, let url = URL(string: s) else { return }
    NSWorkspace.shared.open(url)
}

func reveal(_ path: String) {
    NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
}
