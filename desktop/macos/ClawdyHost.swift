import AppKit
import Foundation
import Darwin

private enum CollectorMode: String, Equatable { case demo, observe }
private func uptime() -> TimeInterval { ProcessInfo.processInfo.systemUptime }

// Only fields which alter a native menu control belong here. Collector
// revisions and rotating phrases do not justify rebuilding SF Symbols/titles.
private struct MenuPresentationSignature: Equatable {
    var mode: CollectorMode
    var state: ClawdyState
    var count: Int
    var providers: [String]
    var confidence: ClawdyConfidence
    var overlayEnabled: Bool
    var attentionPhaseOn: Bool
    var preferences: ClawdyPreferences
    var rendererSafeMode: Bool
    var collectorSafeMode: Bool

    init(snapshot: ClawdySnapshot, mode: CollectorMode, preferences: ClawdyPreferences,
         rendererSafeMode: Bool, collectorSafeMode: Bool, overlayEnabled: Bool = false, now: TimeInterval = 0) {
        self.mode = mode; self.state = snapshot.state; self.count = snapshot.working_count
        self.providers = snapshot.providers
        self.confidence = snapshot.effectiveConfidence
        self.overlayEnabled = overlayEnabled
        self.preferences = preferences; self.rendererSafeMode = rendererSafeMode
        self.collectorSafeMode = collectorSafeMode
        // Only input-needed animates. Existing one-second host updates drive
        // this slow blink; static states do not invalidate the menu cache.
        self.attentionPhaseOn = snapshot.state != .attention || preferences.reducedMotion || preferences.paused
            || now.truncatingRemainder(dividingBy: 2) < 1
    }

    var attentionBlinks: Bool { state == .attention && !preferences.reducedMotion && !preferences.paused }

    func hasSameControls(as other: MenuPresentationSignature) -> Bool {
        var copy = self; copy.attentionPhaseOn = other.attentionPhaseOn
        return copy == other
    }

    var providerLabels: [String] {
        let names = ["claude": "Claude", "codex": "Codex", "gemini": "Gemini", "cursor": "Cursor", "other": "Other", "unknown": "Other"]
        return providers.compactMap { names[$0] }.reduce(into: []) { if !$0.contains($1) { $0.append($1) } }
    }

    var barTitle: String {
        let apps = providerLabels
        let summary = apps.first.map { $0 + (apps.count > 1 ? "+\(apps.count - 1)" : "") }
        if state == .disconnected { return "Offline · \(mode == .demo ? "DEMO" : "OBS")" }
        if state == .uncertain { return "Stale · \(mode == .demo ? "DEMO" : "OBS")" }
        let qualifier = state == .attention ? "Input · " : state == .error ? "Error · " : ""
        return qualifier + "\(count) WIP" + (summary.map { " · " + $0 } ?? "") + (mode == .demo ? " · DEMO" : "")
    }

    var activeLight: Int? {
        switch state {
        case .attention: return attentionBlinks && !attentionPhaseOn ? nil : 0
        case .error: return 0
        case .working: return 1
        case .ready: return 2
        default: return nil
        }
    }

    var accessibilityValue: String {
        let apps = providerLabels.joined(separator: ", ")
        let origin = mode == .demo ? "Demo data" : confidence == .reported
            ? "Read-only reported status; session liveness unconfirmed"
            : "Read-only status; confidence unknown; session liveness unconfirmed"
        var value = "\(origin). \(state.rawValue.capitalized). \(count) reported in progress."
        let lights = ["Red", "Yellow", "Green"]
        // Keep spoken status steady throughout the blink's off phase.
        if state == .attention { value += attentionBlinks ? " Input needed. Red light blinking." : " Input needed. Red light." }
        else { value += activeLight.map { " \(lights[$0]) light." } ?? " No active light." }
        if !apps.isEmpty { value += " Apps: \(apps)." }
        if rendererSafeMode { value += " Overlay recovery paused." }
        if collectorSafeMode { value += " Collector recovery paused." }
        return value
    }
}

// A native, non-template image preserves three recognizable traffic-light
// colors in either menu-bar appearance. State is also exposed in text/AX.
private func trafficLightImage(_ presentation: MenuPresentationSignature) -> NSImage {
    let image = NSImage(size: NSSize(width: 43, height: 18), flipped: false) { bounds in
        NSColor(calibratedWhite: 0.08, alpha: 0.9).setFill()
        NSBezierPath(roundedRect: bounds.insetBy(dx: 0.5, dy: 1), xRadius: 8, yRadius: 8).fill()
        NSColor.white.withAlphaComponent(0.18).setStroke()
        let outline = NSBezierPath(roundedRect: bounds.insetBy(dx: 0.5, dy: 1), xRadius: 8, yRadius: 8)
        outline.lineWidth = 0.5; outline.stroke()
        let colors = [NSColor(srgbRed: 1, green: 0.32, blue: 0.29, alpha: 1),
                      NSColor(srgbRed: 1, green: 0.76, blue: 0.22, alpha: 1),
                      NSColor(srgbRed: 0.29, green: 0.87, blue: 0.48, alpha: 1)]
        for (index, color) in colors.enumerated() {
            let spot = NSRect(x: 5 + CGFloat(index) * 12, y: 5, width: 8, height: 8)
            let active = presentation.activeLight == index
            if active {
                color.withAlphaComponent(0.22).setFill()
                NSBezierPath(ovalIn: spot.insetBy(dx: -1.5, dy: -1.5)).fill()
            }
            color.withAlphaComponent(active ? 1 : 0.25).setFill()
            NSBezierPath(ovalIn: spot).fill()
            if active {
                NSColor.white.withAlphaComponent(0.65).setFill()
                NSBezierPath(ovalIn: NSRect(x: spot.minX + 1.6, y: spot.minY + 4.6, width: 2.1, height: 1.5)).fill()
            }
        }
        return true
    }
    image.isTemplate = false
    image.accessibilityDescription = presentation.accessibilityValue
    return image
}

private func renderMenuPreview(to path: String) throws {
    let rows: [(ClawdyState, Int, [String])] = [(.working, 5, ["codex", "claude"]), (.ready, 0, []),
        (.attention, 2, ["gemini"]), (.error, 0, []), (.idle, 0, []), (.uncertain, 0, []), (.disconnected, 0, [])]
    let width: CGFloat = 460, sectionHeight: CGFloat = 242
    let image = NSImage(size: NSSize(width: width, height: sectionHeight * 2))
    image.lockFocus()
    for (section, dark) in [false, true].enumerated() {
        let base = CGFloat(section) * sectionHeight
        (dark ? NSColor(calibratedWhite: 0.10, alpha: 1) : NSColor(calibratedWhite: 0.95, alpha: 1)).setFill()
        NSRect(x: 0, y: base, width: width, height: sectionHeight).fill()
        let color = dark ? NSColor.white : NSColor.black
        (dark ? "DARK MENU BAR" : "LIGHT MENU BAR").draw(at: NSPoint(x: 16, y: base + 218), withAttributes: [
            .font: NSFont.systemFont(ofSize: 10, weight: .semibold), .foregroundColor: color.withAlphaComponent(0.55)])
        for (index, row) in rows.enumerated() {
            let y = base + 188 - CGFloat(index) * 28
            let snapshot = ClawdySnapshot(version: 1, instance_id: "preview", revision: 1, state: row.0,
                working_count: row.1, providers: row.2, demo: false, phrase: "", confidence: .reported)
            let presentation = MenuPresentationSignature(snapshot: snapshot, mode: .observe, preferences: ClawdyPreferences(),
                rendererSafeMode: false, collectorSafeMode: false)
            trafficLightImage(presentation).draw(in: NSRect(x: 16, y: y, width: 43, height: 18))
            presentation.barTitle.draw(at: NSPoint(x: 65, y: y + 2), withAttributes: [
                .font: NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .medium), .foregroundColor: color])
            row.0.rawValue.draw(at: NSPoint(x: 355, y: y + 3), withAttributes: [
                .font: NSFont.systemFont(ofSize: 10), .foregroundColor: color.withAlphaComponent(0.55)])
        }
    }
    image.unlockFocus()
    guard let tiff = image.tiffRepresentation, let bitmap = NSBitmapImageRep(data: tiff),
          let png = bitmap.representation(using: .png, properties: [:]) else { throw ClawdyProtocolError.invalidSnapshot }
    try png.write(to: URL(fileURLWithPath: path))
}

private enum PipeReadResult { case bytes(Data), notReady, end }
private func readPipeChunk(_ descriptor: Int32) -> PipeReadResult {
    var bytes = [UInt8](repeating: 0, count: 4096)
    let amount = Darwin.read(descriptor, &bytes, bytes.count)
    if amount > 0 { return .bytes(Data(bytes.prefix(amount))) }
    if amount < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) { return .notReady }
    return .end
}

// A stalled child can fill a pipe. All writes are nonblocking, with at most
// three coalesced message types plus one partial frame retained.
private final class PipeWriter {
    private let queue = DispatchQueue(label: "com.clawdy.prototype.pipe-writer")
    private var descriptor: Int32
    private var pending: [String: Data] = [:]
    private var partial = Data()
    private var timer: DispatchSourceTimer?
    private var closed = false
    private let stateLock = NSLock()

