import SwiftUI
import ARKit
import SceneKit
import CoreImage
import ZIPFoundation

@main
struct FloorCopyApp: App {
    @StateObject private var scanner = Scanner()
    var body: some Scene {
        WindowGroup { CaptureScreen(scanner: scanner) }
    }
}

struct CaptureScreen: View {
    @ObservedObject var scanner: Scanner
    @State private var share = false
    var body: some View {
        ZStack(alignment: .bottom) {
            CameraView(scanner: scanner).ignoresSafeArea()
            VStack(spacing: 12) {
                Text("Floor Copy").font(.title2.bold())
                Text(scanner.status).font(.subheadline)
                Text("Кадров: \(scanner.frames) • \(scanner.tracking)").font(.caption)
                Text("Снимай небольшой участок с перекрытием. Двигайся медленно, обходи стены и проёмы. При потере отслеживания закончи участок.")
                    .font(.caption).multilineTextAlignment(.center)
                HStack {
                    Button(scanner.recording ? "Завершить" : "Новый участок") {
                        if scanner.recording { scanner.finish() } else { scanner.start() }
                    }.buttonStyle(.borderedProminent).disabled(scanner.busy || !scanner.supported)
                    if scanner.archive != nil {
                        Button("Экспорт ZIP") { share = true }.buttonStyle(.bordered).disabled(scanner.busy)
                    }
                }
                Text("Точность не подтверждена. Сохраняй контрольные замеры отдельно.").font(.caption2)
            }.padding().frame(maxWidth: .infinity).background(.ultraThinMaterial)
        }
        .sheet(isPresented: $share) {
            if let url = scanner.archive { ShareSheet(url: url) }
        }
    }
}

struct CameraView: UIViewRepresentable {
    let scanner: Scanner
    func makeUIView(context: Context) -> ARSCNView {
        let view = ARSCNView()
        view.session = scanner.session
        view.scene = SCNScene()
        view.automaticallyUpdatesLighting = true
        return view
    }
    func updateUIView(_ uiView: ARSCNView, context: Context) {}
}

struct ShareSheet: UIViewControllerRepresentable {
    let url: URL
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: [url], applicationActivities: nil)
    }
    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}

