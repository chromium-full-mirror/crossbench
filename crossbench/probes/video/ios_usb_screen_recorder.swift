// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Records the screen of a physical iOS device over USB into an H.264 MP4.
//
// Compiled and run on the host by crossbench's video probe
// (crossbench/probes/video/video.py):
//
//   ios_usb_screen_recorder DEVICE_NAME OUTPUT.mp4 FRAME_RATE
//
// DEVICE_NAME is the device's name as shown by devicectl (the capture device
// is published under it; its unique ID is unrelated to the UDID). The program
// prints READY once the first frame has been written and records until its
// stdin is closed or it receives SIGINT/SIGTERM. Needs macOS 14.
//
// Only the device's video port is connected. Frames are timestamped with the
// host clock relative to the first frame and snapped to the frame-rate grid,
// so the file is constant-rate with the odd frame missing rather than
// carrying the USB capture timestamps, whose discontinuities shorten a
// recording.

import AVFoundation
import CoreMedia
import CoreMediaIO
import CoreVideo
import Foundation

let deviceDiscoveryTimeout: TimeInterval = 10
let firstFrameTimeout: TimeInterval = 10

func fail(_ message: String) -> Never {
  FileHandle.standardError.write(Data("\(message)\n".utf8))
  exit(1)
}

/// Lets macOS expose connected iOS devices as capture devices.
///
/// Until a process sets this (per-process) CoreMediaIO property, AVFoundation
/// does not list iOS devices at all; it is what QuickTime Player flips when
/// an iPhone is picked for a movie recording. There is no nicer API for it:
/// CoreMediaIO's device layer is a C API in the style of Core Audio, so the
/// property is addressed by a selector/scope/element struct and both it and
/// the value are passed by pointer, with the value's size alongside.
func allowScreenCaptureDevices() {
  var address = CMIOObjectPropertyAddress(
    mSelector: CMIOObjectPropertySelector(
      kCMIOHardwarePropertyAllowScreenCaptureDevices),
    mScope: CMIOObjectPropertyScope(kCMIOObjectPropertyScopeGlobal),
    mElement: CMIOObjectPropertyElement(kCMIOObjectPropertyElementMain))
  var value: UInt32 = 1  // True.
  let status = CMIOObjectSetPropertyData(
    CMIOObjectID(kCMIOObjectSystemObject), &address, 0, nil,
    UInt32(MemoryLayout.size(ofValue: value)), &value)
  if status != kCMIOHardwareNoError {
    fail("Cannot enable screen capture devices (CoreMediaIO status \(status))")
  }
}

/// Returns the capture device of the iOS device called `name`.
///
/// macOS publishes a connected iOS device as a capture device carrying the
/// device's name. Publication is asynchronous: it starts when screen
/// capture devices are allowed and takes anywhere from a fraction of a
/// second to several seconds (longer right after another process released
/// the device), so the device is polled for until the deadline. Fails if
/// it does not show up in time.
func findCaptureDevice(named name: String) -> AVCaptureDevice {
  let deadline = Date(timeIntervalSinceNow: deviceDiscoveryTimeout)
  var devices: [AVCaptureDevice] = []
  repeat {
    // A mirrored iOS device is an external device with muxed (video and
    // audio) media; neither a camera nor a plain video device.
    devices = AVCaptureDevice.DiscoverySession(
      deviceTypes: [.external], mediaType: .muxed,
      position: .unspecified).devices
    if let device = devices.first(where: { $0.localizedName == name }) {
      return device
    }
    RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.1))
  } while Date() < deadline
  let names = devices.map { $0.localizedName }
  fail("No screen capture device named '\(name)'; found: \(names)")
}

/// Writes the captured frames to an MP4, timestamped on the frame grid.
class FrameWriter: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate {
  let outputURL: URL
  /// Frame timestamps snap to this grid.
  let frameRate: CMTimeScale
  /// Signalled once the first frame has been written.
  let ready = DispatchSemaphore(value: 0)

