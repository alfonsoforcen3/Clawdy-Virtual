import AppKit
import QuartzCore
import Foundation
import Darwin

// Private prototype renderer. Compile with Shared.swift; stdin is the only input.
// Contract: ParentMessage(type: snapshot/preferences/ping), main-queue ChildMessage pong.
// Artwork uses the Clawdy Pro Max website mockup.

private let rendererSize = NSSize(width: 346, height: 68)
private let rendererExpandedSize = NSSize(width: 346, height: 96)

private func presentationSize(_ state: ClawdyState, paused: Bool = false, moveMode: Bool = false) -> NSSize {
    moveMode || (!paused && (state == .attention || state == .error)) ? rendererExpandedSize : rendererSize
}

private func topCenteredFrame(_ size: NSSize, area: NSRect, safeTop: CGFloat? = nil) -> NSRect {
    let top = max(area.minY,min(area.maxY,safeTop ?? area.maxY)-6)
    // If a work area is unusually short, shrink below the safe top rather than
    // clamping a full-height panel upward into the menu/camera exclusion area.
    let usable = NSRect(x:area.minX,y:area.minY,width:area.width,height:top-area.minY)
    return clampedFrame(NSRect(x:area.midX-size.width/2,y:top-size.height,width:size.width,height:size.height),workAreas:[usable])
}
private func workingLabel(_ count: Int) -> String { "\(count) WIP" }
private let providerNames = ["codex": "Codex", "claude": "Claude", "gemini": "Gemini", "cursor": "Cursor", "unknown": "Other", "other": "Other"]

private func validSnapshot(_ snapshot: ClawdySnapshot) -> Bool {
    do { try snapshot.validate(); return true } catch { return false }
}

// Positive or negative screen origins are legal. The panel always fits a visible
// work area, falling back to the nearest screen when an attached monitor vanishes.
private func clampedFrame(_ proposed: NSRect, workAreas: [NSRect]) -> NSRect {
    guard !workAreas.isEmpty else { return proposed }
    func overlap(_ rect: NSRect) -> CGFloat {
        let area = proposed.intersection(rect)
        return area.isNull ? 0 : area.width * area.height
    }
    let center = NSPoint(x: proposed.midX, y: proposed.midY)
    func distance(_ rect: NSRect) -> CGFloat {
        let dx = max(rect.minX - center.x, 0, center.x - rect.maxX)
        let dy = max(rect.minY - center.y, 0, center.y - rect.maxY)
        return dx * dx + dy * dy
    }
    let target = workAreas.max {
        let a = overlap($0), b = overlap($1)
        return a == b ? distance($0) > distance($1) : a < b
    }!
    let width = min(proposed.width, target.width), height = min(proposed.height, target.height)
    return NSRect(x: min(max(proposed.minX, target.minX), target.maxX - width),
                  y: min(max(proposed.minY, target.minY), target.maxY - height), width: width, height: height)
}

private extension NSColor {
    static func rgb(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat, _ a: CGFloat = 1) -> NSColor {
        NSColor(srgbRed: r / 255, green: g / 255, blue: b / 255, alpha: a)
    }
    func mixed(with other: NSColor, amount: CGFloat) -> NSColor {
        blended(withFraction: min(1, max(0, amount)), of: other) ?? self
    }
}

private struct StateStyle {
    let title: String
    let phrase: String
    static func forState(_ state: ClawdyState) -> StateStyle {
        switch state {
        case .idle: return StateStyle(title: "All quiet", phrase: "A little quiet. A little Clawdy.")
        case .working: return StateStyle(title: "Working", phrase: "A few things are taking shape.")
        case .ready: return StateStyle(title: "Ready", phrase: "Your next move.")
        case .attention: return StateStyle(title: "Your input", phrase: "A small nudge is needed.")
        case .error: return StateStyle(title: "Needs a look", phrase: "Something needs a little care.")
        case .disconnected: return StateStyle(title: "Disconnected", phrase: "Waiting for a fresh signal.")
        case .uncertain: return StateStyle(title: "Unconfirmed", phrase: "Last report. Current status unknown.")
        }
    }
}

