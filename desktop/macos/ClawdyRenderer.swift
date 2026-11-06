import AppKit
import QuartzCore
import Foundation
import Darwin

// Private prototype renderer. Compile with Shared.swift; stdin is the only input.
// Contract: ParentMessage(type: snapshot/preferences/ping), main-queue ChildMessage pong.
// The overlay uses a stylized vector mascot.

private let rendererSize = NSSize(width: 196, height: 40)
private let rendererExpandedSize = NSSize(width: 252, height: 66)

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
    let accent: NSColor
    let phrase: String
    let symbol: String
    static func forState(_ state: ClawdyState) -> StateStyle {
        switch state {
        case .idle: return StateStyle(title: "All quiet", accent: .rgb(122, 132, 145), phrase: "A little quiet. A little Clawdy.", symbol: "moon.zzz.fill")
        case .working: return StateStyle(title: "Working", accent: .rgb(221, 160, 50), phrase: "A few things are taking shape.", symbol: "sparkle")
        case .ready: return StateStyle(title: "Ready", accent: .rgb(66, 162, 109), phrase: "Your next move.", symbol: "checkmark")
        case .attention: return StateStyle(title: "Your input", accent: .rgb(215, 118, 70), phrase: "A small nudge is needed.", symbol: "hand.raised.fill")
        case .error: return StateStyle(title: "Needs a look", accent: .rgb(207, 82, 78), phrase: "Something needs a little care.", symbol: "exclamationmark")
        case .disconnected: return StateStyle(title: "Disconnected", accent: .rgb(135, 141, 152), phrase: "Waiting for a fresh signal.", symbol: "link.badge.plus")
        case .uncertain: return StateStyle(title: "Unconfirmed", accent: .rgb(158, 137, 185), phrase: "Last report. Current status unknown.", symbol: "questionmark")
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
    var providerSubtitle: String? {
        guard !paused else { return nil }
        let names = providerLabels
        if snapshot.state == .uncertain && snapshot.working_count > 0, let first = names.first {
            return first + (names.count > 1 ? " +\(names.count-1)" : "")
        }
        if snapshot.state == .working && names.count > 1 {
            return "+\(names.count-1) \(names.count == 2 ? "app" : "apps")"
        }
        return nil
    }
    var visibleAccent: NSColor = .rgb(135, 141, 152)
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
    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        let width = bounds.width, height = bounds.height
        guard width > 3 && height > 3 else { return }
        let expanded = height > 48
        let style = StateStyle.forState(snapshot.state)
        let accent = paused ? NSColor.rgb(150, 155, 165) : visibleAccent
        let capsule = bounds.insetBy(dx: 1, dy: 1)
        let outline = rounded(capsule, expanded ? 21 : 19)
        let upper = dark ? NSColor.rgb(37, 39, 46) : NSColor.rgb(43, 45, 52)
        let lower = dark ? NSColor.rgb(14, 16, 21) : NSColor.rgb(22, 24, 30)
        NSGradient(starting: lower, ending: upper)?.draw(in: outline, angle: 90)
        let border = rounded(capsule.insetBy(dx: 0.5, dy: 0.5), expanded ? 20.5 : 18.5)
        border.lineWidth = 0.65; NSColor.white.withAlphaComponent(dark ? 0.12 : 0.16).setStroke(); border.stroke()
        // Compact top row stays the same height in the expanded island.
        let rowY = height - 29
        let iconOrigin = NSPoint(x: 12, y: rowY+1)
        let s: CGFloat = 45/52, scale: CGFloat = 0.36
        func p(_ x: CGFloat, _ z: CGFloat) -> NSPoint {
            NSPoint(x: iconOrigin.x + 10.3 + x*scale, y: iconOrigin.y+z*scale)
        }
        let body: [(CGFloat, CGFloat)] = [
            (-27*s,0),(-21*s,0),(-21*s,13*s),(-15*s,13*s),(-15*s,0),(-9*s,0),
            (-9*s,13*s),(9*s,13*s),(9*s,0),(15*s,0),(15*s,13*s),(21*s,13*s),
            (21*s,0),(27*s,0),(27*s,26*s),(33*s,26*s),(33*s,39*s),(27*s,39*s),
            (27*s,45),(-27*s,45),(-27*s,39*s),(-33*s,39*s),(-33*s,26*s),(-27*s,26*s)]
        NSGradient(starting: .rgb(229, 145, 110), ending: .rgb(196, 99, 73))?.draw(in: polygon(body.map { p($0.0,$0.1) }), angle: -90)
        let eye = NSColor.rgb(31, 27, 29)
        for x: CGFloat in [-18*s,18*s] {
            let center = p(x,35.75*s), side: CGFloat = 2.2
            if snapshot.state == .error && !paused {
                let cross = NSBezierPath(); cross.move(to: NSPoint(x:center.x-1,y:center.y-1)); cross.line(to:NSPoint(x:center.x+1,y:center.y+1))
                cross.move(to:NSPoint(x:center.x+1,y:center.y-1)); cross.line(to:NSPoint(x:center.x-1,y:center.y+1)); cross.lineWidth=0.85; eye.setStroke(); cross.stroke()
            } else { fill(rounded(NSRect(x:center.x-side/2,y:center.y-side/2,width:side,height:side),0.2),eye) }
        }
        // The physical traffic light is laid on its side, with three lenses in
        // one horizontal head. The island itself stays fixed; no hover loop.
        let strip = NSRect(x: 42, y: rowY+1, width: 50, height: 17)
        fill(rounded(strip,4), .rgb(9,11,15))
        let ring = rounded(strip.insetBy(dx:0.5,dy:0.5),3.5); ring.lineWidth=0.6; NSColor.white.withAlphaComponent(0.055).setStroke(); ring.stroke()
        for (index, base): (Int, NSColor) in [(0,.rgb(239,94,87)),(1,.rgb(245,187,62)),(2,.rgb(92,205,143))] {
            let active = !paused && ((index == 0 && (snapshot.state == .attention || snapshot.state == .error)) || (index == 1 && snapshot.state == .working) || (index == 2 && snapshot.state == .ready))
            let lens = NSRect(x: strip.minX+6+CGFloat(index)*14.5,y:strip.minY+4.5,width:8,height:8)
            if active {
                NSGraphicsContext.saveGraphicsState()
                let glow=NSShadow();glow.shadowColor=base.withAlphaComponent(0.6);glow.shadowBlurRadius=7;glow.shadowOffset = .zero;glow.set()
                fill(NSBezierPath(ovalIn:lens),base)
                NSGraphicsContext.restoreGraphicsState()
                fill(NSBezierPath(ovalIn:NSRect(x:lens.minX+2,y:lens.maxY-3,width:3.5,height:1.3)),.white.withAlphaComponent(0.4))
            } else { fill(NSBezierPath(ovalIn:lens),base.mixed(with:.rgb(22,25,31),amount:0.83)) }
        }
        let title: String
        if paused { title = "Paused" }
        else {
            switch snapshot.state {
            case .idle: title = "Quiet"
            case .working: title = displayedProvider ?? "Working"
            case .attention: title = "Your input"
            case .error: title = "Needs a look"
            case .disconnected: title = "Offline"
            case .uncertain: title = "Unclear"
            default: title = style.title
            }
        }
        let titleWidth = max(42,width-151)
        text(title,NSRect(x:101,y:rowY+2,width:titleWidth,height:14),size:10.5,weight:.semibold,color:.rgb(243,244,247))
        let badge = NSRect(x:width-50,y:rowY+2,width:39,height:14)
        fill(rounded(badge,7),accent.withAlphaComponent(0.15))
        text(workingLabel(snapshot.working_count),badge.offsetBy(dx:0,dy:1),size:7.8,weight:.semibold,color:accent,alignment:.center)
        if let subtitle = providerSubtitle {
            // Uncertain WIP retains a static reported-app hint, never a rotation
            // or freshness claim. Expanded and accessibility retain all names.
            text(subtitle,NSRect(x:101,y:rowY-5,width:titleWidth,height:7),size:5.5,weight:.medium,color:.rgb(151,157,172))
        }
        if snapshot.demo {
            text("DEMO",NSRect(x:width-36,y:height-10,width:25,height:6.5),size:5.4,weight:.semibold,color:.rgb(159,164,177),alignment:.center)
        }
        if expanded {
            let phrase = moveMode ? "Drag to move · finish in the menu" : (paused ? "Taking a little breather." : (snapshot.phrase.isEmpty ? style.phrase : snapshot.phrase))
            let divider = NSBezierPath(); divider.move(to:NSPoint(x:15,y:28)); divider.line(to:NSPoint(x:width-15,y:28)); divider.lineWidth=0.5; NSColor.white.withAlphaComponent(0.07).setStroke(); divider.stroke()
            let providers = providerLabels.joined(separator:" · ")
            text(phrase,NSRect(x:15,y:providers.isEmpty ? 10 : 16,width:width-30,height:12),size:8.5,weight:.medium,color:.rgb(187,192,204),alignment:.center)
            if !providers.isEmpty {
                text(providers,NSRect(x:15,y:5,width:width-30,height:9),size:7.2,weight:.medium,color:.rgb(149,157,174),alignment:.center)
            }
        }
        if moveMode {
            let boundary=rounded(capsule.insetBy(dx:1,dy:1),expanded ? 20 : 18);boundary.lineWidth=0.8;boundary.setLineDash([2,3],count:2,phase:0);accent.withAlphaComponent(0.7).setStroke();boundary.stroke()
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
        canvas.visibleAccent = StateStyle.forState(canvas.snapshot.state).accent
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
        try check(canvas.providerSubtitle == "Codex +1" && providerRotationTimer == nil,"Uncertain active records retain static app hint without rotation")
        try check(canvas.accessibilityLabel()?.contains("Unconfirmed") == true,"Uncertain app hint preserves unconfirmed status")
        uncertain.working_count = 0
        _ = apply(uncertain); updatePresentation()
        try check(canvas.providerSubtitle == nil,"Uncertain zero-WIP state has no active-app hint")
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
    view.visibleAccent = StateStyle.forState(state).accent
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
