// poster <in.mp4> <seconds> <out.png>: one exact frame of the trailer, for the hero poster.
import AVFoundation
import AppKit
let a = CommandLine.arguments
let asset = AVURLAsset(url: URL(fileURLWithPath: a[1]))
let gen = AVAssetImageGenerator(asset: asset)
gen.appliesPreferredTrackTransform = true
gen.requestedTimeToleranceBefore = .zero; gen.requestedTimeToleranceAfter = .zero
let cg = try gen.copyCGImage(at: CMTime(seconds: Double(a[2])!, preferredTimescale: 600), actualTime: nil)
let rep = NSBitmapImageRep(cgImage: cg)
try rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: a[3]))