  /// The file being written, set up on the first frame.
  private struct Sink {
    let writer: AVAssetWriter
    let input: AVAssetWriterInput
    let adaptor: AVAssetWriterInputPixelBufferAdaptor
    let firstFrameTime: CMTime
  }

  private var sink: Sink?
  private var lastFrame: CVPixelBuffer?
  private var lastPresentationTime: CMTime = .zero
  private var droppedFrames = 0
  private var stopped = false

  init(outputURL: URL, frameRate: CMTimeScale) {
    self.outputURL = outputURL
    self.frameRate = frameRate
  }

  func captureOutput(_ output: AVCaptureOutput,
                     didOutput sampleBuffer: CMSampleBuffer,
                     from connection: AVCaptureConnection) {
    if stopped { return }
    guard let frame = sampleBuffer.imageBuffer else { return }
    // The host clock, not the buffer's USB capture timestamp (see the
    // header).
    let now = CMClockGetHostTimeClock().time
    let sink = self.sink ?? startWriting(firstFrame: frame, at: now)
    let presentationTime = (now - sink.firstFrameTime).convertScale(
      frameRate, method: .roundHalfAwayFromZero)
    // At most one frame per grid slot.
    guard lastFrame == nil || presentationTime > lastPresentationTime else {
      return
    }
    guard sink.input.isReadyForMoreMediaData,
          sink.adaptor.append(frame, withPresentationTime: presentationTime)
    else {
      droppedFrames += 1
      return
    }
    lastPresentationTime = presentationTime
    lastFrame = frame
  }

  /// Sets up the writer for the dimensions of the first frame.
  private func startWriting(firstFrame: CVPixelBuffer,
                            at time: CMTime) -> Sink {
    let width = CVPixelBufferGetWidth(firstFrame)
    let height = CVPixelBufferGetHeight(firstFrame)
    let writer: AVAssetWriter
    do {
      writer = try AVAssetWriter(outputURL: outputURL, fileType: .mp4)
    } catch {
      fail("Cannot write \(outputURL.path): \(error)")
    }
    let input = AVAssetWriterInput(
      mediaType: .video,
      outputSettings: [
        AVVideoCodecKey: AVVideoCodecType.h264,
        AVVideoWidthKey: width,
        AVVideoHeightKey: height,
      ])
    input.expectsMediaDataInRealTime = true
    let adaptor = AVAssetWriterInputPixelBufferAdaptor(
      assetWriterInput: input,
      sourcePixelBufferAttributes: [
        kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
        kCVPixelBufferWidthKey as String: width,
        kCVPixelBufferHeightKey as String: height,
      ])
    writer.add(input)
    guard writer.startWriting() else {
      fail("Cannot start writing \(outputURL.path): \(describe(writer))")
    }
    writer.startSession(atSourceTime: .zero)
    let sink = Sink(
      writer: writer, input: input, adaptor: adaptor, firstFrameTime: time)
    self.sink = sink
    // Unbuffered, so the probe sees it right away.
    FileHandle.standardOutput.write(Data("READY\n".utf8))
    ready.signal()
    return sink
  }

  /// Stops taking frames and finishes the file; calls `completion` when done.
  /// Fails the program if the file could not be written.
  func finish(completion: @escaping () -> Void) {
    if stopped { return }
    stopped = true
    guard let sink = sink else {
      completion()
      return
    }
    // Repeat the last frame at the stop time so the file runs to the end.
    let now = CMClockGetHostTimeClock().time
    let endTime = (now - sink.firstFrameTime).convertScale(
      frameRate, method: .roundHalfAwayFromZero)
    if let frame = lastFrame, endTime > lastPresentationTime,
       sink.input.isReadyForMoreMediaData {
      _ = sink.adaptor.append(frame, withPresentationTime: endTime)
    }
    sink.input.markAsFinished()
    let droppedFrames = self.droppedFrames
    sink.writer.finishWriting {
      if sink.writer.status != .completed {
        fail("Writing \(sink.writer.outputURL.path) failed: "
             + describe(sink.writer))
      }
      if droppedFrames > 0 {
        let note = "Dropped \(droppedFrames) frames: writer was not ready"
        FileHandle.standardError.write(Data("\(note)\n".utf8))
      }
      completion()
    }
  }

}

