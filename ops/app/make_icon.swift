// Draws the AstraCore Control app icon (1024×1024 PNG) from the brand mark (src/astracore/static/img/mark.svg),
// laid out like a macOS app icon: an 824 pt rounded tile with a margin and a soft shadow.
// Usage: swift ops/app/make_icon.swift <out.png>
import AppKit

let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "AppIcon.png"
let size = 1024
let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size, bitsPerSample: 8, samplesPerPixel: 4,
                           hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
let ctx = NSGraphicsContext.current!.cgContext
// SVG coordinates (y down)
ctx.translateBy(x: 0, y: CGFloat(size))
ctx.scaleBy(x: 1, y: -1)

func rgb(_ hex: UInt32, _ a: CGFloat = 1) -> CGColor {
    CGColor(red: CGFloat((hex >> 16) & 0xff) / 255, green: CGFloat((hex >> 8) & 0xff) / 255, blue: CGFloat(hex & 0xff) / 255, alpha: a)
}

// Tile
let tile = CGRect(x: 100, y: 100, width: 824, height: 824)
let tilePath = CGPath(roundedRect: tile, cornerWidth: 186, cornerHeight: 186, transform: nil)
ctx.saveGState()
ctx.setShadow(offset: CGSize(width: 0, height: 12), blur: 28, color: rgb(0x000000, 0.35))
ctx.addPath(tilePath)
ctx.setFillColor(rgb(0x0b0c0d))
ctx.fillPath()
ctx.restoreGState()
// a faint top light so it reads as a surface, not a hole
ctx.saveGState()
ctx.addPath(tilePath)
ctx.clip()
let grad = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: [rgb(0x26292c), rgb(0x0b0c0d)] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(grad, start: CGPoint(x: 512, y: 100), end: CGPoint(x: 512, y: 640), options: [])
ctx.restoreGState()
ctx.addPath(CGPath(roundedRect: tile.insetBy(dx: 2, dy: 2), cornerWidth: 184, cornerHeight: 184, transform: nil))
ctx.setStrokeColor(rgb(0xffffff, 0.10))
ctx.setLineWidth(4)
ctx.strokePath()

// Mark: path M6 6H44L58 20V58H20L6 44Z (52 units) centred, about 56% of the tile
let unit: CGFloat = 8.8
let origin = CGPoint(x: 512 - 26 * unit, y: 512 - 26 * unit)
func p(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x: origin.x + (x - 6) * unit, y: origin.y + (y - 6) * unit) }
let mark = CGMutablePath()
mark.move(to: p(6, 6)); mark.addLine(to: p(44, 6)); mark.addLine(to: p(58, 20))
mark.addLine(to: p(58, 58)); mark.addLine(to: p(20, 58)); mark.addLine(to: p(6, 44)); mark.closeSubpath()
ctx.addPath(mark)
ctx.setStrokeColor(rgb(0xece8df))
ctx.setLineWidth(6 * unit)
ctx.setLineJoin(.miter)
ctx.strokePath()
ctx.setFillColor(rgb(0xff6a1a))
ctx.fill(CGRect(origin: p(24, 24), size: CGSize(width: 16 * unit, height: 16 * unit)))

NSGraphicsContext.restoreGraphicsState()
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: out))
print("Icon: \(out)")