private final class ClawdyCanvas: NSView {
    var snapshot = ClawdySnapshot(version: 1, instance_id: "renderer-start", revision: 0,
                                  state: .disconnected, working_count: 0, providers: [], demo: false, phrase: "")
    var paused = false
    var reducedMotion = false
    var moveMode = false
    var providerRotationIndex = 0
    var providerLabels: [String] {
        snapshot.providers.compactMap { providerNames[$0] }.reduce(into:[]) { labels, name in
            if !labels.contains(name) { labels.append(name) }
        }
    }
    var displayedProvider: String? {
        let names = providerLabels
        return names.isEmpty ? nil : names[providerRotationIndex % names.count]
    }
    private var dark: Bool { effectiveAppearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua }
    override var isOpaque: Bool { false }
    override var acceptsFirstResponder: Bool { false }

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        layerContentsRedrawPolicy = .onSetNeedsDisplay
        layer?.backgroundColor = NSColor.clear.cgColor
        setAccessibilityElement(true)
        setAccessibilityRole(.image)
        updateAccessibility()
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    func updateAccessibility() {
        let state = paused ? "Paused" : StateStyle.forState(snapshot.state).title
        let providers = snapshot.providers.compactMap { providerNames[$0] }.joined(separator: ", ")
        setAccessibilityLabel("Clawdy. \(state). \(snapshot.working_count) reported in progress. \(providers). \(snapshot.demo ? "Demo data." : "Read-only status.")")
        setAccessibilityHelp(moveMode ? "Move mode. Drag this capsule to reposition it. Use the menu bar to finish moving." : "Click-through status capsule below the camera. Controls are in the menu bar.")
    }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { moveMode }
    override func mouseDown(with event: NSEvent) { if moveMode { window?.performDrag(with: event) } }
    override func viewDidChangeEffectiveAppearance() {
        super.viewDidChangeEffectiveAppearance(); needsDisplay = true
    }
    private func polygon(_ points: [NSPoint]) -> NSBezierPath {
        let path = NSBezierPath()
        if let first = points.first {
            path.move(to: first)
            for p in points.dropFirst() { path.line(to: p) }
            path.close()
        }
        return path
    }
    private func fill(_ path: NSBezierPath, _ color: NSColor) { color.setFill(); path.fill() }
    private func rounded(_ rect: NSRect, _ radius: CGFloat) -> NSBezierPath { NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius) }
    private func text(_ value: String, _ rect: NSRect, size: CGFloat, weight: NSFont.Weight = .medium, color: NSColor, alignment: NSTextAlignment = .left) {
        let paragraph = NSMutableParagraphStyle(); paragraph.alignment = alignment; paragraph.lineBreakMode = .byTruncatingTail
        (value as NSString).draw(in: rect, withAttributes: [.font: NSFont.systemFont(ofSize: size, weight: weight), .foregroundColor: color, .paragraphStyle: paragraph])
    }
    // These fixed vector paths match the Windows pill. SVG coordinates use a downward Y axis.
    private static let providerMarks = [
        "Codex": vectorMark("M 13.2,20 C 12.67,20 12.16,19.9 11.68,19.7 C 11.2,19.49 10.78,19.21 10.4,18.85 C 10,18.99 9.58,19.06 9.14,19.06 C 8.43,19.06 7.76,18.88 7.16,18.53 C 6.55,18.18 6.06,17.7 5.68,17.09 C 5.32,16.48 5.14,15.8 5.14,15.06 C 5.14,14.75 5.18,14.41 5.27,14.05 C 4.84,13.65 4.51,13.2 4.28,12.69 C 4.04,12.17 3.92,11.62 3.92,11.06 C 3.92,10.48 4.05,9.93 4.29,9.39 C 4.54,8.86 4.88,8.4 5.32,8.02 C 5.76,7.62 6.28,7.35 6.87,7.2 C 6.99,6.59 7.23,6.05 7.6,5.57 C 7.99,5.08 8.46,4.69 9.01,4.42 C 9.57,4.14 10.16,4 10.79,4 C 11.32,4 11.83,4.1 12.31,4.3 C 12.79,4.51 13.21,4.79 13.59,5.15 C 13.99,5.01 14.41,4.94 14.85,4.94 C 15.57,4.94 16.23,5.12 16.84,5.47 C 17.44,5.82 17.93,6.3 18.29,6.91 C 18.67,7.52 18.85,8.2 18.85,8.94 C 18.85,9.25 18.81,9.59 18.72,9.95 C 19.15,10.35 19.48,10.81 19.72,11.33 C 19.95,11.84 20.07,12.38 20.07,12.94 C 20.07,13.52 19.95,14.07 19.7,14.61 C 19.45,15.14 19.11,15.61 18.66,16 C 18.22,16.38 17.71,16.65 17.12,16.8 C 17.01,17.41 16.76,17.95 16.37,18.43 C 16,18.92 15.53,19.31 14.98,19.58 C 14.43,19.86 13.83,20 13.2,20 Z " +
            "M 9.28,17.82 C 9.79,17.82 10.23,17.71 10.61,17.49 L 13.51,15.82 C 13.63,15.75 13.68,15.65 13.68,15.52 V 14.4 L 10.12,16.45 C 9.79,16.64 9.45,16.64 9.12,16.45 L 6.37,14.86 C 6.37,14.93 6.37,14.99 6.37,15.06 C 6.37,15.51 6.49,15.99 6.74,16.43 C 7,16.86 7.35,17.19 7.8,17.44 C 8.24,17.7 8.74,17.82 9.28,17.82 Z " +
            "M 9.43,15.22 C 9.55,15.27 9.66,15.27 9.78,15.22 L 10.76,14.67 L 7.2,12.59 C 6.87,12.41 6.71,12.12 6.71,11.73 V 8.58 C 6.24,8.82 5.87,9.17 5.59,9.62 C 5.32,10.05 5.19,10.54 5.19,11.07 C 5.19,11.57 5.31,12.05 5.56,12.51 C 5.81,12.96 6.14,13.3 6.55,13.54 L 9.43,15.22 Z " +
            "M 13.19,18.75 C 13.73,18.75 14.22,18.63 14.66,18.38 C 15.1,18.14 15.44,17.8 15.68,17.38 C 15.94,16.95 16.07,16.47 16.07,15.95 V 12.62 C 16.07,12.49 16.01,12.38 15.89,12.32 L 14.92,11.73 V 15.86 C 14.92,16.25 14.75,16.54 14.42,16.72 L 11.68,18.3 C 12.15,18.6 12.65,18.75 13.19,18.75 Z " +
            "M 13.68,13.01 V 10.99 L 12,10.03 L 10.31,10.99 V 13.01 L 12,13.97 L 13.68,13.01 Z " +
            "M 9.08,8.14 C 9.08,7.75 9.24,7.46 9.57,7.28 L 12.31,5.7 C 11.84,5.4 11.34,5.25 10.8,5.25 C 10.27,5.25 9.79,5.37 9.35,5.62 C 8.91,5.86 8.56,6.2 8.31,6.62 C 8.06,7.05 7.94,7.53 7.94,8.05 V 11.36 C 7.94,11.49 8,11.59 8.12,11.68 L 9.08,12.27 V 8.14 Z " +
            "M 17.3,15.42 C 17.76,15.19 18.12,14.85 18.39,14.4 C 18.67,13.95 18.8,13.46 18.8,12.93 C 18.8,12.43 18.68,11.95 18.42,11.5 C 18.17,11.05 17.85,10.7 17.44,10.46 L 14.56,8.8 C 14.44,8.74 14.33,8.74 14.21,8.8 L 13.24,9.33 L 16.8,11.42 C 16.97,11.52 17.1,11.64 17.17,11.78 C 17.26,11.9 17.3,12.07 17.3,12.27 V 15.42 Z " +
            "M 13.88,7.52 C 14.21,7.32 14.54,7.32 14.87,7.52 L 17.62,9.14 C 17.62,9.1 17.62,9.07 17.62,9.04 C 17.62,8.55 17.5,8.09 17.25,7.65 C 17.02,7.2 16.68,6.84 16.23,6.58 C 15.79,6.31 15.28,6.18 14.71,6.18 C 14.21,6.18 13.76,6.29 13.38,6.51 L 10.48,8.18 C 10.37,8.25 10.31,8.35 10.31,8.48 V 9.6 L 13.88,7.52 Z"),
        "Claude": vectorMark("M 16,3 L 18.2,11.5 L 26.5,8.5 L 21.5,15 L 29,18 L 21.5,21 L 26.5,27.5 L 18.2,24.5 L 16,33 L 13.8,24.5 L 5.5,27.5 L 10.5,21 L 3,18 L 10.5,15 L 5.5,8.5 L 13.8,11.5 Z"),
        "Gemini": vectorMark("M 16,2 C 16,9.5 9.5,16 2,16 C 9.5,16 16,22.5 16,30 C 16,22.5 22.5,16 30,16 C 22.5,16 16,9.5 16,2 Z"),
        "Cursor": vectorMark("M 16,4 L 27,10 L 27,22 L 16,28 L 5,22 L 5,10 Z M 16,4 L 16,28 M 5,10 L 27,22 M 27,10 L 5,22"),
    ]

    private static func vectorMark(_ source: String) -> CGPath {
        let scanner = Scanner(string: source.replacingOccurrences(of: ",", with: " "))
        scanner.locale = Locale(identifier: "en_US_POSIX")
        let path = CGMutablePath()
        var current = CGPoint.zero
        func point() -> CGPoint {
            CGPoint(x: scanner.scanDouble() ?? 0, y: scanner.scanDouble() ?? 0)
        }
        while let command = scanner.scanCharacters(from: CharacterSet(charactersIn: "MLCHVZ")) {
            switch command {
            case "M": current = point(); path.move(to: current)
            case "L": current = point(); path.addLine(to: current)
            case "C":
                let first = point(), second = point()
                current = point()
                path.addCurve(to: current, control1: first, control2: second)
            case "H": current.x = scanner.scanDouble() ?? 0; path.addLine(to: current)
            case "V": current.y = scanner.scanDouble() ?? 0; path.addLine(to: current)
            case "Z": path.closeSubpath()
            default: return path
            }
        }
        return path
    }

    private func drawProvider(_ provider: String, at origin: CGPoint) {
        guard let context = NSGraphicsContext.current?.cgContext else { return }
        let colors: [String: NSColor] = [
            "Codex": .rgb(46, 205, 163), "Claude": .rgb(237, 155, 113),
            "Gemini": .rgb(110, 158, 255), "Cursor": .rgb(80, 205, 249)
        ]
        guard let mark = Self.providerMarks[provider], let color = colors[provider] else {
            text("•", NSRect(x: origin.x, y: origin.y, width: 26, height: 25),
                 size: 18, color: .rgb(191, 185, 188), alignment: .center)
            return
        }
        let box = mark.boundingBoxOfPath
        guard !box.isEmpty else { return }
        let scale = 24 / max(box.width, box.height)
        context.saveGState()
        context.translateBy(x: origin.x + 13 - box.midX * scale, y: origin.y + 13 + box.midY * scale)
        context.scaleBy(x: scale, y: -scale)
        context.addPath(mark)
        if provider == "Cursor" {
            context.setStrokeColor(color.cgColor)
            context.setLineWidth(2)
            context.setLineJoin(.round)
            context.strokePath()
        } else {
            context.setFillColor(color.cgColor)
            context.fillPath()
        }
        context.restoreGState()
    }

    private static let proMaxArtwork = Bundle.main.url(forResource: "ClawdyProMax", withExtension: "png")
        .flatMap { NSImage(contentsOf: $0) }

    private func drawProMax(at origin: NSPoint) {
        guard let image = Self.proMaxArtwork else { return }
        let width: CGFloat = 82
        let height = width * image.size.height / image.size.width
        image.draw(in: NSRect(x: origin.x, y: origin.y - height / 2, width: width, height: height))
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        guard bounds.width > 3 && bounds.height > 3,
              let context = NSGraphicsContext.current?.cgContext else { return }
        let expanded = moveMode || (!paused && (snapshot.state == .attention || snapshot.state == .error))
        let size = expanded ? rendererExpandedSize : rendererSize
        let scaleToFit = min(bounds.width / size.width, bounds.height / size.height)
        context.saveGState()
        defer { context.restoreGState() }
        context.translateBy(x: (bounds.width - size.width * scaleToFit) / 2,
                            y: (bounds.height - size.height * scaleToFit) / 2)
        context.scaleBy(x: scaleToFit, y: scaleToFit)
        let width = size.width, height = size.height
        let style = StateStyle.forState(snapshot.state)
        let theme: (upper: NSColor, lower: NSColor, rim: NSColor)
        switch paused ? .idle : snapshot.state {
        case .working: theme = (.rgb(74, 38, 22), .rgb(28, 16, 16), .rgb(255, 185, 35))
        case .ready: theme = (.rgb(20, 56, 34), .rgb(8, 26, 18), .rgb(50, 220, 130))
        case .attention, .error: theme = (.rgb(74, 20, 24), .rgb(30, 8, 12), .rgb(255, 77, 77))
        default: theme = (.rgb(40, 27, 25), .rgb(18, 14, 15), .rgb(225, 148, 109))
        }
        let capsule = NSRect(x: 1, y: 1, width: width - 2, height: height - 2)
        let radius = expanded ? CGFloat(32) : capsule.height / 2
        let outline = rounded(capsule, radius)
        NSGradient(starting: theme.lower, ending: theme.upper)?.draw(in: outline, angle: 90)
        let border = rounded(capsule.insetBy(dx: 0.5, dy: 0.5), radius - 0.5)
        border.lineWidth = 1
        theme.rim.withAlphaComponent(dark ? 0.48 : 0.60).setStroke()
        border.stroke()
        let rowY = height - 34
        drawProMax(at: NSPoint(x: 10, y: rowY))
        // The physical traffic light is laid on its side, with three lenses in
        // one horizontal head. The island itself stays fixed; no hover loop.
        for (index, base): (Int, NSColor) in [(0,.rgb(255,94,87)),(1,.rgb(255,191,61)),(2,.rgb(92,226,143))] {
            let active = !paused && ((index == 0 && (snapshot.state == .attention || snapshot.state == .error))
                || (index == 1 && snapshot.state == .working) || (index == 2 && snapshot.state == .ready))
            let lens = NSRect(x: width - 79 + CGFloat(index) * 21, y: rowY - 6.5, width: 13, height: 13)
            if active {
                NSGraphicsContext.saveGraphicsState()
                let glow = NSShadow()
                glow.shadowColor = base.withAlphaComponent(0.75)
                glow.shadowBlurRadius = 10
                glow.shadowOffset = .zero
                glow.set()
                fill(NSBezierPath(ovalIn: lens), base)
                NSGraphicsContext.restoreGraphicsState()
            } else {
                fill(NSBezierPath(ovalIn: lens), base.mixed(with: theme.lower, amount: 0.80))
            }
        }

        let provider = !paused && snapshot.working_count > 0 ? displayedProvider : nil
        if let provider { drawProvider(provider, at: CGPoint(x: 92, y: rowY - 13)) }
        let textX: CGFloat = provider == nil ? 94 : 128
        let textWidth = width - textX - 94
        let title = paused ? "Paused" : provider ?? style.title
        text(title, NSRect(x: textX, y: rowY + 1, width: textWidth, height: 20),
             size: 15, weight: .semibold, color: .rgb(250, 244, 242))
        let more = providerLabels.count - 1
        let count = workingLabel(snapshot.working_count)
        let subtitle = provider != nil && more > 0 ? "\(count) · +\(more) \(more == 1 ? "app" : "apps")" : count
        let details = snapshot.demo ? subtitle + " · Demo" : subtitle
        text(details, NSRect(x: textX, y: rowY - 17, width: textWidth, height: 15),
             size: 11, weight: .medium, color: .rgb(213, 196, 193))
        if expanded {
            let phrase = moveMode ? "Drag to move · finish in the menu" : (snapshot.phrase.isEmpty ? style.phrase : snapshot.phrase)
            text(phrase, NSRect(x: 20, y: 10, width: width - 40, height: 17),
                 size: 11, color: .rgb(226, 206, 206), alignment: .center)
        }
        if moveMode {
            let boundary=rounded(capsule.insetBy(dx:1,dy:1),radius - 1);boundary.lineWidth=0.8;boundary.setLineDash([2,3],count:2,phase:0);theme.rim.withAlphaComponent(0.7).setStroke();boundary.stroke()
        }
    }
}