final class Scanner: NSObject, ObservableObject, ARSessionDelegate {
    @Published var status = "Нажми «Новый участок», чтобы начать"
    @Published var frames = 0
    @Published var tracking = "ожидание"
    @Published var recording = false
    @Published var busy = false
    @Published var archive: URL?
    let session = ARSession()
    let supported = ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth)
        && ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh)
    private let queue = DispatchQueue(label: "org.floorcopy.capture")
    private let ci = CIContext()
    private var folder: URL?
    private var index = 0
    private var lastTime: TimeInterval = -100
    private var active = false
    private var events: [[String: Any]] = []
    private var meshes: [UUID: ARMeshAnchor] = [:]
    private var startTime: TimeInterval = 0
    private let maximumFrames = 240

    override init() {
        super.init()
        session.delegate = self
        session.delegateQueue = queue
        if !supported { status = "Нужен iPhone с LiDAR и поддержкой ARKit" }
    }

    func start() {
        guard supported, !busy, !recording else { return }
        busy = true
        queue.async {
            do {
                let root = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
                let url = root.appendingPathComponent("scan-" + UUID().uuidString)
                try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
                self.folder = url
                self.index = 0
                self.lastTime = -100
                self.startTime = 0
                self.events = []
                self.meshes = [:]
                self.active = true
                let config = ARWorldTrackingConfiguration()
                config.frameSemantics = [.sceneDepth]
                config.sceneReconstruction = .mesh
                config.planeDetection = [.horizontal, .vertical]
                self.session.run(config, options: [.resetTracking, .removeExistingAnchors])
                DispatchQueue.main.async {
                    self.frames = 0
                    self.archive = nil
                    self.recording = true
                    self.busy = false
                    self.status = "Идёт запись. Небольшие участки до 3 минут."
                    UIApplication.shared.isIdleTimerDisabled = true
                }
            } catch { self.fail(error) }
        }
    }

    func finish() {
        guard recording, !busy else { return }
        busy = true
        queue.async { self.complete() }
    }

    private func complete() {
        guard active, let folder = folder else { return }
        active = false
        session.pause()
        DispatchQueue.main.async {
            self.recording = false
            self.busy = true
            self.status = "Сохраняю измерения и архив…"
            UIApplication.shared.isIdleTimerDisabled = false
        }
        do {
            let manifest: [String: Any] = [
                "format": "floorcopy-rgbd", "version": 1, "frames": index,
                "depth": "float32_le_meters", "pose": "column_major_camera_to_world",
                "cameraAxes": "x_right_y_up_z_back", "imageOrientation": "sensor_native",
                "events": events, "accuracyVerified": false,
                "created": ISO8601DateFormatter().string(from: Date())
            ]
            try JSONSerialization.data(withJSONObject: manifest, options: [.prettyPrinted, .sortedKeys])
                .write(to: folder.appendingPathComponent("manifest.json"))
            try saveMesh(to: folder.appendingPathComponent("mesh.ply"))
            let zip = folder.appendingPathExtension("zip")
            try FileManager.default.zipItem(at: folder, to: zip, shouldKeepParent: false)
            DispatchQueue.main.async {
                self.archive = zip
                self.busy = false
                self.status = self.index > 0 ? "Участок сохранён. Экспортируй ZIP на компьютер." : "Нет кадров с надёжным отслеживанием. Повтори съёмку."
            }
        } catch { fail(error) }
    }

    private func fail(_ error: Error) {
        active = false
        session.pause()
        DispatchQueue.main.async {
            self.status = "Ошибка: " + error.localizedDescription
            self.busy = false
            self.recording = false
            UIApplication.shared.isIdleTimerDisabled = false
        }
    }

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        guard active else { return }
        let label: String
        switch frame.camera.trackingState {
        case .normal: label = "отслеживание хорошее"
        case .notAvailable: label = "отслеживание недоступно"
        case .limited: label = "остановись: отслеживание нестабильно"
        }
        DispatchQueue.main.async { self.tracking = label }
        guard case .normal = frame.camera.trackingState else { return }
        guard frame.timestamp - lastTime >= 0.75,
              let depth = frame.sceneDepth, let folder = folder else { return }
        if index >= maximumFrames { complete(); return }
        do {
            if startTime == 0 { startTime = frame.timestamp }
            let name = String(format: "%05d", index)
            let map = depth.depthMap
            let width = CVPixelBufferGetWidth(map), height = CVPixelBufferGetHeight(map)
            CVPixelBufferLockBaseAddress(map, .readOnly)
            var bytes = Data()
            if let base = CVPixelBufferGetBaseAddress(map) {
                let row = CVPixelBufferGetBytesPerRow(map)
                for y in 0..<height { bytes.append(base.advanced(by: y * row).assumingMemoryBound(to: UInt8.self), count: width * 4) }
            }
            CVPixelBufferUnlockBaseAddress(map, .readOnly)
            guard bytes.count == width * height * 4 else { throw CaptureError.invalidBuffer }
            try bytes.write(to: folder.appendingPathComponent(name + ".depth"))
            if let confidence = depth.confidenceMap {
                CVPixelBufferLockBaseAddress(confidence, .readOnly)
                var conf = Data()
                if let base = CVPixelBufferGetBaseAddress(confidence) {
                    for y in 0..<height {
                        conf.append(base.advanced(by: y * CVPixelBufferGetBytesPerRow(confidence)).assumingMemoryBound(to: UInt8.self), count: width)
                    }
                }
                CVPixelBufferUnlockBaseAddress(confidence, .readOnly)
                try conf.write(to: folder.appendingPathComponent(name + ".confidence"))
            }
            let image = CIImage(cvPixelBuffer: frame.capturedImage)
            guard let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
                  let jpg = ci.jpegRepresentation(of: image, colorSpace: colorSpace, options: [:])
            else { throw CaptureError.invalidBuffer }
            try jpg.write(to: folder.appendingPathComponent(name + ".jpg"))
            let meta: [String: Any] = [
                "timestamp": frame.timestamp - startTime,
                "depthWidth": width, "depthHeight": height,
                "imageWidth": CVPixelBufferGetWidth(frame.capturedImage),
                "imageHeight": CVPixelBufferGetHeight(frame.capturedImage),
                "intrinsics": flatten(frame.camera.intrinsics),
                "transform": flatten(frame.camera.transform), "tracking": "normal"
            ]
            try JSONSerialization.data(withJSONObject: meta).write(to: folder.appendingPathComponent(name + ".json"))
            lastTime = frame.timestamp
            index += 1
            DispatchQueue.main.async { self.frames = self.index }
        } catch { fail(error) }
    }

    func session(_ session: ARSession, didAdd anchors: [ARAnchor]) { updateMeshes(anchors) }
    func session(_ session: ARSession, didUpdate anchors: [ARAnchor]) { updateMeshes(anchors) }
    func session(_ session: ARSession, didRemove anchors: [ARAnchor]) {
        for anchor in anchors { meshes.removeValue(forKey: anchor.identifier) }
    }
    private func updateMeshes(_ anchors: [ARAnchor]) {
        guard active else { return }
        for anchor in anchors {
            if let mesh = anchor as? ARMeshAnchor { meshes[mesh.identifier] = mesh }
        }
    }
    func sessionWasInterrupted(_ session: ARSession) {
        guard active else { return }
        events.append(["type": "interruption", "afterFrame": index])
        complete()
    }
    func session(_ session: ARSession, didFailWithError error: Error) { fail(error) }

    private func saveMesh(to url: URL) throws {
        var vertices: [String] = [], faces: [String] = []
        for anchor in meshes.values {
            let geometry = anchor.geometry, offset = vertices.count
            for i in 0..<geometry.vertices.count {
                let pointer = geometry.vertices.buffer.contents().advanced(by: geometry.vertices.offset + geometry.vertices.stride * i)
                let xyz = pointer.assumingMemoryBound(to: Float.self)
                let p = anchor.transform * SIMD4<Float>(xyz[0], xyz[1], xyz[2], 1)
                vertices.append("\(p.x) \(p.y) \(p.z)")
            }
            let element = geometry.faces
            guard element.indexCountPerPrimitive == 3 else { continue }
            for i in 0..<element.count {
                var indices: [Int] = []
                for j in 0..<3 {
                    let pointer = element.buffer.contents().advanced(by: (i * 3 + j) * element.bytesPerIndex)
                    let value: Int
                    if element.bytesPerIndex == 4 { value = Int(pointer.load(as: UInt32.self)) }
                    else { value = Int(pointer.load(as: UInt16.self)) }
                    indices.append(offset + value)
                }
                faces.append("3 \(indices[0]) \(indices[1]) \(indices[2])")
            }
        }
        let header = "ply\nformat ascii 1.0\nelement vertex \(vertices.count)\nproperty float x\nproperty float y\nproperty float z\nelement face \(faces.count)\nproperty list uchar int vertex_indices\nend_header\n"
        try (header + vertices.joined(separator: "\n") + "\n" + faces.joined(separator: "\n") + "\n").write(to: url, atomically: true, encoding: .utf8)
    }
    private func flatten(_ m: simd_float3x3) -> [Float] {
        (0..<3).flatMap { c in (0..<3).map { r in m[c][r] } }
    }
    private func flatten(_ m: simd_float4x4) -> [Float] {
        (0..<4).flatMap { c in (0..<4).map { r in m[c][r] } }
    }
    enum CaptureError: Error { case invalidBuffer }
}