/// The writer's error, or its status when it has none.
func describe(_ writer: AVAssetWriter) -> String {
  return writer.error.map { "\($0)" } ?? "status \(writer.status.rawValue)"
}

/// A capture session delivering the device's video frames (and nothing else)
/// to `frameWriter` on `queue`.
func makeSession(device: AVCaptureDevice, frameWriter: FrameWriter,
                 queue: DispatchQueue) throws -> AVCaptureSession {
  let session = AVCaptureSession()
  session.sessionPreset = .high
  let input = try AVCaptureDeviceInput(device: device)
  for port in input.ports where port.mediaType != .video {
    port.isEnabled = false
  }
  guard let videoPort = input.ports.first(where: { $0.mediaType == .video })
  else {
    fail("The iOS USB screen capture device has no video port")
  }
  let output = AVCaptureVideoDataOutput()
  output.videoSettings = [
    kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA
  ]
  output.setSampleBufferDelegate(frameWriter, queue: queue)
  session.addInputWithNoConnections(input)
  session.addOutputWithNoConnections(output)
  session.addConnection(
    AVCaptureConnection(inputPorts: [videoPort], output: output))
  return session
}

/// Finishes the recording when the process is asked to stop, whether by
/// its stdin closing (how the probe stops it) or by a signal (Ctrl-C), so
/// that the file is playable either way.
func finishOnStop(frameWriter: FrameWriter, queue: DispatchQueue,
                  completion: @escaping () -> Void) -> [DispatchSourceSignal] {
  let finish = { queue.async { frameWriter.finish(completion: completion) } }
  let signals = [SIGINT, SIGTERM].map { number -> DispatchSourceSignal in
    signal(number, SIG_IGN)
    let source = DispatchSource.makeSignalSource(signal: number, queue: queue)
    source.setEventHandler(handler: finish)
    source.resume()
    return source
  }
  DispatchQueue.global().async {
    _ = FileHandle.standardInput.readDataToEndOfFile()
    finish()
  }
  return signals
}

func main() {
  let arguments = CommandLine.arguments
  guard arguments.count == 4, let frameRate = CMTimeScale(arguments[3]) else {
    fail("Usage: \(arguments[0]) DEVICE_NAME OUTPUT.mp4 FRAME_RATE")
  }
  let deviceName = arguments[1]
  let outputPath = arguments[2]

  allowScreenCaptureDevices()
  let device = findCaptureDevice(named: deviceName)
  let outputURL = URL(fileURLWithPath: outputPath)
  // Leftovers of an earlier run; "no such file" is the expected error.
  try? FileManager.default.removeItem(at: outputURL)
  let frameWriter = FrameWriter(outputURL: outputURL, frameRate: frameRate)
  let frameQueue = DispatchQueue(label: "crossbench.video.recorder")
  let session: AVCaptureSession
  do {
    session = try makeSession(
      device: device, frameWriter: frameWriter, queue: frameQueue)
  } catch {
    fail("Cannot capture from \(device.localizedName): \(error)")
  }

  let finished = DispatchSemaphore(value: 0)
  let signalSources = finishOnStop(
    frameWriter: frameWriter, queue: frameQueue) { finished.signal() }
  session.startRunning()
  if frameWriter.ready.wait(timeout: .now() + firstFrameTimeout) == .timedOut {
    fail("No frames from \(device.localizedName) within \(firstFrameTimeout) s "
         + "(is the device unlocked and trusted?)")
  }
  finished.wait()
  session.stopRunning()
  withExtendedLifetime(signalSources) {}
}

main()