private final class ClawdyPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

// Coalesce stdin onto one main-queue drain. Rapid snapshots/preferences cannot
// create an unbounded main-event backlog; the last ping is sufficient for liveness.
private final class RendererInbox {
    private let lock = NSLock()
    private var snapshot: ClawdySnapshot?
    private var hidden: Bool?, paused: Bool?, reducedMotion: Bool?, moveMode: Bool?
    private var nonce: Int?
    private var scheduled = false
    var consume: ((ClawdySnapshot?, Bool?, Bool?, Bool?, Bool?, Int?) -> Void)?
    func submit(_ message: ParentMessage) {
        lock.lock()
        switch message.type {
        case "snapshot": if let value = message.snapshot, validSnapshot(value) { snapshot = value }
        case "preferences":
            if let value = message.hidden { hidden = value }
            if let value = message.paused { paused = value }
            if let value = message.reducedMotion { reducedMotion = value }
            if let value = message.moveMode { moveMode = value }
        case "ping": nonce = message.nonce
        default: break
        }
        if !scheduled {
            scheduled = true
            DispatchQueue.main.async { [weak self] in self?.drain() }
        }
        lock.unlock()
    }
    private func drain() {
        lock.lock()
        let values = (snapshot, hidden, paused, reducedMotion, moveMode, nonce)
        snapshot = nil; hidden = nil; paused = nil; reducedMotion = nil; moveMode = nil; nonce = nil; scheduled = false
        lock.unlock()
        consume?(values.0, values.1, values.2, values.3, values.4, values.5)
    }
}

