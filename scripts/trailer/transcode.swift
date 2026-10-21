// transcode <in> <out> <width> <height> <videoBitrate>: H.264 High + AAC, fast start.
import AVFoundation
let a = CommandLine.arguments
let asset = AVURLAsset(url: URL(fileURLWithPath: a[1]))
let out = URL(fileURLWithPath: a[2]); try? FileManager.default.removeItem(at: out)
let W = Int(a[3])!, H = Int(a[4])!, BR = Int(a[5])!
let reader = try AVAssetReader(asset: asset)
let writer = try AVAssetWriter(outputURL: out, fileType: .mp4)
writer.shouldOptimizeForNetworkUse = true
let vt = asset.tracks(withMediaType: .video)[0]
let vr = AVAssetReaderTrackOutput(track: vt, outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange])
reader.add(vr)
let vw = AVAssetWriterInput(mediaType: .video, outputSettings: [AVVideoCodecKey: AVVideoCodecType.h264, AVVideoWidthKey: W, AVVideoHeightKey: H,
  AVVideoScalingModeKey: AVVideoScalingModeResizeAspect,
  AVVideoCompressionPropertiesKey: [AVVideoAverageBitRateKey: BR, AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel, AVVideoMaxKeyFrameIntervalKey: 120, AVVideoAllowFrameReorderingKey: true]])
vw.expectsMediaDataInRealTime = false
writer.add(vw)
var pairs: [(AVAssetReaderOutput, AVAssetWriterInput)] = [(vr, vw)]
if let at = asset.tracks(withMediaType: .audio).first {
  let ar = AVAssetReaderTrackOutput(track: at, outputSettings: [AVFormatIDKey: kAudioFormatLinearPCM])
  reader.add(ar)
  let aw = AVAssetWriterInput(mediaType: .audio, outputSettings: [AVFormatIDKey: kAudioFormatMPEG4AAC, AVNumberOfChannelsKey: 2, AVSampleRateKey: 48000, AVEncoderBitRateKey: 128000])
  writer.add(aw); pairs.append((ar, aw))
}
reader.startReading(); writer.startWriting(); writer.startSession(atSourceTime: .zero)
let g = DispatchGroup()
for (i, (r, w)) in pairs.enumerated() {
  g.enter()
  w.requestMediaDataWhenReady(on: DispatchQueue(label: "q\(i)")) {
    while w.isReadyForMoreMediaData {
      if let s = r.copyNextSampleBuffer() { w.append(s) } else { w.markAsFinished(); g.leave(); return }
    }
  }
}
g.wait()
let sem = DispatchSemaphore(value: 0)
writer.finishWriting { sem.signal() }; sem.wait()
if writer.status != .completed { print("failed", writer.error ?? ""); exit(1) }
print("ok")