    init(handle: FileHandle) {
        descriptor = dup(handle.fileDescriptor)
        let flags = fcntl(descriptor, F_GETFL)
        _ = fcntl(descriptor, F_SETFL, flags | O_NONBLOCK)
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now(), repeating: .milliseconds(100))
        timer.setEventHandler { [weak self] in self?.flush() }
        self.timer = timer; timer.resume()
    }

    func send(_ message: ParentMessage) {
        guard ["snapshot", "preferences", "ping"].contains(message.type),
              let data = try? encodedLine(message), data.count <= 65_537 else { return }
        stateLock.lock(); defer { stateLock.unlock() }
        guard !closed else { return }
        // No per-message dispatch blocks: even a noisy producer retains only
        // the latest three messages. The fixed timer performs the actual write.
        pending[message.type] = data
    }

    private func flush() {
        stateLock.lock(); defer { stateLock.unlock() }
        guard !closed else { return }
        if partial.isEmpty {
            for key in ["preferences", "snapshot", "ping"] {
                if let frame = pending.removeValue(forKey: key) { partial = frame; break }
            }
        }
        guard !partial.isEmpty else { return }
        let written = partial.withUnsafeBytes { raw in
            Darwin.write(descriptor, raw.baseAddress, raw.count)
        }
        if written > 0 { partial.removeFirst(written) }
        else if written < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR { shutdownOnQueue() }
    }

    private func shutdownOnQueue() {
        guard !closed else { return }
        closed = true; pending.removeAll(); partial.removeAll()
        timer?.cancel(); timer = nil
        if descriptor >= 0 { Darwin.close(descriptor); descriptor = -1 }
    }

    func close() {
        queue.async { [weak self] in
            guard let self = self else { return }
            self.stateLock.lock(); defer { self.stateLock.unlock() }
            self.shutdownOnQueue()
        }
    }
    deinit { timer?.cancel(); if descriptor >= 0 { Darwin.close(descriptor) } }
}

private final class OwnedChild {
    let process = Process()
    let output = Pipe()
    var input: Pipe?
    var writer: PipeWriter?
    var framer = NDJSONFramer()
    var expectedStop = false
    let role: String
    let deliverySlot = DispatchSemaphore(value: 1)
    init(_ role: String) { self.role = role }
}