// Main-queue progress is acknowledged before enqueueing. A nonblocking pipe
// write can never hold AppKit waiting for its parent; at most one latest pong
// and one writability source are retained during backpressure.
private final class RendererPongChannel {
    private var pending: Data?
    private var writable: DispatchSourceWrite?
    private var configured = false
    init() {
        signal(SIGPIPE, SIG_IGN)
        let flags = fcntl(STDOUT_FILENO, F_GETFL)
        if flags >= 0 { configured = fcntl(STDOUT_FILENO, F_SETFL, flags | O_NONBLOCK) == 0 }
    }
    func submit(_ message: ChildMessage) {
        dispatchPrecondition(condition: .onQueue(.main))
        guard configured else { NSApp.terminate(nil); return }
        guard let data = try? encodedLine(message), data.count <= 256 else { return }
        pending = data
        flush()
    }
    private func flush() {
        guard let data = pending else { stopWaiting(); return }
        let written = data.withUnsafeBytes { Darwin.write(STDOUT_FILENO, $0.baseAddress, $0.count) }
        if written == data.count { pending = nil; stopWaiting() }
        else if written < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) {
            if writable == nil {
                let source = DispatchSource.makeWriteSource(fileDescriptor: STDOUT_FILENO, queue: .main)
                source.setEventHandler { [weak self] in self?.flush() }
                writable = source
                source.activate()
            }
        } else {
            // Tiny <= PIPE_BUF writes are atomic on the inherited pipe. A
            // closed/broken parent is an orderly renderer shutdown, not SIGPIPE.
            pending = nil; stopWaiting(); NSApp.terminate(nil)
        }
    }
    private func stopWaiting() { writable?.cancel(); writable = nil }
    deinit { writable?.cancel() }
}

private final class RendererDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private var panel: ClawdyPanel!
    private var canvas: ClawdyCanvas!
    private var hidden = false, paused = false, reducedMotion = false, moveMode = false, sleeping = false
    private var manuallyMoved = false
    private var clamping = false
    private var providerRotationTimer: Timer?
    private var observers: [NSObjectProtocol] = []
    private let inbox = RendererInbox()
    private lazy var pongChannel = RendererPongChannel()
    // Acceptance fixtures inject only this process's geometry/motion observation;
    // they never change screen configuration, OS preferences or workspace state.
    private var fixtureWorkArea: NSRect?
    private var systemReducedMotion: () -> Bool = { NSWorkspace.shared.accessibilityDisplayShouldReduceMotion }

    func applicationDidFinishLaunching(_ notification: Notification) { preparePanel(attachInput: true) }
    private func preparePanel(attachInput: Bool) {
        panel = ClawdyPanel(contentRect: NSRect(origin: .zero, size: rendererSize), styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.backgroundColor = .clear; panel.isOpaque = false; panel.hasShadow = true
        panel.level = .floating; panel.isFloatingPanel = true; panel.hidesOnDeactivate = false
        panel.becomesKeyOnlyIfNeeded = true; panel.ignoresMouseEvents = true
        panel.isReleasedWhenClosed = false; panel.collectionBehavior = [.transient, .ignoresCycle]
        panel.delegate = self
        canvas = ClawdyCanvas(frame: NSRect(origin: .zero, size: rendererSize))
        canvas.autoresizingMask = [.width, .height]
        panel.contentView = canvas
        positionPanel(size: rendererSize, animated: false)
        inbox.consume = { [weak self] snapshot, hidden, paused, motion, move, nonce in
            guard let self = self else { return }
            var changed = snapshot.map { self.apply($0) } ?? false
            if let value = hidden, value != self.hidden { self.hidden = value; changed = true }
            if let value = paused, value != self.paused { self.paused = value; changed = true }
            if let value = motion, value != self.reducedMotion { self.reducedMotion = value; changed = true }
            if let value = move, value != self.moveMode { self.moveMode = value; changed = true }
            if changed { self.updatePresentation() }
            if let nonce = nonce {
                // This code is reached only through the AppKit main queue.
                self.pongChannel.submit(ChildMessage(type: "pong", nonce: nonce))
            }
        }
        if attachInput {
            observeLifecycle()
            updatePresentation()
            startInput()
        }
    }
    private func workAreas() -> [NSRect] {
        if let area = fixtureWorkArea { return [area] }
        return NSScreen.screens.map { $0.visibleFrame }
    }
    private func clamp() {
        guard !clamping, panel != nil else { return }
        let frame = clampedFrame(panel.frame, workAreas: workAreas())
        if frame != panel.frame {
            clamping = true; panel.setFrame(frame, display: true); clamping = false
        }
    }
    func windowDidMove(_ notification: Notification) {
        if moveMode && !clamping { manuallyMoved = true }
        clamp()
    }
    private func positionPanel(size: NSSize, animated: Bool) {
        let old = panel.frame
        let target: NSRect
        if manuallyMoved {
            target = clampedFrame(NSRect(x:old.midX-size.width/2,y:old.maxY-size.height,width:size.width,height:size.height),workAreas:workAreas())
        } else if let area = fixtureWorkArea {
            target = topCenteredFrame(size,area:area)
        } else if let screen = NSScreen.main ?? NSScreen.screens.first {
            target = topCenteredFrame(size,area:screen.visibleFrame,safeTop:screen.frame.maxY-screen.safeAreaInsets.top)
        } else { target = topCenteredFrame(size,area:NSRect(x:0,y:0,width:1024,height:768)) }
        guard target != old else { return }
        clamping = true
        panel.setFrame(target,display:true)
        canvas.frame = NSRect(origin:.zero,size:target.size)
        clamping = false
        if animated && old.width > 0 && old.height > 0 {
            let transition = CABasicAnimation(keyPath:"transform")
            var from = CATransform3DMakeTranslation(0,(target.height-old.height)/2,0)
            from = CATransform3DScale(from,old.width/target.width,old.height/target.height,1)
            transition.fromValue = NSValue(caTransform3D:from)
            transition.toValue = NSValue(caTransform3D:CATransform3DIdentity)
            transition.duration = 0.23;transition.timingFunction = CAMediaTimingFunction(name:.easeInEaseOut)
            canvas.layer?.add(transition,forKey:"island-resize")
        }
    }
    private func apply(_ snapshot: ClawdySnapshot) -> Bool {
        let old = canvas.snapshot
        // The host owns revision/instance ordering and may synthesize local
        // stale/disconnected snapshots; presentation follows that trusted order.
        let changed = snapshot.state != old.state || snapshot.working_count != old.working_count
            || snapshot.providers != old.providers || snapshot.demo != old.demo || snapshot.phrase != old.phrase
        if snapshot.providers != old.providers {
            canvas.providerRotationIndex = 0
            providerRotationTimer?.invalidate(); providerRotationTimer = nil
        }
        canvas.snapshot = snapshot
        return changed
    }
    private func updatePresentation() {
        guard canvas != nil else { return }
        canvas.paused = paused; canvas.moveMode = moveMode
        canvas.reducedMotion = reducedMotion || systemReducedMotion()
        panel.ignoresMouseEvents = !moveMode
        canvas.updateAccessibility()
        if hidden || sleeping {
            if panel.isVisible { panel.orderOut(nil) }
        } else if !panel.isVisible { panel.orderFrontRegardless() }
        // Stable camera-adjacent anchor. Only bounded state transitions animate;
        // there is no hover, recurring display timer or animation polling.
        let animate = !hidden && !sleeping && !paused && !canvas.reducedMotion && !moveMode
        if !animate { canvas.layer?.removeAllAnimations() }
        positionPanel(size:presentationSize(canvas.snapshot.state,paused:paused,moveMode:moveMode),animated:animate)
        updateProviderRotation()
        canvas.needsDisplay = true
    }
    private var rotatesProviders: Bool {
        !hidden && !sleeping && !paused && !canvas.reducedMotion && !moveMode
        && canvas.snapshot.state == .working && canvas.providerLabels.count > 1
    }
    private func rotateProvider() {
        guard rotatesProviders else { return }
        canvas.providerRotationIndex = (canvas.providerRotationIndex+1) % canvas.providerLabels.count
        canvas.needsDisplay = true
    }
    private func updateProviderRotation() {
        if !rotatesProviders { providerRotationTimer?.invalidate(); providerRotationTimer = nil }
        else if providerRotationTimer == nil {
            let timer = Timer(timeInterval:5,repeats:true) { [weak self] _ in self?.rotateProvider() }
            providerRotationTimer = timer
            RunLoop.main.add(timer,forMode:.common)
        }
    }
    private func screenConfigurationChanged() {
        manuallyMoved = false
        positionPanel(size:presentationSize(canvas.snapshot.state,paused:paused,moveMode:moveMode),animated:false)
    }
    private func setSleeping(_ value: Bool) {
        sleeping = value
        if !value { clamp() }
        updatePresentation()
    }
    private func observeLifecycle() {
        let center = NotificationCenter.default
        observers.append(center.addObserver(forName: NSApplication.didChangeScreenParametersNotification, object: nil, queue: .main) { [weak self] _ in self?.screenConfigurationChanged() })
        let workspace = NSWorkspace.shared.notificationCenter
        for name in [NSWorkspace.willSleepNotification, NSWorkspace.sessionDidResignActiveNotification] {
            observers.append(workspace.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in self?.setSleeping(true) })
        }
        for name in [NSWorkspace.didWakeNotification, NSWorkspace.sessionDidBecomeActiveNotification] {
            observers.append(workspace.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in self?.setSleeping(false) })
        }
        observers.append(workspace.addObserver(forName: NSWorkspace.accessibilityDisplayOptionsDidChangeNotification, object: nil, queue: .main) { [weak self] _ in self?.updatePresentation() })
    }
    private func startInput() {
        DispatchQueue.global(qos: .utility).async { [weak self] in
            var framer = NDJSONFramer()
            do {
                while true {
                    let chunk = FileHandle.standardInput.availableData
                    if chunk.isEmpty { break }
                    for frame in try framer.append(chunk) {
                        if let message = try? JSONDecoder().decode(ParentMessage.self, from: frame) { self?.inbox.submit(message) }
                    }
                }
            } catch { FileHandle.standardError.write(Data("Clawdy renderer: invalid or oversized input frame.\n".utf8)) }
            DispatchQueue.main.async { NSApp.terminate(nil) }
        }
    }
    // Offscreen native acceptance: real AppKit panel/view, production handlers,
    // no physical clicks, global notifications, display changes or user-app edits.
    func runNativeAcceptance() throws -> [String] {
        enum Failure: Error { case check(String) }
        func check(_ condition: @autoclosure () -> Bool, _ message: String) throws {
            if !condition() { throw Failure.check(message) }
        }
        _ = NSApplication.shared
        NSApp.setActivationPolicy(.accessory)
        let initialFrontmost = NSWorkspace.shared.frontmostApplication?.processIdentifier
        let initialActive = NSApp.isActive
        fixtureWorkArea = NSRect(x:-20000,y:-20000,width:1200,height:800)
        systemReducedMotion = { false }
        preparePanel(attachInput:false)
        defer { providerRotationTimer?.invalidate(); panel.orderOut(nil); panel.close() }
        try check(NSScreen.screens.allSatisfy { !panel.frame.intersects($0.frame) }, "Fixture must remain offscreen")
        try check(panel.styleMask.contains(.nonactivatingPanel) && !panel.canBecomeKey && !panel.canBecomeMain, "Panel must reject key/main activation")
        try check(panel.ignoresMouseEvents && !canvas.acceptsFirstResponder, "Default click-through and no responder capture")
        try check(panel.level == .floating && !panel.collectionBehavior.contains(.canJoinAllSpaces) && !panel.collectionBehavior.contains(.fullScreenAuxiliary), "Floating on current desktop only")
        updatePresentation()
        RunLoop.main.run(until:Date(timeIntervalSinceNow:0.06))
        try check(panel.isVisible && !panel.isKeyWindow && !panel.isMainWindow, "Ordered panel must stay non-key/non-main")
        try check(NSWorkspace.shared.frontmostApplication?.processIdentifier == initialFrontmost && NSApp.isActive == initialActive, "Ordering must not change foreground application")
        var passed = ["native panel: nonactivation, floating/current-desktop flags and click-through property"]
        let work = ClawdySnapshot(version:1,instance_id:"fixture",revision:1,state:.working,working_count:2,providers:["codex","other"],demo:true,phrase:"")
        _ = apply(work); updatePresentation()
        try check(canvas.isAccessibilityElement() && canvas.accessibilityRole() == .image, "Native accessible image element")
        let label = canvas.accessibilityLabel() ?? ""
        try check(label.contains("Working") && label.contains("2 reported in progress") && label.contains("Codex") && label.contains("Other") && label.contains("Demo data"), "Accessible state/count/providers/demo summary")
        try check(canvas.accessibilityHelp()?.contains("Click-through") == true, "Accessible menu-controls hint")
        try check(panel.frame.size == rendererSize, "Normal compact dimensions")
        try check(canvas.displayedProvider == "Codex" && providerRotationTimer?.isValid == true && providerRotationTimer?.timeInterval == 5, "Working shows AI app name; mixed apps alone get five-second rotation")
        rotateProvider()
        try check(canvas.displayedProvider == "Other", "Mixed provider rotation uses app summary rather than inferred models")
        let anchor = panel.frame.maxY
        var sameDisplay = work; sameDisplay.revision = 999
        canvas.needsDisplay = false
        try check(!apply(sameDisplay) && !canvas.needsDisplay, "Revision-only snapshots must not invalidate cached vectors")
        var attention = work; attention.state = .attention; attention.revision = 2
        _ = apply(attention); updatePresentation()
        try check(panel.frame.size == rendererExpandedSize && abs(panel.frame.maxY-anchor)<0.01, "Expansion preserves top anchor and bounded dimensions")
        if let animation = canvas.layer?.animation(forKey:"island-resize") as? CABasicAnimation {
            try check(animation.duration > 0 && animation.duration <= 0.25 && animation.repeatCount == 0 && !animation.autoreverses && (canvas.layer?.animationKeys() ?? []).count == 1, "Transition must be finite, short, single and nonrepeating")
        } else { throw Failure.check("Expected one bounded compositor resize transition") }
        passed.append("accessibility: real AppKit image label, state/WIP/providers/demo/help")
        reducedMotion = true; updatePresentation()
        try check(canvas.reducedMotion && (canvas.layer?.animationKeys() ?? []).isEmpty && providerRotationTimer == nil, "Explicit reduced motion removes transitions and rotation")
        reducedMotion = false; systemReducedMotion = { true }; updatePresentation()
        try check(canvas.reducedMotion && (canvas.layer?.animationKeys() ?? []).isEmpty && providerRotationTimer == nil, "Observed OS reduced motion removes transitions and rotation without changing OS")
        systemReducedMotion = { false }; paused = true; updatePresentation()
        try check(canvas.paused && panel.frame.size == rendererSize && (canvas.layer?.animationKeys() ?? []).isEmpty, "Pause is compact and static")
        try check(canvas.accessibilityLabel()?.contains("Paused") == true, "Pause accessible state")
        hidden = true; updatePresentation()
        try check(!panel.isVisible && (canvas.layer?.animationKeys() ?? []).isEmpty, "Hidden removes window and transitions")
        hidden = false; paused = false; updatePresentation()
        setSleeping(true)
        try check(!panel.isVisible && (canvas.layer?.animationKeys() ?? []).isEmpty, "Sleep/session-inactive handler hides and stops transition")
        setSleeping(false)
        try check(panel.isVisible, "Wake/session-active handler restores visibility")
        moveMode = true; updatePresentation()
        try check(!panel.ignoresMouseEvents && canvas.acceptsFirstMouse(for:nil) && panel.frame.size == rendererExpandedSize, "Explicit move mode alone enables interaction")
        try check((canvas.layer?.animationKeys() ?? []).isEmpty, "Move mode disables transitions")
        moveMode = false; updatePresentation()
        try check(panel.ignoresMouseEvents, "Finishing move restores click-through")
        fixtureWorkArea = NSRect(x:-18000,y:-14000,width:900,height:700)
        manuallyMoved = true
        screenConfigurationChanged()
        try check(!manuallyMoved && abs(panel.frame.midX-fixtureWorkArea!.midX)<0.01 && abs(panel.frame.maxY-(fixtureWorkArea!.maxY-6))<0.01, "Monitor-change handler reanchors at safe top center")
        // Isolate each stop condition while the working/mixed-app precondition
        // really holds, rather than passing because attention already stopped it.
        for gate in ["hidden","paused","sleeping","motion","moving"] {
            hidden = false; paused = false; sleeping = false; reducedMotion = false; moveMode = false
            systemReducedMotion = { false }
            _ = apply(work); updatePresentation()
            try check(providerRotationTimer?.isValid == true,"Mixed-app clock must be active before testing " + gate)
            switch gate {
            case "hidden": hidden = true
            case "paused": paused = true
            case "sleeping": sleeping = true
            case "motion": reducedMotion = true
            default: moveMode = true
            }
            updatePresentation()
            try check(providerRotationTimer == nil && (canvas.layer?.animationKeys() ?? []).isEmpty,"Clock/transitions must stop for " + gate)
        }
        hidden = false; paused = false; sleeping = false; reducedMotion = false; moveMode = false
        var single = work; single.providers = ["codex"]
        _ = apply(single); updatePresentation()
        try check(providerRotationTimer == nil,"Single app needs no rotation clock")
        var uncertain = work; uncertain.state = .uncertain
        _ = apply(uncertain); updatePresentation()
        try check(canvas.displayedProvider == "Codex" && canvas.providerLabels.count == 2 && providerRotationTimer == nil,"Uncertain active records retain static app hint without rotation")
        try check(canvas.accessibilityLabel()?.contains("Unconfirmed") == true,"Uncertain app hint preserves unconfirmed status")
        uncertain.working_count = 0
        _ = apply(uncertain); updatePresentation()
        try check(canvas.snapshot.working_count == 0,"Uncertain zero-WIP state has no active-app hint")
        passed.append("production preference/lifecycle handlers: hidden, paused, reduced motion, move, sleep/wake and screen change (injected only)")
        passed.append("animation: finite <=250 ms; no hover/polling; mixed-app rotation only every 5 s while visible working; reduced motion stops it")
        try check(NSWorkspace.shared.frontmostApplication?.processIdentifier == initialFrontmost && NSApp.isActive == initialActive, "Fixture completion must not change foreground application")
        passed.append("foreground unchanged before/after offscreen window ordering")
        return passed
    }
    func applicationWillTerminate(_ notification: Notification) { providerRotationTimer?.invalidate(); canvas?.layer?.removeAllAnimations() }
}