private final class ClawdyHost: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private let diagnostics: Bool
    private var diagnosticLines = 0
    private var mode: CollectorMode
    private var preferences = ClawdyPreferences()
    private var overlayEnabled: Bool
    private var manualReducedMotion = false
    private var statusItem: NSStatusItem!
    private var menuPresentation: MenuPresentationSignature?
    private var details: ClawdyAttentionController?
    private var statusLine = NSMenuItem(title: "Starting…", action: nil, keyEquivalent: "")
    private var demoItem: NSMenuItem!
    private var observeItem: NSMenuItem!
    private var hideItem: NSMenuItem!
    private var pauseItem: NSMenuItem!
    private var motionItem: NSMenuItem!
    private var moveItem: NSMenuItem!
    private var updateItem: NSMenuItem!
    private var automaticUpdateItem: NSMenuItem!
    private var restartUpdateItem: NSMenuItem!
    private let updateStatus = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    private var updateTimer: Timer?
    private var stagedUpdate: URL?
    private var collector: OwnedChild?
    private var renderer: OwnedChild?
    private var children: [OwnedChild] = []
    private var collectorBudget = RestartBudget()
    private var rendererBudget = RestartBudget()
    private var collectorGeneration = 0
    private var rendererGeneration = 0
    private var collectorRestart: RestartTicket?
    private var rendererRestart: RestartTicket?
    private var tracker = SnapshotTracker()
    private var renderedSnapshot: ClawdySnapshot?
    private var lastPong = uptime()
    private var nonce = 0
    private var lastPingNonce = 0
    private var rendererStarted = uptime()
    private var collectorStarted = uptime()
    private var badCollectorFrames = 0
    private var rendererSafeMode = false
    private var collectorSafeMode = false
    private var watchdog = HostWatchdog()
    private var sleeping: Bool { watchdog.sleeping }
    private var closing = false
    private var timer: Timer?
    private var signalSources: [DispatchSourceSignal] = []
    private var quitAfter: TimeInterval?

    init(mode: CollectorMode, diagnostics: Bool, quitAfter: TimeInterval?, overlayEnabled: Bool = false) {
        self.mode = mode; self.diagnostics = diagnostics; self.quitAfter = quitAfter
        self.overlayEnabled = overlayEnabled
        super.init()
    }

    private func log(_ event: String) {
        guard diagnostics && diagnosticLines < 128 else { return }
        diagnosticLines += 1
        let line = Data(("virtual-clawdy " + String(event.prefix(180)) + "\n").utf8)
        line.withUnsafeBytes { raw in _ = Darwin.write(STDERR_FILENO, raw.baseAddress, raw.count) }
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        buildMenu()
        log("host launch pid=\(getpid()) mode=\(mode.rawValue) overlay=\(overlayEnabled) ephemeral=true")
        refreshMotion()
        let center = NSWorkspace.shared.notificationCenter
        center.addObserver(self, selector: #selector(willSleep), name: NSWorkspace.willSleepNotification, object: nil)
        center.addObserver(self, selector: #selector(didWake), name: NSWorkspace.didWakeNotification, object: nil)
        center.addObserver(self, selector: #selector(motionChanged), name: NSWorkspace.accessibilityDisplayOptionsDidChangeNotification, object: nil)
        for number in [SIGTERM, SIGINT] {
            signal(number, SIG_IGN)
            let source = DispatchSource.makeSignalSource(signal: number, queue: .main)
            source.setEventHandler { [weak self] in self?.quit() }
            signalSources.append(source); source.resume()
        }
        watchdog.resume(at: uptime())
        startCollector(); startRenderer()
        timer = Timer(timeInterval: 1, repeats: true) { [weak self] _ in self?.tick() }
        RunLoop.main.add(timer!, forMode: .common)
        if quitAfter == nil {
            updateTimer = Timer.scheduledTimer(withTimeInterval: 3600, repeats: true) { [weak self] _ in
                self?.stageAutomaticUpdate()
            }
            stageAutomaticUpdate()
        }
        if let interval = quitAfter {
            DispatchQueue.main.asyncAfter(deadline: .now() + interval) { [weak self] in self?.quit() }
        }
    }

    private func item(_ title: String, _ action: Selector, key: String = "") -> NSMenuItem {
        let result = NSMenuItem(title: title, action: action, keyEquivalent: key)
        result.target = self; return result
    }

    private func buildMenu() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.menu = makeMenu()
        if let button = statusItem.button { details = ClawdyAttentionController(button: button) }
        updateMenu()
    }

    // The same detached menu is used by acceptance fixtures. Constructing it
    // neither adds a status item nor starts any child processes.
    private func makeMenu() -> NSMenu {
        let menu = NSMenu()
        menu.delegate = self
        menu.autoenablesItems = false
        let title = NSMenuItem(title: "Clawdy", action: nil, keyEquivalent: "")
        title.isEnabled = false; menu.addItem(title)
        statusLine.isEnabled = false; menu.addItem(statusLine)
        menu.addItem(.separator())
        demoItem = item("Demo — simulated activity", #selector(useDemo)); menu.addItem(demoItem)
        observeItem = item("Observe existing local bridge", #selector(useObserve)); menu.addItem(observeItem)
        menu.addItem(.separator())
        menu.addItem(item("Show status details", #selector(showDetails), key: "d"))
        hideItem = item("Show floating Clawdy", #selector(toggleOverlay)); menu.addItem(hideItem)
        pauseItem = item("Pause animation", #selector(togglePause)); menu.addItem(pauseItem)
        motionItem = item("Reduce motion", #selector(toggleMotion)); menu.addItem(motionItem)
        moveItem = item("Move Clawdy — drag to position", #selector(toggleMove)); menu.addItem(moveItem)
        menu.addItem(item("Restart overlay", #selector(retryRenderer)))
        menu.addItem(item("Retry status collector", #selector(retryCollector)))
        menu.addItem(.separator())
        updateItem = item("Update Clawdy…", #selector(updateClawdy)); menu.addItem(updateItem)
        automaticUpdateItem = item("Automatic Updates", #selector(toggleAutomaticUpdates))
        automaticUpdateItem.state = VirtualUpdate.automatic ? .on : .off
        menu.addItem(automaticUpdateItem)
        restartUpdateItem = item("Restart to Apply Update", #selector(restartWithUpdate))
        restartUpdateItem.isEnabled = false; menu.addItem(restartUpdateItem)
        updateStatus.isEnabled = false; updateStatus.isHidden = true; menu.addItem(updateStatus)
        menu.addItem(.separator())
        let privacy = NSMenuItem(title: "No hooks, hardware or startup changes", action: nil, keyEquivalent: "")
        privacy.isEnabled = false; menu.addItem(privacy)
        menu.addItem(item("Quit Clawdy", #selector(quit), key: "q"))
        return menu
    }

    private func applyMenuControls(_ presentation: MenuPresentationSignature) {
        demoItem.state = presentation.mode == .demo ? .on : .off
        observeItem.state = presentation.mode == .observe ? .on : .off
        hideItem.title = presentation.overlayEnabled ? "Hide floating Clawdy" : "Show floating Clawdy"
        hideItem.state = presentation.overlayEnabled ? .on : .off
        pauseItem.state = presentation.preferences.paused ? .on : .off
        motionItem.state = presentation.preferences.reducedMotion ? .on : .off
        moveItem.state = presentation.preferences.moveMode ? .on : .off
        // Pause/Reduce Motion also control the menu-bar input-needed blink.
        pauseItem.isEnabled = true; motionItem.isEnabled = true
        moveItem.isEnabled = presentation.overlayEnabled
        if let restart = hideItem.menu?.items.first(where: { $0.action == #selector(retryRenderer) }) {
            restart.isEnabled = presentation.overlayEnabled
        }
    }

    private func updateMenu() {
        guard statusItem != nil else { return }
        let now = uptime()
        let value = tracker.presented(at: now, demo: mode == .demo)
        details?.update(snapshot: value, preferences: preferences)
        let presentation = MenuPresentationSignature(snapshot: value, mode: mode, preferences: preferences,
                                                     rendererSafeMode: rendererSafeMode, collectorSafeMode: collectorSafeMode,
                                                     overlayEnabled: overlayEnabled, now: now)
        guard presentation != menuPresentation else { return }
        let controlsUnchanged = menuPresentation?.hasSameControls(as: presentation) ?? false
        menuPresentation = presentation
        statusItem.button?.image = trafficLightImage(presentation)
        // A blink changes only the image. Keep labels, checkmarks, tooltips
        // and accessibility values untouched until their content changes.
        guard !controlsUnchanged else { return }
        applyMenuControls(presentation)
        statusItem.button?.imagePosition = .imageLeading
        statusItem.button?.title = " " + presentation.barTitle
        statusItem.button?.font = NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .medium)
        statusItem.button?.toolTip = presentation.accessibilityValue
        statusItem.button?.setAccessibilityLabel("Clawdy status menu")
        statusItem.button?.setAccessibilityValue(presentation.accessibilityValue)
        statusItem.button?.setAccessibilityHelp("Open the menu to change display controls, choose demo or reported status, or quit.")
        let suffix = rendererSafeMode ? " · Overlay recovery paused" : collectorSafeMode ? " · Collector recovery paused" : ""
        let confidenceLabel = mode == .demo ? "DEMO" : presentation.confidence == .reported ? "REPORTED / UNCONFIRMED" : "CONFIDENCE UNKNOWN"
        statusLine.title = "\(confidenceLabel) · \(value.state.rawValue.capitalized) · \(value.working_count) WIP\(suffix)"
    }

    private func wireRead(_ child: OwnedChild, consumer: @escaping (OwnedChild, Data, TimeInterval) -> Void) {
        let descriptor = child.output.fileHandleForReading.fileDescriptor
        _ = fcntl(descriptor, F_SETFL, fcntl(descriptor, F_GETFL) | O_NONBLOCK)
        child.output.fileHandleForReading.readabilityHandler = { [weak self, weak child] handle in
            guard let self = self, let child = child else { return }
            guard child.deliverySlot.wait(timeout: .now()) == .success else {
                usleep(1_000); return
            }
            // Foundation read(upToCount:) may wait to fill its requested size
            // on a live pipe. A raw nonblocking read delivers tiny pong frames
            // immediately and never waits for 4096 bytes or child EOF.
            let chunk: Data
            switch readPipeChunk(descriptor) {
            case .bytes(let data): chunk = data
            case .notReady: child.deliverySlot.signal(); return
            case .end:
                child.deliverySlot.signal(); handle.readabilityHandler = nil; return
            }
            let readAt = uptime()
            DispatchQueue.main.async { [weak self, child] in
                defer { child.deliverySlot.signal() }
                guard let self = self, !self.closing else { return }
                consumer(child, chunk, readAt)
            }
        }
    }

    private func register(_ child: OwnedChild) {
        children.append(child)
        child.process.standardOutput = child.output
        child.process.standardError = FileHandle.nullDevice
        child.process.terminationHandler = { [weak self, weak child] _ in
            DispatchQueue.main.async {
                guard let self = self, let child = child else { return }
                self.log("\(child.role) exit pid=\(child.process.processIdentifier) code=\(child.process.terminationStatus) expected=\(child.expectedStop)")
                child.output.fileHandleForReading.readabilityHandler = nil
                child.writer?.close()
                self.children.removeAll { $0 === child }
                if self.closing || child.expectedStop { return }
                if self.collector === child { self.collector = nil; self.collectorFailed("exit") }
                if self.renderer === child { self.renderer = nil; self.rendererFailed("exit") }
            }
        }
    }

    private func startCollector() {
        guard !closing, !sleeping, !collectorSafeMode, collector == nil else { return }
        if let ticket = collectorRestart {
            guard ticket.isReady(generation: collectorGeneration, at: uptime(), sleeping: sleeping, closing: closing) else { return }
        }
        collectorRestart = nil
        guard let resource = Bundle.main.resourceURL?.appendingPathComponent("virtual_clawdy.py"),
              FileManager.default.fileExists(atPath: resource.path) else {
            collectorSafeMode = true; log("collector safe-mode reason=missing-resource"); updateMenu(); return
        }
        let child = OwnedChild("collector")
        child.process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        child.process.arguments = ["-u", resource.path, mode == .demo ? "--demo" : "--observe"]
        child.process.standardInput = FileHandle.nullDevice
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        child.process.environment = environment
        tracker = SnapshotTracker(); badCollectorFrames = 0
        register(child); collector = child; collectorStarted = uptime()
        wireRead(child) { [weak self] child, data, readAt in self?.readCollector(child, data, at: readAt) }
        do { try child.process.run(); log("collector launch pid=\(child.process.processIdentifier) mode=\(mode.rawValue)") }
        catch {
            child.expectedStop = true; child.output.fileHandleForReading.readabilityHandler = nil
            children.removeAll { $0 === child }; collector = nil; collectorFailed("launch")
        }
    }

    private func readCollector(_ child: OwnedChild, _ data: Data, at readAt: TimeInterval) {
        guard collector === child else { return }
        do {
            let lines = try child.framer.append(data)
            var latest: ClawdySnapshot?
            for line in lines {
                do {
                    let value = try JSONDecoder().decode(ClawdySnapshot.self, from: line)
                    guard value.demo == (mode == .demo) else { throw ClawdyProtocolError.invalidSnapshot }
                    if try tracker.receive(value, at: readAt) { latest = value }
                    badCollectorFrames = 0
                } catch { badCollectorFrames += 1 }
            }
            if badCollectorFrames >= 5 { collectorFailed("invalid-data"); return }
            if latest != nil { sendSnapshot(tracker.presented(at: uptime(), demo: mode == .demo)) }
            updateMenu()
        } catch { collectorFailed("oversize-frame") }
    }

    private func startRenderer() {
        guard overlayEnabled, !closing, !sleeping, !rendererSafeMode, renderer == nil else { return }
        if let ticket = rendererRestart {
            guard ticket.isReady(generation: rendererGeneration, at: uptime(), sleeping: sleeping, closing: closing) else { return }
        }
        rendererRestart = nil
        let url = Bundle.main.bundleURL.appendingPathComponent("Contents/MacOS/ClawdyRenderer")
        guard FileManager.default.isExecutableFile(atPath: url.path) else {
            rendererSafeMode = true; log("renderer safe-mode reason=missing-executable"); updateMenu(); return
        }
        let child = OwnedChild("renderer")
        let pipe = Pipe(); child.input = pipe; child.process.standardInput = pipe
        child.process.executableURL = url
        register(child); renderer = child; rendererStarted = uptime(); lastPong = uptime()
        wireRead(child) { [weak self] child, data, readAt in self?.readRenderer(child, data, at: readAt) }
        do {
            try child.process.run()
            child.writer = PipeWriter(handle: pipe.fileHandleForWriting)
            try? pipe.fileHandleForWriting.close()
            child.writer?.send(.preferences(preferences))
            child.writer?.send(ParentMessage.rendererSnapshot(tracker.presented(at: uptime(), demo: mode == .demo)))
            log("renderer launch pid=\(child.process.processIdentifier)")
        } catch {
            child.expectedStop = true; child.output.fileHandleForReading.readabilityHandler = nil
            children.removeAll { $0 === child }; renderer = nil; rendererFailed("launch")
        }
    }

    private func readRenderer(_ child: OwnedChild, _ data: Data, at readAt: TimeInterval) {
        guard renderer === child else { return }
        do {
            for line in try child.framer.append(data) {
                let reply = try JSONDecoder().decode(ChildMessage.self, from: line)
                if reply.type == "pong", let acknowledged = reply.nonce,
                   acknowledged > 0 && acknowledged <= lastPingNonce && acknowledged >= lastPingNonce - 2 {
                    lastPong = max(lastPong, readAt)
                }
            }
        } catch { rendererFailed("invalid-output") }
    }

    private func stop(_ child: OwnedChild?) {
        guard let child = child else { return }
        child.expectedStop = true
        child.output.fileHandleForReading.readabilityHandler = nil
        child.writer?.close()
        if child.process.isRunning {
            child.process.terminate()
            DispatchQueue.main.asyncAfter(deadline: .now() + .milliseconds(700)) { [weak self, weak child] in
                guard let child = child, child.process.isRunning else { return }
                self?.log("\(child.role) terminate-escalation pid=\(child.process.processIdentifier)")
                _ = kill(child.process.processIdentifier, SIGKILL)
            }
        }
    }

    private func collectorFailed(_ reason: String) {
        guard !closing else { return }
        let old = collector; collector = nil; stop(old); tracker.invalidateFreshness()
        collectorGeneration += 1; collectorRestart = nil
        publishCurrentStatus()
        guard let delay = collectorBudget.register(at: uptime()) else {
            collectorSafeMode = true; log("collector safe-mode reason=\(reason)"); updateMenu(); return
        }
        log("collector retry reason=\(reason) delay=\(Int(delay))")
        scheduleCollectorRestart(after: delay)
    }

    private func rendererFailed(_ reason: String) {
        guard overlayEnabled, !closing else { return }
        let old = renderer; renderer = nil; stop(old)
        rendererGeneration += 1; rendererRestart = nil
        guard let delay = rendererBudget.register(at: uptime()) else {
            rendererSafeMode = true; log("renderer safe-mode reason=\(reason)"); updateMenu(); return
        }
        log("renderer retry reason=\(reason) delay=\(Int(delay))")
        scheduleRendererRestart(after: delay)
    }

    private func scheduleCollectorRestart(after delay: TimeInterval) {
        let ticket = RestartTicket(generation: collectorGeneration, notBefore: uptime() + delay)
        collectorRestart = ticket
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            guard let self = self, self.collectorRestart == ticket else { return }
            self.startCollector()
        }
    }

    private func scheduleRendererRestart(after delay: TimeInterval) {
        let ticket = RestartTicket(generation: rendererGeneration, notBefore: uptime() + delay)
        rendererRestart = ticket
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            guard let self = self, self.rendererRestart == ticket else { return }
            self.startRenderer()
        }
    }

    private func publishCurrentStatus() {
        sendSnapshot(tracker.presented(at: uptime(), demo: mode == .demo)); updateMenu()
    }

    private func sendSnapshot(_ value: ClawdySnapshot) {
        let value = value.forRenderer()
        if value != renderedSnapshot {
            renderedSnapshot = value
            renderer?.writer?.send(ParentMessage.rendererSnapshot(value))
        }
    }

    private func tick() {
        guard !closing, !sleeping else { return }
        let now = uptime()
        if watchdog.tick(at: now) {
            tracker.invalidateFreshness(); renderedSnapshot = nil
            log("host scheduling-gap recovery-grace")
        }
        // Also service due tickets here: a callback may have been deferred by
        // sleep or delivered just before its monotonic not-before deadline.
        startCollector(); startRenderer()
        sendSnapshot(tracker.presented(at: now, demo: mode == .demo)); updateMenu()
        if let child = renderer, child.process.isRunning {
            nonce += 1; lastPingNonce = nonce
            child.writer?.send(ParentMessage(type: "ping", nonce: nonce))
            if watchdog.timedOut(lastProgress: lastPong, at: now, after: 10) { rendererFailed("main-loop-timeout") }
            else if now - rendererStarted > 600 { rendererBudget.reset() }
        }
        if let child = collector, child.process.isRunning {
            if watchdog.timedOut(lastProgress: tracker.lastReceived ?? collectorStarted, at: now, after: 15) { collectorFailed("snapshot-timeout") }
            else if now - collectorStarted > 600 { collectorBudget.reset() }
        }
    }

    private func refreshPreferences() {
        renderer?.writer?.send(.preferences(preferences)); updateMenu()
    }
    private func refreshMotion() {
        preferences.reducedMotion = manualReducedMotion || NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
        refreshPreferences()
    }
    private func switchMode(_ next: CollectorMode) {
        guard !closing, mode != next else { return }
        mode = next; collectorGeneration += 1; collectorBudget.reset(); collectorSafeMode = false
        collectorRestart = nil
        details?.resetEpisode()
        let old = collector; collector = nil; stop(old); tracker = SnapshotTracker(); badCollectorFrames = 0
        renderedSnapshot = nil
        log("mode change mode=\(mode.rawValue)"); startCollector()
        sendSnapshot(tracker.presented(at: uptime(), demo: mode == .demo)); updateMenu()
    }

    @objc private func useDemo() { switchMode(.demo) }
    @objc private func useObserve() { switchMode(.observe) }
    @objc private func showDetails() {
        DispatchQueue.main.async { [weak self] in self?.details?.showForKeyboard() }
    }
    func menuWillOpen(_ menu: NSMenu) { details?.hideForMenu() }
    func menuDidClose(_ menu: NSMenu) { details?.resumeAfterMenu() }
    @objc private func toggleOverlay() {
        overlayEnabled.toggle(); rendererGeneration += 1
        rendererRestart = nil
        rendererBudget.reset(); rendererSafeMode = false
        preferences.hidden = false; preferences.moveMode = false
        if overlayEnabled { startRenderer() }
        else {
            let old = renderer; renderer = nil; stop(old); renderedSnapshot = nil
        }
        updateMenu()
    }
    @objc private func togglePause() { preferences.paused.toggle(); refreshPreferences() }
    @objc private func toggleMotion() { manualReducedMotion.toggle(); refreshMotion() }
    @objc private func toggleMove() {
        guard overlayEnabled else { return }
        preferences.moveMode.toggle(); preferences.hidden = false; refreshPreferences()
    }
    @objc private func motionChanged() { refreshMotion() }
    @objc private func willSleep() { watchdog.suspend(); details?.suspend() }
    @objc private func didWake() {
        guard !closing else { return }
        watchdog.resume(at: uptime())
        tracker.invalidateFreshness(); renderedSnapshot = nil
        publishCurrentStatus()
        details?.resume()
        // A due retry which fired during sleep remains pending. Launch only
        // its current generation, preserving deadlines and crash safe mode.
        startCollector(); startRenderer()
    }
    @objc private func retryRenderer() {
        guard overlayEnabled else { return }
        rendererGeneration += 1; rendererBudget.reset(); rendererSafeMode = false
        let old = renderer; renderer = nil; stop(old)
        scheduleRendererRestart(after: 1)
    }
    @objc private func retryCollector() {
        collectorGeneration += 1; collectorBudget.reset(); collectorSafeMode = false
        let old = collector; collector = nil; stop(old); tracker = SnapshotTracker()
        publishCurrentStatus()
        scheduleCollectorRestart(after: 1)
    }

    @objc private func updateClawdy() { stageUpdate(manual: true) }

    @objc private func toggleAutomaticUpdates() {
        VirtualUpdate.automatic.toggle()
        automaticUpdateItem.state = VirtualUpdate.automatic ? .on : .off
        stageAutomaticUpdate()
    }

    private func stageAutomaticUpdate() {
        if VirtualUpdate.automatic { stageUpdate(manual: false) }
    }

    private func stageUpdate(manual: Bool) {
        guard !closing, updateItem.isEnabled else { return }
        updateItem.isEnabled = false
        if manual { showUpdateStatus("Checking and preparing updates…") }
        VirtualUpdate.stage { [weak self] reply in
            guard let self, !self.closing else { return }
            self.updateItem.isEnabled = true
            if let app = reply?.stagedApp {
                self.stagedUpdate = app
                self.restartUpdateItem.isEnabled = true
                self.showUpdateStatus("Update ready. Restart when convenient.")
            } else if manual {
                let message = reply?.status == "current" ? "Clawdy is up to date."
                    : reply?.message ?? "Clawdy could not prepare the update. Try again."
                self.showUpdateStatus(message)
            }
        }
    }

    private func showUpdateStatus(_ message: String) {
        updateStatus.title = message
        updateStatus.isHidden = false
    }

    @objc private func restartWithUpdate() {
        guard let app = stagedUpdate, restartUpdateItem.isEnabled else { return }
        restartUpdateItem.isEnabled = false
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = false
        configuration.createsNewApplicationInstance = true
        configuration.arguments = [mode == .demo ? "--demo" : "--observe"]
        if overlayEnabled { configuration.arguments.append("--overlay") }
        NSWorkspace.shared.openApplication(at: app, configuration: configuration) { [weak self] running, error in
            DispatchQueue.main.async {
                guard let self, !self.closing else { return }
                if let running, error == nil, !running.isTerminated,
                   running.processIdentifier != getpid(),
                   running.bundleURL?.resolvingSymlinksInPath() == app.resolvingSymlinksInPath() {
                    self.quit()
                } else {
                    self.restartUpdateItem.isEnabled = true
                    self.showUpdateStatus("Clawdy could not open the update. Try again.")
                }
            }
        }
    }

    @objc private func quit() { NSApp.terminate(nil) }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        cleanup(); return .terminateNow
    }
    func applicationWillTerminate(_ notification: Notification) { cleanup() }

    static func testMenuControls(_ check: (Bool, String) -> Void) {
        let host = ClawdyHost(mode: .demo, diagnostics: false, quitAfter: nil)
        let menu = host.makeMenu()
        let expected: [(String, Selector)] = [
            ("Demo — simulated activity", #selector(useDemo)),
            ("Observe existing local bridge", #selector(useObserve)),
            ("Show status details", #selector(showDetails)),
            ("Show floating Clawdy", #selector(toggleOverlay)),
            ("Pause animation", #selector(togglePause)),
            ("Reduce motion", #selector(toggleMotion)),
            ("Move Clawdy — drag to position", #selector(toggleMove)),
            ("Restart overlay", #selector(retryRenderer)),
            ("Retry status collector", #selector(retryCollector)),
            ("Update Clawdy…", #selector(updateClawdy)),
            ("Automatic Updates", #selector(toggleAutomaticUpdates)),
            ("Restart to Apply Update", #selector(restartWithUpdate)),
            ("Quit Clawdy", #selector(quit))
        ]
        let controls = menu.items.filter { $0.action != nil }
        check(controls.count == expected.count, "exact production menu action count")
        for (entry, specification) in zip(controls, expected) {
            check(entry.title == specification.0 && entry.action == specification.1
                  && (entry.target as? ClawdyHost) === host, "production menu target: \(specification.0)")
        }
        check(controls.last?.keyEquivalent == "q", "quit keyboard equivalent")
        check(controls.first(where: { $0.action == #selector(showDetails) })?.keyEquivalent == "d", "details keyboard equivalent")
        check(menu.items.first?.isEnabled == false && menu.items.contains(where: {
            $0.title == "No hooks, hardware or startup changes" && !$0.isEnabled
        }), "prototype and privacy labels are informational")
        func render(_ mode: CollectorMode = .demo) {
            host.applyMenuControls(MenuPresentationSignature(snapshot: .local(.idle, demo: mode == .demo, phrase: ""),
                mode: mode, preferences: host.preferences, rendererSafeMode: false, collectorSafeMode: false,
                overlayEnabled: host.overlayEnabled))
        }
        func activate(_ selector: Selector) {
            if let entry = controls.first(where: { $0.action == selector }) { _ = host.perform(entry.action) }
        }
        render()
        check(host.demoItem.state == .on && host.observeItem.state == .off, "demo selection checkmark")
        render(.observe)
        check(host.demoItem.state == .off && host.observeItem.state == .on, "observer selection checkmark")
        check(!host.overlayEnabled && host.hideItem.title == "Show floating Clawdy" && host.hideItem.state == .off
              && host.pauseItem.isEnabled && host.motionItem.isEnabled && !host.moveItem.isEnabled,
              "default is menu bar only; bar motion controls available, overlay movement disabled")
        host.startRenderer(); host.retryRenderer(); host.toggleMove()
        check(host.renderer == nil && !host.rendererSafeMode && host.rendererGeneration == 0 && !host.preferences.moveMode,
              "bar-only renderer start/retry/move cannot launch or schedule a child")
        // Enable only fixture state; actual renderer opt-in/quit is covered by
        // the separate owned-process lifecycle test, never this detached menu.
        host.overlayEnabled = true; render()
        check(host.hideItem.title == "Hide floating Clawdy" && host.hideItem.state == .on
              && host.pauseItem.isEnabled && host.moveItem.isEnabled, "optional overlay controls enabled")
        activate(#selector(togglePause)); render()
        check(host.preferences.paused && host.pauseItem.state == .on, "pause action checked")
        activate(#selector(togglePause)); render()
        check(!host.preferences.paused && host.pauseItem.state == .off, "resume action unchecked")
        activate(#selector(toggleMotion)); render()
        check(host.manualReducedMotion && host.preferences.reducedMotion && host.motionItem.state == .on, "manual reduce motion checked")
        activate(#selector(toggleMotion)); render()
        check(!host.manualReducedMotion && host.preferences.reducedMotion == NSWorkspace.shared.accessibilityDisplayShouldReduceMotion,
              "manual motion off respects system preference without changing it")
        activate(#selector(toggleMove)); render()
        check(host.preferences.moveMode && !host.preferences.hidden && host.moveItem.state == .on,
              "move action reveals overlay and checks move mode")
        activate(#selector(toggleMove)); render()
        check(!host.preferences.moveMode && host.moveItem.state == .off, "move action returns to click-through mode")
        host.rendererSafeMode = true
        activate(#selector(toggleOverlay)); render()
        check(!host.overlayEnabled && host.rendererGeneration == 1 && !host.rendererSafeMode && host.renderer == nil
              && host.hideItem.title == "Show floating Clawdy", "hide optional overlay cancels retries and resets recovery state")
        check(host.collector == nil && host.renderer == nil && host.statusItem == nil && host.timer == nil,
              "detached menu fixture starts no children, status item or timer")
    }

    static func testRecovery(_ check: (Bool, String) -> Void) throws {
        let host = ClawdyHost(mode: .demo, diagnostics: false, quitAfter: nil, overlayEnabled: true)
        let now = uptime(), readAt = now - 20
        let collector = OwnedChild("collector"); host.collector = collector
        var value = ClawdySnapshot.local(.working, demo: true, phrase: "fixture")
        value.instance_id = "recovery-fixture"; value.revision = 1; value.working_count = 2
        host.readCollector(collector, try encodedLine(value), at: readAt)
        check(host.tracker.lastReceived == readAt && host.renderedSnapshot?.state == .disconnected,
              "delayed queued collector bytes cannot renew freshness or show cached working")
        host.collector = nil
        let renderer = OwnedChild("renderer"); host.renderer = renderer
        host.lastPingNonce = 2; host.lastPong = readAt - 1
        host.readRenderer(renderer, try encodedLine(ChildMessage(type: "pong", nonce: 2)), at: readAt)
        check(host.lastPong == readAt, "queued renderer ack retains observation time")
        host.renderer = nil
        value.revision = 2; _ = try host.tracker.receive(value, at: now)
        host.willSleep()
        host.startCollector(); host.startRenderer()
        check(host.sleeping && host.collector == nil && host.renderer == nil
              && !host.collectorSafeMode && !host.rendererSafeMode,
              "native sleep handler prevents launches before touching bundle resources")
        host.retryCollector()
        let superseded = host.collectorRestart!
        host.retryCollector()
        let current = host.collectorRestart!
        check(!superseded.isReady(generation: host.collectorGeneration, at: now + 100, sleeping: false, closing: false)
              && current.generation == host.collectorGeneration && host.collector == nil,
              "new native manual retry supersedes earlier callback while asleep")
        host.retryRenderer()
        check(host.rendererRestart != nil, "overlay retry retained during sleep")
        host.toggleOverlay()
        check(!host.overlayEnabled && host.rendererRestart == nil, "hiding overlay cancels pending retry")
        host.collectorSafeMode = true; host.rendererSafeMode = true
        host.didWake()
        check(!host.sleeping && host.tracker.lastReceived == nil && host.renderedSnapshot?.state == .disconnected
              && host.collector == nil && host.renderer == nil && host.collectorRestart == current,
              "injected native wake clears stale light and preserves safe mode and retry deadline")
        host.collectorSafeMode = false
        let future = RestartTicket(generation: host.collectorGeneration, notBefore: uptime() + 100)
        host.collectorRestart = future
        host.startCollector()
        check(host.collector == nil && !host.collectorSafeMode && host.collectorRestart == future,
              "early native launch cannot skip pending restart not-before time")
        host.cleanup()
        check(host.collectorRestart == nil && host.rendererRestart == nil && host.closing,
              "native cleanup invalidates pending retry callbacks")
    }

    private func cleanup() {
        guard !closing else { return }; closing = true
        details?.shutdown(); details = nil
        collectorGeneration += 1; rendererGeneration += 1
        collectorRestart = nil; rendererRestart = nil
        timer?.invalidate(); timer = nil
        updateTimer?.invalidate(); updateTimer = nil
        for source in signalSources { source.cancel() }; signalSources.removeAll()
        NSWorkspace.shared.notificationCenter.removeObserver(self)
        for child in children { stop(child) }
        let deadline = uptime() + 0.8
        while children.contains(where: { $0.process.isRunning }) && uptime() < deadline { usleep(10_000) }
        for child in children where child.process.isRunning { _ = kill(child.process.processIdentifier, SIGKILL) }
        log("host quit cleanup owned-children=\(children.count)")
        if statusItem != nil { NSStatusBar.system.removeStatusItem(statusItem) }
    }
}

// Test-only helper: launched directly by --self-test, before any UI/collector.
private func pipeSelfTestChild(startupDelay: UInt32) -> Never {
    func writeBytes(_ bytes: Data) {
        var offset = 0
        while offset < bytes.count {
            let amount = bytes.withUnsafeBytes {
                Darwin.write(STDOUT_FILENO, $0.baseAddress!.advanced(by: offset), bytes.count - offset)
            }
            if amount > 0 { offset += amount }
            else if errno != EINTR { exit(2) }
        }
    }
    func awaitToken(_ expected: UInt8) {
        var token: UInt8 = 0
        var amount: Int
        repeat { amount = Darwin.read(STDIN_FILENO, &token, 1) } while amount < 0 && errno == EINTR
        guard amount == 1 && token == expected else { exit(2) }
    }
    usleep(startupDelay * 1_000)
    writeBytes(Data("{\"type\":\"ready\"}\n".utf8))
    awaitToken(103); writeBytes(Data("{".utf8))
    awaitToken(114); writeBytes(Data("\"type\":\"pong\",\"nonce\":1}\n".utf8))
    awaitToken(120)
    exit(0)
}

private func selfTest() throws {
    func check(_ value: Bool, _ name: String) {
        if !value { fputs("FAIL: \(name)\n", stderr); exit(1) }
    }
    var framing = NDJSONFramer(maximumBytes: 16)
    check(try framing.append(Data("{\"a\":".utf8)).isEmpty, "fragment retained")
    let frames = try framing.append(Data("1}\n{}\n".utf8))
    check(frames.count == 2, "multiple frames")
    do { _ = try framing.append(Data(repeating: 65, count: 17)); check(false, "oversize rejected") }
    catch ClawdyProtocolError.frameTooLarge { }
    check(try framing.append(Data("{}\n".utf8)) == [Data("{}".utf8)], "framer recovers after partial overflow")
    var exact = NDJSONFramer(maximumBytes: 2)
    check(try exact.append(Data("{}\n\n{}\n".utf8)).count == 2, "exact byte limit and empty frames")
    do { _ = try exact.append(Data("123\n".utf8)); check(false, "complete overflow rejected") }
    catch ClawdyProtocolError.frameTooLarge { }
    check(try exact.append(Data("{}\n".utf8)).count == 1, "framer recovers after complete overflow")
    let raw = Data("{\"version\":1,\"instance_id\":\"fixture\",\"revision\":2,\"state\":\"working\",\"working_count\":12,\"providers\":[\"codex\"],\"demo\":true,\"phrase\":\"Brain go brrr\"}".utf8)
    let snapshot = try JSONDecoder().decode(ClawdySnapshot.self, from: raw)
    try snapshot.validate()
    check(snapshot.effectiveConfidence == .demo, "legacy demo confidence defaults safely")
    check(snapshot.attention_providers == nil, "legacy snapshot omits attention targets safely")
    var targetRecord = try JSONSerialization.jsonObject(with: raw) as! [String: Any]
    for invalidTargets: Any in [NSNull(), ["codex", "codex"], ["untrusted-app"], ["codex"]] {
        targetRecord["attention_providers"] = invalidTargets
        do {
            let invalid = try JSONDecoder().decode(ClawdySnapshot.self, from: JSONSerialization.data(withJSONObject: targetRecord))
            try invalid.validate(); check(false, "invalid/null/duplicate/non-red attention targets rejected")
        } catch { }
    }
    targetRecord["state"] = "attention"; targetRecord["attention_providers"] = ["claude"]
    let targetSnapshot = try JSONDecoder().decode(ClawdySnapshot.self, from: JSONSerialization.data(withJSONObject: targetRecord))
    try targetSnapshot.validate()
    check(targetSnapshot.attention_providers == ["claude"] && targetSnapshot.providers == ["codex"],
          "red target provider remains independent of working provider")
    var confidenceRecord = try JSONSerialization.jsonObject(with: raw) as! [String: Any]
    confidenceRecord["demo"] = false
    let legacyObserve = try JSONDecoder().decode(ClawdySnapshot.self, from: JSONSerialization.data(withJSONObject: confidenceRecord))
    try legacyObserve.validate()
    check(legacyObserve.effectiveConfidence == .unknown, "missing OBS confidence is unknown")
    for confidence in ["reported", "unknown"] {
        confidenceRecord["confidence"] = confidence
        let reported = try JSONDecoder().decode(ClawdySnapshot.self, from: JSONSerialization.data(withJSONObject: confidenceRecord))
        try reported.validate()
        check(reported.state == .working && reported.working_count == 12 && reported.effectiveConfidence.rawValue == confidence,
              "confidence preserves reported state and WIP")
    }
    for invalidConfidence: Any in ["fresh", "confirmed", "demo", NSNull(), false, 7] {
        confidenceRecord["confidence"] = invalidConfidence
        do {
            let malformed = try JSONDecoder().decode(ClawdySnapshot.self, from: JSONSerialization.data(withJSONObject: confidenceRecord))
            try malformed.validate(); check(false, "invalid confidence rejected")
        } catch { }
    }
    var exactSnapshot = targetSnapshot
    exactSnapshot.demo = false; exactSnapshot.confidence = .reported
    let routeID = "11111111-2222-4333-8444-555555555555"
    exactSnapshot.attention_providers = ["codex"]
    exactSnapshot.attention_chats = [ClawdyAttentionChat(provider: "codex", thread_id: routeID)]
    try exactSnapshot.validate()
    check(exactSnapshot.forRenderer().attention_chats == nil, "renderer has no chat routing IDs")
    let initialRendererMessage = ParentMessage.rendererSnapshot(exactSnapshot)
    check(initialRendererMessage.snapshot?.attention_chats == nil, "initial renderer snapshot strips routing")
    check(!String(data: try encodedLine(initialRendererMessage), encoding: .utf8)!.contains(routeID),
          "initial renderer wire has no chat routing ID")
    check(!String(data: try encodedLine(exactSnapshot.forRenderer()), encoding: .utf8)!.contains(routeID), "renderer wire strips chat IDs")
    for bad in ["../thread", routeID + "?hostId=other", "https://example.invalid", "11111111-2222-4333-8444-55555555555Z"] {
        exactSnapshot.attention_chats = [ClawdyAttentionChat(provider: "codex", thread_id: bad)]
        do { try exactSnapshot.validate(); check(false, "invalid chat route rejected") } catch { }
    }
    var exactSnapshotRecord = try JSONSerialization.jsonObject(with: raw) as! [String: Any]
    exactSnapshotRecord["attention_chats"] = NSNull()
    do { _ = try JSONDecoder().decode(ClawdySnapshot.self, from: JSONSerialization.data(withJSONObject: exactSnapshotRecord)); check(false, "null chat routes rejected") } catch { }
    var unicode = snapshot; unicode.phrase = "Café 🦀"
    let unicodeLine = try encodedLine(unicode)
    for split in 0...unicodeLine.count {
        var splitFramer = NDJSONFramer()
        let parts = try splitFramer.append(Data(unicodeLine.prefix(split)))
            + splitFramer.append(Data(unicodeLine.dropFirst(split)))
        check(parts.count == 1, "UTF-8 arbitrary byte split has exactly one frame")
        check(try JSONDecoder().decode(ClawdySnapshot.self, from: parts[0]) == unicode,
              "UTF-8 arbitrary byte split preserves snapshot")
    }
    let invalidCases: [(String, (inout ClawdySnapshot) -> Void)] = [
        ("schema version", { $0.version = 2 }),
        ("empty instance", { $0.instance_id = "" }),
        ("control instance", { $0.instance_id = "bad\u{7f}" }),
        ("UTF-8 instance length", { $0.instance_id = String(repeating: "é", count: 65) }),
        ("negative revision", { $0.revision = -1 }),
        ("count overflow", { $0.working_count = 10_000 }),
        ("unknown app", { $0.providers = ["invented-model"] }),
        ("duplicate apps", { $0.providers = ["codex", "codex"] }),
        ("demo confidence mismatch", { $0.confidence = .reported }),
        ("UTF-8 phrase length", { $0.phrase = String(repeating: "🦀", count: 65) })
    ]
    for (name, mutate) in invalidCases {
        var bad = snapshot; mutate(&bad)
        do { try bad.validate(); check(false, "rejected \(name)") }
        catch ClawdyProtocolError.invalidSnapshot { }
    }
    var tracker = SnapshotTracker()
    check(try tracker.receive(snapshot, at: 10), "valid snapshot")
    check(tracker.presented(at: 12, demo: true).state == .working, "fresh working")
    check(tracker.presented(at: 13, demo: true).state == .uncertain, "stale is not ready")
    check(tracker.presented(at: 20, demo: true).state == .disconnected, "lost link")
    var older = snapshot; older.revision = 1
    check(!(try tracker.receive(older, at: 21)), "old revision ignored")
    check(!(try tracker.receive(snapshot, at: 22)), "same revision cannot replay liveness")
    check(tracker.presented(at: 22, demo: true).state == .disconnected, "replay cannot keep green fresh")
    var restarted = snapshot; restarted.instance_id = "new"; restarted.revision = 0
    check(try tracker.receive(restarted, at: 23), "new instance accepted")
    check(!(try tracker.receive(snapshot, at: 24)), "retired instance rejected")
    tracker.invalidateFreshness()
    check(tracker.presented(at: 24, demo: true).state == .disconnected, "wake invalidates cache")
    var invalid = snapshot; invalid.working_count = -1
    do { try invalid.validate(); check(false, "invalid count rejected") } catch ClawdyProtocolError.invalidSnapshot { }
    invalid = snapshot; invalid.phrase = "private\ncontrol"
    do { try invalid.validate(); check(false, "control text rejected") } catch ClawdyProtocolError.invalidSnapshot { }
    var budget = RestartBudget()
    check(budget.register(at: 0) == 1, "first restart")
    check(budget.register(at: 1) == 2, "second restart")
    check(budget.register(at: 2) == 4, "third restart")
    check(budget.register(at: 3) == nil, "crash loop stops")
    budget.reset(); check(budget.register(at: 4) == 1, "manual retry")
    var watchdog = HostWatchdog()
    watchdog.resume(at: 0)
    check(!watchdog.tick(at: 1), "regular host scheduling needs no recovery grace")
    check(watchdog.tick(at: 19), "eighteen-second scheduling gap detected")
    check(!watchdog.timedOut(lastProgress: 1, at: 19, after: 15), "healthy collector not blamed when host resumes")
    for second in 20...35 { check(!watchdog.tick(at: Double(second)), "regular ticks do not renew grace") }
    check(watchdog.timedOut(lastProgress: 1, at: 35, after: 15), "silent collector still times out after bounded grace")
    check(!watchdog.timedOut(lastProgress: 34, at: 35, after: 15), "new collector progress supersedes recovery floor")
    watchdog.suspend()
    check(!watchdog.tick(at: 1000) && !watchdog.timedOut(lastProgress: 1, at: 1000, after: 10),
          "OS sleep cannot spend watchdog deadline")
    watchdog.resume(at: 1000)
    check(!watchdog.timedOut(lastProgress: 1, at: 1001, after: 10), "wake allows normal ack grace without falsifying last progress")
    for second in 1001...1011 { _ = watchdog.tick(at: Double(second)) }
    check(watchdog.timedOut(lastProgress: 1, at: 1011, after: 10), "frozen renderer still fails after wake grace")
    let retry = RestartTicket(generation: 2, notBefore: 50)
    check(!retry.isReady(generation: 2, at: 49, sleeping: false, closing: false)
          && retry.isReady(generation: 2, at: 50, sleeping: false, closing: false), "restart obeys exact not-before deadline")
    check(!retry.isReady(generation: 3, at: 100, sleeping: false, closing: false)
          && !retry.isReady(generation: 2, at: 100, sleeping: true, closing: false)
          && !retry.isReady(generation: 2, at: 100, sleeping: false, closing: true),
          "superseded, sleeping and closing retries cannot launch")
    try ClawdyHost.testRecovery(check)
    let line = try encodedLine(ParentMessage.preferences(ClawdyPreferences()))
    check(line.last == 10, "commands framed")
    let command = try JSONDecoder().decode(ParentMessage.self, from: line.dropLast())
    check(command.type == "preferences" && command.hidden == false, "preference contract")
    let partialCommand = try JSONDecoder().decode(ParentMessage.self, from: Data("{\"type\":\"preferences\",\"paused\":true}".utf8))
    check(partialCommand.paused == true && partialCommand.hidden == nil && partialCommand.moveMode == nil,
          "partial preferences preserve absent fields")
    let menuBase = MenuPresentationSignature(snapshot: snapshot, mode: .demo, preferences: ClawdyPreferences(),
                                               rendererSafeMode: false, collectorSafeMode: false)
    var sameVisible = snapshot; sameVisible.revision += 100; sameVisible.phrase = "New phrase"
    let menuUnchanged = MenuPresentationSignature(snapshot: sameVisible, mode: .demo, preferences: ClawdyPreferences(),
                                                    rendererSafeMode: false, collectorSafeMode: false)
    check(menuBase == menuUnchanged, "revision and phrase do not invalidate native menu")
    var changed = menuBase; changed.state = .uncertain
    check(changed != menuBase, "stale state invalidates menu")
    changed = menuBase; changed.state = .disconnected
    check(changed != menuBase, "disconnect invalidates menu")
    changed = menuBase; changed.mode = .observe
    check(changed != menuBase, "privacy mode label invalidates menu")
    changed = menuBase; changed.count += 1
    check(changed != menuBase, "WIP count invalidates menu")
    changed = menuBase; changed.providers = ["claude", "gemini"]
    check(changed != menuBase, "AI app changes invalidate accessible status")
    check(menuBase.accessibilityValue.contains("Demo data") && menuBase.accessibilityValue.contains("12 reported in progress")
          && menuBase.accessibilityValue.contains("Codex"), "accessible status includes mode, WIP and actual app name")
    check(changed.accessibilityValue.contains("Claude, Gemini") && !changed.accessibilityValue.contains("GPT"),
          "accessible app names do not infer underlying models")
    check(menuBase.barTitle == "12 WIP · Codex · DEMO" && menuBase.activeLight == 1,
          "working status lights yellow with visible WIP and app")
    let lightStates: [(ClawdyState, Int?)] = [(.attention, 0), (.error, 0), (.working, 1), (.ready, 2),
                                           (.idle, nil), (.uncertain, nil), (.disconnected, nil)]
    var brightness: [ClawdyState: [Double]] = [:]
    for (state, expectedLight) in lightStates {
        var fixture = menuBase; fixture.state = state
        check(fixture.activeLight == expectedLight, "traffic-light semantic mapping: \(state.rawValue)")
        let image = trafficLightImage(fixture)
        check(image.size == NSSize(width: 43, height: 18) && !image.isTemplate,
              "colored native glyph has fixed menu-bar size")
        guard let tiff = image.tiffRepresentation, let bitmap = NSBitmapImageRep(data: tiff) else {
            check(false, "native traffic-light bitmap renders"); continue
        }
        var samples: [Double] = []
        for index in 0..<3 {
            let x = Int((9 + CGFloat(index) * 12) / 43 * CGFloat(bitmap.pixelsWide))
            let y = bitmap.pixelsHigh / 2
            guard let color = bitmap.colorAt(x: x, y: y)?.usingColorSpace(.deviceRGB) else {
                check(false, "native light color sample available"); continue
            }
            samples.append(Double(color.redComponent + color.greenComponent + color.blueComponent))
        }
        brightness[state] = samples
    }
    if let off = brightness[.idle] {
        for (state, light) in lightStates {
            guard let light = light, let lit = brightness[state], off.count == 3 && lit.count == 3 else { continue }
            check(lit[light] > off[light] + 0.4, "active native light visibly brighter: \(state.rawValue)")
            for index in 0..<3 where index != light {
                check(abs(lit[index] - off[index]) < 0.05, "other native lights remain dim")
            }
        }
    }
    var attentionSnapshot = snapshot; attentionSnapshot.state = .attention
    func attentionPresentation(at now: TimeInterval, preferences: ClawdyPreferences = ClawdyPreferences()) -> MenuPresentationSignature {
        MenuPresentationSignature(snapshot: attentionSnapshot, mode: .demo, preferences: preferences,
            rendererSafeMode: false, collectorSafeMode: false, now: now)
    }
    let attentionOn = attentionPresentation(at: 0.25), attentionOff = attentionPresentation(at: 1.25)
    check(attentionOn.activeLight == 0 && attentionOff.activeLight == nil && attentionOn != attentionOff,
          "existing one-second clock alternates input-needed red light")
    check(attentionOn.hasSameControls(as: attentionOff), "blink refreshes only the native image, not menu or AX setters")
    check(attentionPresentation(at: 2.25) == attentionOn, "input-needed blink repeats every two seconds")
    check(attentionOn.barTitle.hasPrefix("Input · ") && attentionOff.barTitle == attentionOn.barTitle
          && attentionOff.accessibilityValue == attentionOn.accessibilityValue
          && attentionOff.accessibilityValue.contains("Input needed. Red light blinking"),
          "input qualifier and spoken status remain stable through off phase")
    var errorSnapshot = snapshot; errorSnapshot.state = .error
    let errorOn = MenuPresentationSignature(snapshot: errorSnapshot, mode: .demo, preferences: ClawdyPreferences(),
        rendererSafeMode: false, collectorSafeMode: false, now: 0.25)
    let errorLater = MenuPresentationSignature(snapshot: errorSnapshot, mode: .demo, preferences: ClawdyPreferences(),
        rendererSafeMode: false, collectorSafeMode: false, now: 1.25)
    check(errorOn == errorLater && errorOn.activeLight == 0 && errorOn.barTitle.hasPrefix("Error · "),
          "error red is solid and visibly distinguished from input-needed")
    for state in ClawdyState.allCases where state != .attention {
        var staticSnapshot = snapshot; staticSnapshot.state = state
        let early = MenuPresentationSignature(snapshot: staticSnapshot, mode: .demo, preferences: ClawdyPreferences(),
            rendererSafeMode: false, collectorSafeMode: false, now: 0.25)
        let later = MenuPresentationSignature(snapshot: staticSnapshot, mode: .demo, preferences: ClawdyPreferences(),
            rendererSafeMode: false, collectorSafeMode: false, now: 1.25)
        check(early == later, "static status avoids blink-driven menu rebuild: \(state.rawValue)")
    }
    for pause in [false, true] {
        var motionPreferences = ClawdyPreferences()
        if pause { motionPreferences.paused = true } else { motionPreferences.reducedMotion = true }
        let staticOn = attentionPresentation(at: 0.25, preferences: motionPreferences)
        let staticOff = attentionPresentation(at: 1.25, preferences: motionPreferences)
        check(staticOn == staticOff && staticOff.activeLight == 0 && staticOff.barTitle.hasPrefix("Input · ")
              && !staticOff.accessibilityValue.contains("blinking"),
              "pause or reduced motion gives steady red with input qualifier")
    }
    if let tiff = trafficLightImage(attentionOff).tiffRepresentation, let bitmap = NSBitmapImageRep(data: tiff),
       let color = bitmap.colorAt(x: bitmap.pixelsWide * 9 / 43, y: bitmap.pixelsHigh / 2)?.usingColorSpace(.deviceRGB),
       let idle = brightness[.idle]?.first {
        check(abs(Double(color.redComponent + color.greenComponent + color.blueComponent) - idle) < 0.05,
              "native input-needed off-phase bitmap actually dims red")
    } else { check(false, "native input-needed off-phase bitmap renders") }
    changed = menuBase; changed.mode = .observe; changed.confidence = .reported; changed.providers = ["codex", "claude", "gemini"]
    check(changed.barTitle == "12 WIP · Codex+2" && changed.accessibilityValue.contains("liveness unconfirmed"),
          "reported app summary compact with honest uncertainty badge")
    let reportedPresentation = changed
    changed.confidence = .unknown
    check(changed != reportedPresentation && changed.accessibilityValue.contains("confidence unknown")
          && changed.activeLight == 1, "unknown confidence refreshes AX without hiding last reported light")
    changed.state = .uncertain
    check(changed.barTitle == "Stale · OBS" && changed.activeLight == nil, "stale source cannot show a ready light or old WIP")
    changed.state = .disconnected
    check(changed.barTitle == "Offline · OBS" && changed.activeLight == nil, "lost source shows offline and unlit lights")
    changed = menuBase; changed.count = 9999; changed.providers = Array(ClawdySnapshot.allowedProviders).sorted()
    check(changed.barTitle.count < 45 && changed.barTitle.contains("9999 WIP"), "maximum WIP and multiple apps stay bounded")
    changed = menuBase; changed.overlayEnabled = true
    check(changed != menuBase, "optional overlay mode invalidates menu controls")
    changed = menuBase; changed.preferences.hidden = true
    check(changed != menuBase, "hide preference invalidates menu")
    changed = menuBase; changed.preferences.paused = true
    check(changed != menuBase, "pause preference invalidates menu")
    changed = menuBase; changed.preferences.reducedMotion = true
    check(changed != menuBase, "reduced motion invalidates menu")
    changed = menuBase; changed.preferences.moveMode = true
    check(changed != menuBase, "move mode invalidates menu")
    changed = menuBase; changed.rendererSafeMode = true
    check(changed != menuBase, "renderer recovery status invalidates menu")
    changed = menuBase; changed.collectorSafeMode = true
    check(changed != menuBase, "collector recovery status invalidates menu")
    ClawdyHost.testMenuControls(check)
    let pipe = Pipe()
    let writer = PipeWriter(handle: pipe.fileHandleForWriting)
    try pipe.fileHandleForWriting.close()
    let readFD = pipe.fileHandleForReading.fileDescriptor
    _ = fcntl(readFD, F_SETFL, fcntl(readFD, F_GETFL) | O_NONBLOCK)
    writer.send(.preferences(ClawdyPreferences()))
    for revision in 0..<1_000 {
        var update = snapshot; update.revision = revision
        writer.send(ParentMessage.rendererSnapshot(update))
    }
    writer.send(ParentMessage(type: "ping", nonce: 7))
    var reader = NDJSONFramer()
    var decoded: [ParentMessage] = []
    let deadline = uptime() + 1.2
    while uptime() < deadline {
        var bytes = [UInt8](repeating: 0, count: 4096)
        let amount = Darwin.read(readFD, &bytes, bytes.count)
        if amount > 0 {
            for frame in try reader.append(Data(bytes.prefix(amount))) {
                decoded.append(try JSONDecoder().decode(ParentMessage.self, from: frame))
            }
        }
        if decoded.contains(where: { $0.snapshot?.revision == 999 }) && decoded.contains(where: { $0.nonce == 7 }) { break }
        usleep(10_000)
    }
    writer.close()
    check(decoded.contains(where: { $0.type == "preferences" }), "preferences delivered")
    check(decoded.contains(where: { $0.snapshot?.revision == 999 }), "coalesced latest snapshot delivered")
    check(decoded.count < 20, "producer burst coalesced without a message backlog")
    check(decoded.contains(where: { $0.nonce == 7 }), "ping delivered")
    // Fill a real kernel pipe before constructing the writer. A stalled
    // renderer must not block producers, and the latest coalesced state must
    // arrive once the reader resumes. Blank lines are valid ignored framing.
    let blockedPipe = Pipe()
    let blockedFD = blockedPipe.fileHandleForWriting.fileDescriptor
    _ = fcntl(blockedFD, F_SETFL, fcntl(blockedFD, F_GETFL) | O_NONBLOCK)
    let padding = [UInt8](repeating: 10, count: 4096)
    var filled = 0
    while filled < 8_388_608 {
        let amount = padding.withUnsafeBytes { Darwin.write(blockedFD, $0.baseAddress, $0.count) }
        if amount > 0 { filled += amount }
        else { break }
    }
    check(filled > 0 && (errno == EAGAIN || errno == EWOULDBLOCK), "kernel pipe is actually full")
    let blockedWriter = PipeWriter(handle: blockedPipe.fileHandleForWriting)
    try blockedPipe.fileHandleForWriting.close()
    let burstStart = uptime()
    blockedWriter.send(.preferences(ClawdyPreferences()))
    for revision in 1_000..<2_000 {
        var update = snapshot; update.revision = revision
        blockedWriter.send(ParentMessage.rendererSnapshot(update))
    }
    blockedWriter.send(ParentMessage(type: "ping", nonce: 55))
    check(uptime() - burstStart < 1, "full pipe does not block producer burst")
    usleep(150_000)
    let resumedFD = blockedPipe.fileHandleForReading.fileDescriptor
    _ = fcntl(resumedFD, F_SETFL, fcntl(resumedFD, F_GETFL) | O_NONBLOCK)
    var resumedFramer = NDJSONFramer(); var resumed: [ParentMessage] = []
    let resumeDeadline = uptime() + 1.5
    while uptime() < resumeDeadline {
        if case .bytes(let bytes) = readPipeChunk(resumedFD) {
            for frame in try resumedFramer.append(bytes) {
                resumed.append(try JSONDecoder().decode(ParentMessage.self, from: frame))
            }
        } else { usleep(5_000) }
        if resumed.contains(where: { $0.snapshot?.revision == 1999 }) && resumed.contains(where: { $0.nonce == 55 }) { break }
    }
    blockedWriter.close()
    check(resumed.contains(where: { $0.type == "preferences" }) && resumed.contains(where: { $0.snapshot?.revision == 1999 })
          && resumed.contains(where: { $0.nonce == 55 }), "full pipe recovers preferences, latest state and ping")
    check(resumed.count <= 4, "full pipe retains bounded coalesced output")
    // Separate native-child startup from the unchanged one-second read budget.
    // Handshake-controlled fragments guarantee that success requires a complete
    // NDJSON frame while the child still owns its open stdout pipe.
    for startupDelay in [0, 1_200] {
        let child = Process(); let childInput = Pipe(); let childOutput = Pipe()
        child.executableURL = URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL
        child.arguments = ["--self-test-pipe-child", String(startupDelay)]
        child.standardInput = childInput; child.standardOutput = childOutput
        child.standardError = FileHandle.nullDevice
        try child.run()
        defer {
            try? childInput.fileHandleForWriting.close()
            if child.isRunning { child.terminate() }
            let stopDeadline = uptime() + 0.3
            while child.isRunning && uptime() < stopDeadline { usleep(5_000) }
            if child.isRunning { _ = kill(child.processIdentifier, SIGKILL) }
            try? childOutput.fileHandleForReading.close()
        }
        try childInput.fileHandleForReading.close()
        try childOutput.fileHandleForWriting.close()
        let childFD = childOutput.fileHandleForReading.fileDescriptor
        check(fcntl(childFD, F_SETFL, fcntl(childFD, F_GETFL) | O_NONBLOCK) == 0,
              "fixture output is nonblocking")
        var childFramer = NDJSONFramer(maximumBytes: 128)
        func readFrame(until deadline: TimeInterval) throws -> Data? {
            while uptime() < deadline {
                switch readPipeChunk(childFD) {
                case .bytes(let bytes):
                    if let frame = try childFramer.append(bytes).first { return frame }
                case .notReady: usleep(5_000)
                case .end: return nil
                }
            }
            return nil
        }
        let readyFrame = try readFrame(until: uptime() + 5)
        let ready = readyFrame.flatMap { try? JSONDecoder().decode(ChildMessage.self, from: $0) }
        check(ready?.type == "ready", "native fixture startup handshake")
        let readDeadline = uptime() + 1
        try childInput.fileHandleForWriting.write(contentsOf: Data([103])) // g: first fragment
        var prefix = Data()
        while uptime() < readDeadline && prefix.isEmpty {
            if case .bytes(let bytes) = readPipeChunk(childFD) { prefix.append(bytes) }
            else { usleep(5_000) }
        }
        check(prefix == Data("{".utf8), "real child first fragment observed")
        check(try childFramer.append(prefix).isEmpty, "partial child frame is retained")
        try childInput.fileHandleForWriting.write(contentsOf: Data([114])) // r: remainder
        let pongFrame = try readFrame(until: readDeadline)
        let pong = pongFrame.flatMap { try? JSONDecoder().decode(ChildMessage.self, from: $0) }
        check(child.isRunning, "tiny frame delivered before child EOF")
        check(pong?.type == "pong" && pong?.nonce == 1, "real child complete small ack delivered")
        try childInput.fileHandleForWriting.write(contentsOf: Data([120])) // x: release child
    }
    print("VirtualClawdy host self-test: UTF-8/framing, validation, freshness/replay, crash budget, detached production menu actions, accessible app status, burst/full-pipe recovery and real-child small-ack reads passed.")
}

@main private enum HostMain {
    static func main() {
        signal(SIGPIPE, SIG_IGN)
        let args = Array(CommandLine.arguments.dropFirst())
        if args.first == "--self-test-pipe-child" {
            guard args.count == 2, let delay = UInt32(args[1]), delay <= 1_200 else { exit(2) }
            pipeSelfTestChild(startupDelay: delay)
        }
        if args.contains("--self-test") {
            do { try selfTest(); return } catch { fputs("Host self-test failed: \(error)\n", stderr); exit(1) }
        }
        if args == ["--attention-self-test"] || args == ["--attention-ui-test"] {
            do { try ClawdyAttentionController.selfTest(showWindows: args == ["--attention-ui-test"]); return }
            catch { fputs("Attention test failed: \(error.localizedDescription)\n", stderr); exit(1) }
        }
        if args.count == 1, let option = args.first, option.hasPrefix("--render-menu-preview=") {
            do { try renderMenuPreview(to: String(option.dropFirst("--render-menu-preview=".count))); return }
            catch { fputs("Menu preview failed: \(error)\n", stderr); exit(1) }
        }
        if args.count == 1, let option = args.first, option.hasPrefix("--render-attention-preview=") {
            do { try ClawdyAttentionController.renderPreview(to: String(option.dropFirst("--render-attention-preview=".count))); return }
            catch { fputs("Attention preview failed: \(error)\n", stderr); exit(1) }
        }
        let allowed = ["--demo", "--observe", "--diagnostics", "--ephemeral", "--overlay"]
        guard args.allSatisfy({ allowed.contains($0) || $0.hasPrefix("--quit-after=") }),
              !(args.contains("--demo") && args.contains("--observe")) else {
            fputs("Usage: VirtualClawdy [--observe | --demo] [--overlay] [--diagnostics] [--ephemeral] [--quit-after=seconds] | --self-test | --render-menu-preview=path\n", stderr); exit(2)
        }
        var duration: TimeInterval? = nil
        if let argument = args.first(where: { $0.hasPrefix("--quit-after=") }) {
            guard let value = Double(argument.dropFirst("--quit-after=".count)), value.isFinite,
                  value > 0, value <= 3600 else { exit(2) }
            duration = value
        }
        let app = NSApplication.shared
        let delegate = ClawdyHost(mode: args.contains("--demo") ? .demo : .observe,
                                  diagnostics: args.contains("--diagnostics"), quitAfter: duration,
                                  overlayEnabled: args.contains("--overlay"))
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