private func writePreview(_ path: String, state: ClawdyState, dark: Bool, count: Int) throws {
    _ = NSApplication.shared
    NSApp.setActivationPolicy(.prohibited)
    let size = presentationSize(state)
    let view = ClawdyCanvas(frame: NSRect(origin: .zero, size: size))
    view.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
    view.snapshot = ClawdySnapshot(version: 1, instance_id: "preview", revision: 1, state: state,
                                   working_count: count, providers: ["codex", "claude"], demo: true, phrase: "")
    view.reducedMotion = true
    guard let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size.width*2), pixelsHigh: Int(size.height*2), bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0),
          let context = NSGraphicsContext(bitmapImageRep: bitmap) else { throw NSError(domain: "ClawdyPreview", code: 1) }
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = context
    context.cgContext.clear(CGRect(x: 0, y: 0, width: size.width*2, height: size.height*2))
    context.cgContext.scaleBy(x: 2, y: 2)
    view.appearance?.performAsCurrentDrawingAppearance { view.draw(view.bounds) }
    NSGraphicsContext.restoreGraphicsState()
    guard let png = bitmap.representation(using: .png, properties: [:]) else { throw NSError(domain: "ClawdyPreview", code: 2) }
    try png.write(to: URL(fileURLWithPath: path), options: .atomic)
}

private func selfTest() -> Bool {
    let screens = [NSRect(x: -1920, y: 28, width: 1920, height: 1052), NSRect(x: 0, y: 24, width: 1440, height: 876)]
    let cases = [NSRect(x: -5000, y: -100, width: 196, height: 40), NSRect(x: 1500, y: 1200, width: 196, height: 40),
                 NSRect(x: -1500, y: 200, width: 196, height: 40), NSRect(x: -100, y: 200, width: 196, height: 40)]
    for frame in cases {
        let result = clampedFrame(frame, workAreas: screens)
        if !screens.contains(where: { $0.contains(result) }) { return false }
    }
    let tiny = NSRect(x:40,y:50,width:120,height:35)
    if clampedFrame(NSRect(origin:.zero,size:rendererExpandedSize),workAreas:[tiny]) != tiny { return false }
    for screen in screens {
        let frame = topCenteredFrame(rendererSize,area:screen)
        if !screen.contains(frame) || abs(frame.midX-screen.midX)>0.01 || abs(frame.maxY-(screen.maxY-6))>0.01 { return false }
        let safe = topCenteredFrame(rendererExpandedSize,area:screen,safeTop:screen.maxY-42)
        if !screen.contains(safe) || safe.maxY > screen.maxY-48.0 { return false }
    }
    // Simulated screens: negative/vertical origins, tiny areas, menu/Dock work
    // areas and camera insets. Never move physical monitors to exercise these.
    let areas = [NSRect(x:-3840,y:-1200,width:1920,height:1080),
                 NSRect(x:0,y:0,width:1512,height:945),NSRect(x:300,y:1600,width:1200,height:760),
                 NSRect(x:-500,y:40,width:160,height:35),NSRect(x:10,y:10,width:80,height:90)]
    for area in areas {
        for inset: CGFloat in [0,24,37,80] {
            for state in ClawdyState.allCases {
                for moving in [false,true] {
                    let size = presentationSize(state,moveMode:moving)
                    let safeTop = area.maxY-inset
                    let result = topCenteredFrame(size,area:area,safeTop:safeTop)
                    if !area.contains(result) || abs(result.midX-area.midX)>0.01
                        || result.maxY > max(area.minY,safeTop-6)+0.01
                        || result.width > size.width || result.height > size.height { return false }
                }
            }
        }
    }
    if workingLabel(0) != "0 WIP" || workingLabel(9999) != "9999 WIP" { return false }
    if presentationSize(.working) != rendererSize || presentationSize(.attention) != rendererExpandedSize { return false }
    let good = ClawdySnapshot(version: 1, instance_id: "test", revision: 0, state: .working, working_count: 2, providers: ["codex"], demo: true, phrase: "Quietly working.")
    if !validSnapshot(good) { return false }
    let invalid = ClawdySnapshot(version: 2, instance_id: "test", revision: 0, state: .working, working_count: 2, providers: [], demo: true, phrase: "")
    return !validSnapshot(invalid)
}

@main
private enum ClawdyRendererMain {
    static func main() {
        let args = CommandLine.arguments
        if args.contains("--acceptance-test") {
            do {
                guard selfTest() else { throw NSError(domain:"ClawdyPlacement",code:1) }
                let evidence = try RendererDelegate().runNativeAcceptance()
                for item in evidence { print("PASS: " + item) }
                print("Limits: no physical click delivery, VoiceOver speech, notch/external display, real sleep/lock or fullscreen acceptance was performed.")
            } catch {
                FileHandle.standardError.write(Data("Renderer acceptance failed: \(error)\n".utf8)); exit(1)
            }
            return
        }
        if args.contains("--self-test") {
            let passed = selfTest()
            print(passed ? "Renderer self-test passed: top-center placement, safe top, 280 simulated screen/state/move combinations, monitor fallback, compact sizing and model." : "Renderer self-test failed.")
            exit(passed ? 0 : 1)
        }
        if let index = args.firstIndex(of: "--render-preview"), index+1 < args.count {
            let stateIndex = args.firstIndex(of: "--state")
            let state = stateIndex.flatMap { $0+1 < args.count ? ClawdyState(rawValue: args[$0+1]) : nil } ?? .working
            let count = state == .working || state == .attention || state == .uncertain ? 2 : 0
            do { try writePreview(args[index+1], state: state, dark: args.contains("--dark"), count: count) }
            catch { FileHandle.standardError.write(Data("Clawdy preview failed: \(error.localizedDescription)\n".utf8)); exit(1) }
            return
        }
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        let delegate = RendererDelegate()
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
