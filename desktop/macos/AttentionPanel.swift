import AppKit
import QuartzCore
import ImageIO

private let attentionCardSize = NSSize(width: 332, height: 184)
private let clawdyTerracotta = NSColor(srgbRed: 0.88, green: 0.58, blue: 0.43, alpha: 1)

private enum ClawdyProductArt {
    static let image = load(Bundle.main.url(forResource: "ClawdyProduct", withExtension: "png"))
    static func load(_ url: URL?) -> NSImage? {
        guard let url = url, let source = CGImageSourceCreateWithURL(url as CFURL, nil),
              let thumbnail = CGImageSourceCreateThumbnailAtIndex(source, 0, [
                kCGImageSourceCreateThumbnailFromImageAlways: true,
                kCGImageSourceCreateThumbnailWithTransform: true,
                kCGImageSourceThumbnailMaxPixelSize: 216
              ] as CFDictionary) else { return nil }
        return NSImage(cgImage: thumbnail, size: NSSize(width: thumbnail.width, height: thumbnail.height))
    }
}

private final class ClawdyProductTile: NSView {
    let image: NSImage?
    init(frame: NSRect, image: NSImage?) {
        self.image = image; super.init(frame: frame)
        setAccessibilityElement(true); setAccessibilityRole(.image); setAccessibilityLabel("Clawdy product illustration")
    }
    required init?(coder: NSCoder) { nil }
    override var isOpaque: Bool { false }
    override func draw(_ dirtyRect: NSRect) {
        NSColor(srgbRed: 0.96, green: 0.91, blue: 0.83, alpha: 1).setFill()
        NSBezierPath(roundedRect: bounds, xRadius: 16, yRadius: 16).fill()
        if let image = image, image.size.width > 0, image.size.height > 0 {
            let area = bounds.insetBy(dx: 6, dy: 6)
            let scale = min(area.width / image.size.width, area.height / image.size.height)
            let size = NSSize(width: image.size.width * scale, height: image.size.height * scale)
            image.draw(in: NSRect(x: area.midX - size.width / 2, y: area.midY - size.height / 2, width: size.width, height: size.height))
        } else {
            // Keep branding legible if the bundled image is absent/corrupt.
            ("C" as NSString).draw(at: NSPoint(x: bounds.midX - 11, y: bounds.midY - 18), withAttributes: [
                .font: NSFont.systemFont(ofSize: 30, weight: .bold), .foregroundColor: clawdyTerracotta])
        }
    }
}

// One automatic expansion per red episode. Transport interruptions and new
// revisions are not new episodes; only a confirmed non-red state resets it.
struct AttentionPresentationPolicy {
    private(set) var inRedEpisode = false
    private(set) var consumed = false
    private(set) var dismissed = false

    mutating func observe(_ state: ClawdyState) -> Bool {
        if state == .attention || state == .error {
            if !inRedEpisode { inRedEpisode = true; consumed = false; dismissed = false }
            guard !consumed && !dismissed else { return false }
            consumed = true; return true
        }
        if state == .working || state == .ready || state == .idle { reset() }
        return false
    }
    mutating func dismiss() { if inRedEpisode { dismissed = true; consumed = true } }
    mutating func reset() { inRedEpisode = false; consumed = false; dismissed = false }
}

struct AttentionAppTarget: Equatable {
    let provider: String
    let name: String
    let bundleIdentifier: String

    // All launch destinations are native, fixed bundle identifiers. Status
    // input supplies only a provider enum, never a URL, path or shell command.
    static func forProvider(_ provider: String) -> AttentionAppTarget? {
        switch provider {
        case "codex": return .init(provider: provider, name: "Codex", bundleIdentifier: "com.openai.codex")
        case "claude", "gemini": return .init(provider: provider, name: "Terminal", bundleIdentifier: "com.apple.Terminal")
        case "cursor": return .init(provider: provider, name: "Cursor", bundleIdentifier: "com.todesktop.230313mzl4w4u92")
        default: return nil
        }
    }
    static func candidates(for snapshot: ClawdySnapshot) -> [AttentionAppTarget] {
        guard !snapshot.demo, snapshot.state == .attention || snapshot.state == .error else { return [] }
        return (snapshot.attention_providers ?? []).compactMap(Self.forProvider)
    }
}

private struct AttentionChatTarget: Equatable {
    let threadID: String
    init?(provider: String, threadID: String) {
        guard provider == "codex", threadID.count == 36, let uuid = UUID(uuidString: threadID),
              uuid.uuidString.caseInsensitiveCompare(threadID) == .orderedSame else { return nil }
        self.threadID = uuid.uuidString.lowercased()
    }
    var url: URL { URL(string: "codex://threads/" + threadID)! }
    static func candidates(for snapshot: ClawdySnapshot) -> [AttentionChatTarget] {
        guard !snapshot.demo, snapshot.state == .attention || snapshot.state == .error,
              (snapshot.attention_providers ?? []).contains("codex") else { return [] }
        return (snapshot.attention_chats ?? []).compactMap { AttentionChatTarget(provider: $0.provider, threadID: $0.thread_id) }
    }
}

private enum AttentionAction: Equatable {
    case chat(AttentionChatTarget), app(AttentionAppTarget)
    var identity: String {
        switch self { case .chat(let route): return "chat:" + route.threadID
        case .app(let target): return "app:" + target.bundleIdentifier }
    }
    var failureName: String {
        switch self { case .chat: return "chat"; case .app(let target): return target.name }
    }
}

func attentionPanelFrame(anchor: NSRect, visibleFrame: NSRect, size: NSSize = attentionCardSize) -> NSRect {
    let margin: CGFloat = 8
    let area = visibleFrame.insetBy(dx: min(margin, visibleFrame.width / 4), dy: min(margin, visibleFrame.height / 4))
    let width = min(size.width, area.width), height = min(size.height, area.height)
    return NSRect(x: min(max(anchor.midX - width / 2, area.minX), area.maxX - width),
                  y: min(max(anchor.minY - height - 6, area.minY), area.maxY - height), width: width, height: height)
}

private struct AttentionContent: Equatable {
    let state: ClawdyState
    let count: Int
    let providers: [String]
    let attentionProviders: [String]
    let attentionChats: [AttentionChatTarget]
    let phrase: String
    let demo: Bool
    let confidence: ClawdyConfidence
    let recent: Bool

    init(_ snapshot: ClawdySnapshot, recent: Bool = false) {
        state = snapshot.state; count = snapshot.working_count; providers = snapshot.providers
        attentionProviders = snapshot.attention_providers ?? []; phrase = snapshot.phrase
        attentionChats = AttentionChatTarget.candidates(for: snapshot)
        demo = snapshot.demo; confidence = snapshot.effectiveConfidence
        self.recent = recent
    }
    var heading: String {
        switch state {
        case .attention: return "A little help?"
        case .error: return "Something needs a look"
        case .working: return "Little lights. Big plans."
        case .ready: return "All yours."
        case .idle: return "Enjoying the quiet."
        case .uncertain: return "Waiting for a fresh signal."
        case .disconnected: return "Taking a signal break."
        }
    }
    var accent: NSColor {
        switch state {
        case .attention, .error: return NSColor(srgbRed: 1, green: 0.38, blue: 0.35, alpha: 1)
        case .working: return NSColor(srgbRed: 1, green: 0.77, blue: 0.27, alpha: 1)
        case .ready: return NSColor(srgbRed: 0.36, green: 0.87, blue: 0.55, alpha: 1)
        default: return NSColor(srgbRed: 0.58, green: 0.64, blue: 0.74, alpha: 1)
        }
    }
    var statusLabel: String {
        if recent { return state == .error ? "Recent error" : "Recent request" }
        switch state {
        case .attention: return "Needs input"
        case .error: return "Error"
        case .working: return "Working"
        case .ready: return "Ready"
        case .idle: return "Idle"
        case .uncertain: return "Signal delayed"
        case .disconnected: return "Offline"
        }
    }
    var providerSummary: String {
        let names = ["claude":"Claude", "codex":"Codex", "gemini":"Gemini", "cursor":"Cursor", "other":"Other", "unknown":"Other"]
        let labels = providers.compactMap { names[$0] }.reduce(into: [String]()) { if !$0.contains($1) { $0.append($1) } }
        return "\(count) WIP" + (labels.isEmpty ? "" : "  ·  " + labels.joined(separator: ", "))
    }
    var footer: String {
        if recent { return state == .error ? "Recent error · status changed" : "Recent request · status changed" }
        return demo ? "Demo data · no app actions" : confidence == .reported
            ? "Reported status · session liveness unconfirmed"
            : "Status confidence unknown"
    }
}

private final class AttentionPanel: NSPanel {
    var allowsKeyboardFocus = false
    var onDismiss: (() -> Void)?
    override var canBecomeKey: Bool { allowsKeyboardFocus }
    override var canBecomeMain: Bool { false }
    override func cancelOperation(_ sender: Any?) { onDismiss?() }
}

private final class AttentionSurface: NSView {
    override var isFlipped: Bool { true }
    override var isOpaque: Bool { false }
    override func draw(_ dirtyRect: NSRect) {
        NSColor(srgbRed: 0.075, green: 0.083, blue: 0.10, alpha: 0.97).setFill()
        NSBezierPath(roundedRect: bounds.insetBy(dx: 0.5, dy: 0.5), xRadius: 23, yRadius: 23).fill()
        NSColor.white.withAlphaComponent(0.10).setStroke()
        let line = NSBezierPath(roundedRect: bounds.insetBy(dx: 0.5, dy: 0.5), xRadius: 23, yRadius: 23)
        line.lineWidth = 1; line.stroke()
    }
}

final class ClawdyAttentionController: NSObject {
    private let button: NSStatusBarButton?
    private let panel: AttentionPanel
    private let surface = AttentionSurface(frame: NSRect(origin: .zero, size: attentionCardSize))
    private let productTile: ClawdyProductTile
    private let brand = NSTextField(labelWithString: "Clawdy")
    private let heading = NSTextField(labelWithString: "")
    private let summary = NSTextField(labelWithString: "")
    private let footer = NSTextField(labelWithString: "")
    private let hint = NSTextField(labelWithString: "")
    private let closeButton = NSButton()
    private var actionButtons: [NSButton] = []
    private var targets: [AttentionAppTarget] = []
    private var actions: [AttentionAction] = []
    private var actionsConfigured = false
    private var policy = AttentionPresentationPolicy()
    private var content: AttentionContent?
    private var reducedMotion = false
    private var hoveringButton = false
    private var hoveringPanel = false
    private var ignoreHoverUntilLeave = false
    private var menuSuspended = false
    private var sleepSuspended = false
    private var autoPinned = false
    private var keyboardPresented = false
    private var hoverGeneration = 0
    private var visibilityGeneration = 0
    private var actionGeneration = 0
    private var buttonTracking: NSTrackingArea?
    private var localMonitor: Any?
    private var globalMouseMonitor: Any?
    private var screenObserver: NSObjectProtocol?
    private var frameObserver: NSObjectProtocol?
    private let appAvailable: (String) -> Bool
    private let launchApp: (AttentionAppTarget, @escaping (Bool) -> Void) -> Void
    private let openChat: (URL, @escaping (Bool) -> Void) -> Void
    private let anchorProvider: (() -> (NSRect, NSRect)?)?
    private var presentationRequests = 0
    private let clock: () -> TimeInterval
    private var latestSnapshot: ClawdySnapshot?
    private var retainedAlert: ClawdySnapshot?
    private var pinnedAt: TimeInterval?

    init(button: NSStatusBarButton?, appAvailable: @escaping (String) -> Bool = {
        NSWorkspace.shared.urlForApplication(withBundleIdentifier: $0) != nil
    }, launchApp: @escaping (AttentionAppTarget, @escaping (Bool) -> Void) -> Void = { target, complete in
        guard let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: target.bundleIdentifier) else { complete(false); return }
        let config = NSWorkspace.OpenConfiguration(); config.activates = true
        NSWorkspace.shared.openApplication(at: url, configuration: config) { application, error in complete(application != nil && error == nil) }
    }, openChat: @escaping (URL, @escaping (Bool) -> Void) -> Void = { url, complete in
        guard url.scheme == "codex", url.host == "threads", url.query == nil, url.fragment == nil,
              let app = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.openai.codex") else { complete(false); return }
        let config = NSWorkspace.OpenConfiguration(); config.activates = true
        NSWorkspace.shared.open([url], withApplicationAt: app, configuration: config) { _, error in complete(error == nil) }
    }, anchorProvider: (() -> (NSRect, NSRect)?)? = nil,
       clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime },
       productImage: NSImage? = ClawdyProductArt.image) {
        self.button = button
        self.appAvailable = appAvailable; self.launchApp = launchApp
        self.openChat = openChat
        self.anchorProvider = anchorProvider
        self.clock = clock
        productTile = ClawdyProductTile(frame: NSRect(x: 242, y: 40, width: 72, height: 72), image: productImage)
        panel = AttentionPanel(contentRect: NSRect(origin: .zero, size: attentionCardSize),
            styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: true)
        super.init()
        panel.isReleasedWhenClosed = false; panel.isOpaque = false; panel.backgroundColor = .clear
        panel.hasShadow = true; panel.level = .floating; panel.hidesOnDeactivate = false
        panel.collectionBehavior = [.transient, .ignoresCycle]
        panel.becomesKeyOnlyIfNeeded = true; panel.isMovable = false
        panel.contentView = surface; panel.onDismiss = { [weak self] in self?.dismiss() }
        surface.wantsLayer = true; surface.layer?.cornerRadius = 23; surface.layer?.masksToBounds = true
        let glass = NSVisualEffectView(frame: surface.bounds)
        glass.material = .hudWindow; glass.blendingMode = .withinWindow; glass.state = .active
        glass.appearance = NSAppearance(named: .darkAqua); glass.alphaValue = 0.35
        glass.autoresizingMask = [.width, .height]; surface.addSubview(glass)
        configureLabels()
        let tracking = NSTrackingArea(rect: .zero, options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect],
            owner: self, userInfo: ["surface":"panel"])
        surface.addTrackingArea(tracking)
        if let button = button {
            let tracking = NSTrackingArea(rect: .zero, options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect],
                owner: self, userInfo: ["surface":"button"])
            button.addTrackingArea(tracking); buttonTracking = tracking
            button.postsFrameChangedNotifications = true
            frameObserver = NotificationCenter.default.addObserver(forName: NSView.frameDidChangeNotification,
                object: button, queue: .main) { [weak self] _ in self?.reanchor() }
        }
        screenObserver = NotificationCenter.default.addObserver(forName: NSApplication.didChangeScreenParametersNotification,
            object: nil, queue: .main) { [weak self] _ in self?.reanchor() }
    }

    private func configureLabels() {
        brand.frame = NSRect(x: 22, y: 17, width: 210, height: 17)
        brand.font = .systemFont(ofSize: 12, weight: .semibold); brand.textColor = clawdyTerracotta
        heading.frame = NSRect(x: 22, y: 42, width: 204, height: 42)
        heading.font = .systemFont(ofSize: 17, weight: .semibold); heading.textColor = .white
        summary.frame = NSRect(x: 22, y: 88, width: 204, height: 17)
        summary.font = .monospacedDigitSystemFont(ofSize: 11, weight: .medium)
        footer.frame = NSRect(x: 22, y: 161, width: 288, height: 13)
        footer.font = .systemFont(ofSize: 10); footer.textColor = .white.withAlphaComponent(0.72)
        hint.frame = NSRect(x: 22, y: 124, width: 288, height: 21)
        hint.font = .systemFont(ofSize: 11); hint.textColor = .white.withAlphaComponent(0.75)
        for label in [brand, heading, summary, footer, hint] {
            label.lineBreakMode = .byTruncatingTail; label.maximumNumberOfLines = 1; surface.addSubview(label)
        }
        heading.maximumNumberOfLines = 2; heading.lineBreakMode = .byWordWrapping
        heading.cell?.wraps = true; heading.cell?.usesSingleLineMode = false
        surface.addSubview(productTile)
        closeButton.frame = NSRect(x: 291, y: 12, width: 27, height: 26)
        closeButton.isBordered = false; closeButton.image = NSImage(systemSymbolName: "xmark.circle.fill", accessibilityDescription: "Dismiss status details")
        closeButton.contentTintColor = .white.withAlphaComponent(0.55)
        closeButton.target = self; closeButton.action = #selector(closePressed)
        closeButton.setAccessibilityLabel("Dismiss status details"); closeButton.toolTip = "Dismiss · Esc when focused"
        surface.addSubview(closeButton)
        surface.setAccessibilityElement(true); surface.setAccessibilityRole(.group)
        surface.setAccessibilityLabel("Clawdy status details")
    }

    func update(snapshot: ClawdySnapshot, preferences: ClawdyPreferences) {
        latestSnapshot = snapshot
        reducedMotion = preferences.reducedMotion || preferences.paused
        let red = snapshot.state == .attention || snapshot.state == .error
        let automaticallyExpand = policy.observe(snapshot.state)
        if retainedAlert == nil && red && automaticallyExpand {
            retainedAlert = snapshot; pinnedAt = clock(); autoPinned = true
            display(snapshot: snapshot); present(keyboard: false)
        } else if let retained = retainedAlert {
            // The pending target belongs to the original request until the
            // user acknowledges it, even if another source/route reports red.
            let sameRequest = red && retained.state == snapshot.state && retained.demo == snapshot.demo
                && retained.attention_providers == snapshot.attention_providers
                && retained.attention_chats == snapshot.attention_chats
            if sameRequest { retainedAlert = snapshot }
            var shown = sameRequest ? snapshot : retained
            shown.working_count = snapshot.working_count; shown.providers = snapshot.providers
            display(snapshot: shown, recent: !sameRequest)
        } else {
            display(snapshot: snapshot)
        }
    }

    private func display(snapshot: ClawdySnapshot, recent: Bool = false) {
        let next = AttentionContent(snapshot, recent: recent)
        if content != next {
            if content?.state != next.state || content?.demo != next.demo || content?.attentionProviders != next.attentionProviders
                || content?.attentionChats != next.attentionChats {
                actionGeneration += 1
            }
            content = next; heading.stringValue = next.heading; summary.stringValue = next.providerSummary
            brand.stringValue = "Clawdy · " + next.statusLabel
            brand.setAccessibilityLabel("Clawdy · " + next.statusLabel)
            summary.toolTip = next.providerSummary
            summary.setAccessibilityLabel("Working sessions and apps")
            summary.setAccessibilityValue(next.providerSummary)
            summary.textColor = next.accent; footer.stringValue = next.footer
            heading.setAccessibilityLabel(next.heading)
            configureActions(snapshot: snapshot)
        }
    }

    private func cancelRetention() {
        retainedAlert = nil; pinnedAt = nil
    }

    private func configureActions(snapshot: ClawdySnapshot) {
        let chatTargets = appAvailable("com.openai.codex") ? AttentionChatTarget.candidates(for: snapshot) : []
        let nextTargets = AttentionAppTarget.candidates(for: snapshot).filter {
            appAvailable($0.bundleIdentifier) && (chatTargets.isEmpty || $0.provider != "codex")
        }.reduce(into: [AttentionAppTarget]()) { result, target in
            if !result.contains(where: { $0.bundleIdentifier == target.bundleIdentifier }) { result.append(target) }
        }
        let shown = Array((chatTargets.map { AttentionAction.chat($0) } + nextTargets.map { .app($0) }).prefix(3))
        hint.isHidden = !shown.isEmpty
        hint.stringValue = snapshot.demo ? "Just a rehearsal. No app will open." : (snapshot.state == .attention || snapshot.state == .error)
            ? "Open your AI app to respond." : (snapshot.phrase.isEmpty ? "A small window into your workflow." : snapshot.phrase)
        guard !actionsConfigured || actions != shown else { return }
        let focusedIndex = actionButtons.firstIndex { panel.firstResponder === $0 }
        let focusedIdentity = focusedIndex.flatMap { actions.indices.contains($0) ? actions[$0].identity : nil }
        let preserveFocus = focusedIndex != nil && panel.isKeyWindow
        for action in actionButtons { action.removeFromSuperview() }; actionButtons.removeAll()
        targets = nextTargets; actions = shown; actionsConfigured = true
        let actionWidth = (288 - CGFloat(max(0, shown.count - 1)) * 8) / CGFloat(max(1, shown.count))
        for (index, target) in shown.enumerated() {
            let title: String
            switch target {
            case .chat: title = chatTargets.count > 1 ? "Codex chat \(index + 1)"
                : shown.count <= 2 ? "Open Codex chat" : "Codex chat"
            case .app(let app): title = "Open " + app.name
            }
            let action = NSButton(title: title, target: self, action: #selector(openApp(_:)))
            action.frame = NSRect(x: 22 + CGFloat(index) * (actionWidth + 8), y: 123, width: actionWidth, height: 28)
            action.bezelStyle = .rounded; action.controlSize = .small; action.font = .systemFont(ofSize: 11, weight: .medium)
            action.appearance = NSAppearance(named: .darkAqua); action.tag = index
            action.bezelColor = NSColor(srgbRed: 0.57, green: 0.29, blue: 0.21, alpha: 1)
            action.contentTintColor = NSColor(srgbRed: 1, green: 0.94, blue: 0.86, alpha: 1)
            switch target {
            case .chat:
                action.setAccessibilityLabel(chatTargets.count > 1 ? "Open Codex chat \(index + 1)" : "Open Codex chat")
                action.toolTip = "Open this verified local Codex chat."
                action.setAccessibilityHelp("Opens this Codex thread. Reported attention may be stale.")
            case .app(let app):
                action.toolTip = app.name == "Terminal" ? "Open Terminal. Select the Claude or Gemini CLI session yourself."
                    : "Open \(app.name). Select the relevant chat in the app."
                action.setAccessibilityHelp("Opens the app, not a specific chat or CLI session. Reported attention may be stale.")
            }
            surface.addSubview(action); actionButtons.append(action)
        }
        // Native key loop works after an explicit keyboard/menu request.
        let keyViews: [NSView] = actionButtons + [closeButton]
        for (index, view) in keyViews.enumerated() { view.nextKeyView = keyViews[(index + 1) % keyViews.count] }
        panel.initialFirstResponder = actionButtons.first ?? closeButton
        if preserveFocus {
            let index = focusedIdentity.flatMap { identity in shown.firstIndex(where: { $0.identity == identity }) }
            panel.makeFirstResponder(index.map { actionButtons[$0] } ?? closeButton)
        }
    }

    private func anchor() -> (NSRect, NSRect)? {
        if let provider = anchorProvider { return provider() }
        guard let button = button, let window = button.window, let screen = window.screen else { return nil }
        return (window.convertToScreen(button.convert(button.bounds, to: nil)), screen.visibleFrame)
    }
    private func reanchor() {
        guard panel.isVisible, let (anchor, area) = anchor() else { return }
        panel.setFrame(attentionPanelFrame(anchor: anchor, visibleFrame: area), display: true)
    }
    private func present(keyboard: Bool) {
        presentationRequests += 1
        guard !menuSuspended && !sleepSuspended, content != nil, let (anchor, area) = anchor() else { return }
        hoverGeneration += 1; visibilityGeneration += 1
        keyboardPresented = keyboardPresented || keyboard
        let target = attentionPanelFrame(anchor: anchor, visibleFrame: area)
        let wasVisible = panel.isVisible
        if !wasVisible || keyboard { actionGeneration += 1 }
        panel.layerAnimationsStop()
        let compact = NSRect(x: target.midX - target.width * 0.48, y: target.maxY - target.height * 0.96,
            width: target.width * 0.96, height: target.height * 0.96)
        panel.setFrame(!reducedMotion && !wasVisible ? compact : target, display: true)
        panel.allowsKeyboardFocus = keyboardPresented
        if !wasVisible { panel.alphaValue = reducedMotion ? 1 : 0 }
        panel.orderFrontRegardless()
        if keyboard { panel.makeKeyAndOrderFront(nil); panel.makeFirstResponder(actionButtons.first ?? closeButton) }
        installMonitors()
        if !reducedMotion && !wasVisible {
            NSAnimationContext.runAnimationGroup { context in
                context.duration = 0.18; context.timingFunction = CAMediaTimingFunction(name: .easeOut)
                panel.animator().setFrame(target, display: true)
                panel.animator().alphaValue = 1
            }
        } else { panel.alphaValue = 1 }
    }

    func showForKeyboard() { ignoreHoverUntilLeave = false; present(keyboard: true) }
    func resetEpisode() { policy.reset(); hide(dismissEpisode: false) }
    func hideForMenu() { menuSuspended = true; hideTemporarily() }
    func resumeAfterMenu() { menuSuspended = false; restorePending() }
    func suspend() { sleepSuspended = true; hideTemporarily() }
    func resume() { sleepSuspended = false; restorePending() }
    private func restorePending() {
        if retainedAlert != nil && !menuSuspended && !sleepSuspended { present(keyboard: false) }
    }
    private func hideTemporarily() {
        if retainedAlert == nil { hide(dismissEpisode: false); return }
        hoverGeneration += 1; visibilityGeneration += 1
        hoveringPanel = false; hoveringButton = false; keyboardPresented = false
        panel.allowsKeyboardFocus = false; panel.layerAnimationsStop()
        removeMonitors(); panel.orderOut(nil); panel.alphaValue = 1
    }
    private func dismiss() { hide(dismissEpisode: true) }
    private func hide(dismissEpisode: Bool) {
        let pending = retainedAlert
        let latest = latestSnapshot
        cancelRetention()
        if let latest = latestSnapshot { display(snapshot: latest) }
        hoverGeneration += 1; visibilityGeneration += 1
        actionGeneration += 1
        if dismissEpisode {
            // Acknowledge only the card actually shown. A different active
            // request is bounded by latestSnapshot and remains eligible on the
            // next update; it must not inherit the original card's dismissal.
            let deferred = pending != nil && latest != nil
                && (latest!.state == .attention || latest!.state == .error)
                && (pending!.state != latest!.state || pending!.demo != latest!.demo
                    || pending!.attention_providers != latest!.attention_providers
                    || pending!.attention_chats != latest!.attention_chats)
            if deferred { policy.reset() }
            else {
                if let latest = latest, latest.state == .attention || latest.state == .error {
                    _ = policy.observe(latest.state)
                }
                policy.dismiss()
            }
        }
        hoveringPanel = false
        hoveringButton = anchor()?.0.contains(NSEvent.mouseLocation) ?? false
        if dismissEpisode { ignoreHoverUntilLeave = hoveringButton }
        autoPinned = false; keyboardPresented = false; panel.allowsKeyboardFocus = false
        removeMonitors()
        guard panel.isVisible else { return }
        let generation = visibilityGeneration
        if reducedMotion { panel.orderOut(nil); panel.alphaValue = 1; return }
        NSAnimationContext.runAnimationGroup({ context in
            context.duration = 0.12; context.timingFunction = CAMediaTimingFunction(name: .easeOut)
            panel.animator().alphaValue = 0
        }, completionHandler: { [weak self] in
            guard let self = self, self.visibilityGeneration == generation else { return }
            self.panel.orderOut(nil); self.panel.alphaValue = 1
        })
    }
    @objc private func closePressed() { dismiss() }
    @objc private func openApp(_ sender: NSButton) {
        guard let content = content, !content.demo, content.state == .attention || content.state == .error,
              actions.indices.contains(sender.tag) else { return }
        let target = actions[sender.tag]
        // Only an explicit user click reaches this native application launch.
        let generation = actionGeneration
        let clickedState = content.state
        let complete: (Bool) -> Void = { [weak self] success in
            DispatchQueue.main.async {
                guard let self = self, self.actionGeneration == generation, self.content?.state == clickedState,
                      self.content?.demo == false, self.actions.contains(target) else { return }
                if success { self.dismiss() }
                else {
                    self.heading.stringValue = "Couldn’t open " + target.failureName
                    self.heading.setAccessibilityLabel(self.heading.stringValue)
                    self.footer.stringValue = self.content?.recent == true ? self.content!.footer : "Try opening the app directly."
                }
            }
        }
        switch target {
        case .chat(let route):
            guard content.attentionChats.contains(route) else { return }
            openChat(route.url, complete)
        case .app(let app):
            guard content.attentionProviders.contains(app.provider) else { return }
            launchApp(app, complete)
        }
    }

    @objc func mouseEntered(with event: NSEvent) {
        enter(surface: event.trackingArea?.userInfo?["surface"] as? String ?? "panel")
    }
    private func enter(surface: String) {
        if surface == "button" { hoveringButton = true; ignoreHoverUntilLeave = false }
        else { hoveringPanel = true }
        hoverGeneration += 1
        guard !ignoreHoverUntilLeave else { return }
        let generation = hoverGeneration
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.12) { [weak self] in
            guard let self = self, self.hoverGeneration == generation,
                  self.hoveringButton || self.hoveringPanel, !self.ignoreHoverUntilLeave else { return }
            self.present(keyboard: false)
        }
    }
    @objc func mouseExited(with event: NSEvent) {
        leave(surface: event.trackingArea?.userInfo?["surface"] as? String ?? "panel")
    }
    private func leave(surface: String) {
        if surface == "button" { hoveringButton = false }
        else { hoveringPanel = false }
        hoverGeneration += 1
        if !hoveringButton && !hoveringPanel { ignoreHoverUntilLeave = false }
        let generation = hoverGeneration
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.28) { [weak self] in
            guard let self = self, self.hoverGeneration == generation, !self.hoveringButton, !self.hoveringPanel,
                  !self.keyboardPresented else { return }
            guard !self.autoPinned else { return }
            self.hide(dismissEpisode: false)
        }
    }
    private func installMonitors() {
        guard localMonitor == nil else { return }
        localMonitor = NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown, .keyDown]) { [weak self] event in
            guard let self = self else { return event }
            if event.type == .keyDown {
                if event.keyCode == 53 && self.panel.isKeyWindow { self.dismiss(); return nil }
            } else { self.dismissIfOutside() }
            return event
        }
        // Mouse-only global observation requires no keyboard capture/trust.
        globalMouseMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            DispatchQueue.main.async { self?.dismissIfOutside() }
        }
    }
    private func dismissIfOutside() {
        guard retainedAlert == nil else { return }
        let point = NSEvent.mouseLocation
        if panel.frame.contains(point) { return }
        if let (button, _) = anchor(), button.contains(point) { return }
        dismiss()
    }
    private func removeMonitors() {
        if let monitor = localMonitor { NSEvent.removeMonitor(monitor); localMonitor = nil }
        if let monitor = globalMouseMonitor { NSEvent.removeMonitor(monitor); globalMouseMonitor = nil }
    }
    func shutdown() {
        cancelRetention(); latestSnapshot = nil; content = nil; actions = []; targets = []
        hoverGeneration += 1; visibilityGeneration += 1; removeMonitors()
        panel.orderOut(nil); panel.onDismiss = nil
        if let tracking = buttonTracking { button?.removeTrackingArea(tracking); buttonTracking = nil }
        if let observer = screenObserver { NotificationCenter.default.removeObserver(observer); screenObserver = nil }
        if let observer = frameObserver { NotificationCenter.default.removeObserver(observer); frameObserver = nil }
    }
    deinit { removeMonitors() }

    static func selfTest(showWindows: Bool = false) throws {
        func check(_ condition: Bool, _ message: String) throws {
            if !condition { throw NSError(domain: "ClawdyAttentionTests", code: 1, userInfo: [NSLocalizedDescriptionKey: message]) }
        }
        func pump(_ seconds: TimeInterval) { RunLoop.main.run(until: Date(timeIntervalSinceNow: seconds)) }
        var gate = AttentionPresentationPolicy()
        try check(!gate.observe(.working) && gate.observe(.attention), "red episode automatically expands")
        for _ in 0..<100 { try check(!gate.observe(.attention), "revisions do not reopen") }
        gate.dismiss()
        try check(!gate.observe(.error) && !gate.observe(.disconnected) && !gate.observe(.attention), "dismissal survives red/transport churn")
        try check(!gate.observe(.working) && gate.observe(.error), "confirmed non-red state starts next episode")
        for area in [NSRect(x: -1920, y: 30, width: 1920, height: 1050), NSRect(x: 0, y: 24, width: 1440, height: 876), NSRect(x: 0, y: 0, width: 160, height: 100)] {
            for x in [area.minX - 100, area.midX, area.maxX + 100] {
                let frame = attentionPanelFrame(anchor: NSRect(x: x, y: area.maxY, width: 90, height: 24), visibleFrame: area)
                try check(area.contains(frame), "panel clamped to positive/negative/tiny work area")
            }
        }
        _ = NSApplication.shared
        var pending: [(Bool) -> Void] = []; var launched: [AttentionAppTarget] = []
        var chatURLs: [URL] = []; var pendingChats: [(Bool) -> Void] = []
        let area = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1024, height: 768)
        let controller = ClawdyAttentionController(button: nil, appAvailable: { _ in true }, launchApp: { target, complete in
            launched.append(target); pending.append(complete)
        }, openChat: { url, complete in
            chatURLs.append(url); pendingChats.append(complete)
        }, anchorProvider: showWindows ? { (NSRect(x: area.midX - 60, y: area.maxY + 8, width: 120, height: 22), area) } : nil)
        defer { controller.shutdown() }
        var snapshot = ClawdySnapshot.local(.working, demo: false, phrase: "fixture")
        snapshot.providers = ["claude"]; snapshot.confidence = .reported; snapshot.working_count = 3
        controller.update(snapshot: snapshot, preferences: ClawdyPreferences())
        try check(!controller.panel.isVisible && !controller.panel.canBecomeKey && !controller.panel.canBecomeMain,
            "idle native panel stays hidden and passive")
        try check(controller.surface.bounds.size == attentionCardSize && controller.heading.maximumNumberOfLines == 2
            && !controller.heading.frame.intersects(controller.productTile.frame)
            && !controller.closeButton.frame.intersects(controller.productTile.frame)
            && controller.footer.frame.maxY <= controller.surface.bounds.maxY,
            "branded 332x184 layout keeps title, product, close and status note separate")
        try check(controller.brand.stringValue == "Clawdy · Working", "working state is explicit without relying on lamp colour")
        var crowded = snapshot; crowded.working_count = 9999; crowded.providers = ["claude", "codex", "gemini", "cursor"]
        controller.update(snapshot: crowded, preferences: ClawdyPreferences())
        try check(controller.summary.toolTip == "9999 WIP  ·  Claude, Codex, Gemini, Cursor"
            && controller.summary.accessibilityValue() == controller.summary.toolTip,
            "truncated visual summary preserves all working apps in tooltip and accessibility value")
        controller.update(snapshot: snapshot, preferences: ClawdyPreferences())
        let missingTile = ClawdyProductTile(frame: NSRect(x: 0, y: 0, width: 72, height: 72), image: nil)
        let missingBitmap = missingTile.bitmapImageRepForCachingDisplay(in: missingTile.bounds)
        if let bitmap = missingBitmap { missingTile.cacheDisplay(in: missingTile.bounds, to: bitmap) }
        try check(missingBitmap != nil && ClawdyProductArt.load(nil) == nil,
            "missing product image has a native branded fallback without failure")
        controller.enter(surface: "button"); controller.leave(surface: "button"); pump(0.15)
        try check(controller.presentationRequests == 0, "rapid hover exit cancels pending expansion")
        controller.enter(surface: "button"); pump(0.15)
        try check(controller.presentationRequests == 1, "stable hover opens after dwell")
        if showWindows { try check(controller.panel.isVisible && !controller.panel.isKeyWindow, "hover actual panel visible without key focus") }
        controller.leave(surface: "button"); pump(0.10); controller.enter(surface: "panel"); pump(0.21)
        if showWindows { try check(controller.panel.isVisible, "hover gap crossing does not collapse actual panel") }
        controller.leave(surface: "panel"); pump(0.45)
        try check(!controller.panel.isVisible, "delayed hover exit hides actual panel")
        snapshot.state = .attention; snapshot.attention_providers = ["codex"]
        controller.update(snapshot: snapshot, preferences: ClawdyPreferences()); pump(0.20)
        try check(controller.targets.map(\.provider) == ["codex"] && controller.actionButtons.count == 1,
            "red app target is separate from working Claude app")
        let stableButton = controller.actionButtons[0]
        snapshot.working_count = 8; snapshot.providers = ["gemini"]; snapshot.phrase = "another phrase"
        controller.update(snapshot: snapshot, preferences: ClawdyPreferences())
        try check(controller.actionButtons[0] === stableButton, "WIP/working providers/phrase retain native action focus identity")
        controller.openApp(stableButton)
        try check(launched.count == 1 && launched[0].bundleIdentifier == "com.openai.codex", "fake explicit app action uses fixed Codex bundle")
        pending.removeFirst()(false); pump(0.02)
        try check(controller.heading.stringValue == "Couldn’t open Codex", "launch failure stays visible inline")
        controller.openApp(stableButton)
        controller.dismiss(); snapshot.state = .working
        controller.update(snapshot: snapshot, preferences: ClawdyPreferences())
        snapshot.state = .error; snapshot.attention_providers = ["claude", "gemini"]
        controller.update(snapshot: snapshot, preferences: ClawdyPreferences())
        pending.removeFirst()(true); pump(0.02)
        try check(controller.heading.stringValue == "Something needs a look" && controller.actionButtons.count == 1
            && controller.targets[0].bundleIdentifier == "com.apple.Terminal", "stale completion cannot dismiss new target; Terminal deduplicated")
        controller.dismiss(); pump(0.15)
        snapshot.revision += 1; controller.update(snapshot: snapshot, preferences: ClawdyPreferences())
        snapshot.state = .disconnected; snapshot.attention_providers = []; controller.update(snapshot: snapshot, preferences: ClawdyPreferences())
        snapshot.state = .attention; snapshot.attention_providers = ["codex"]; controller.update(snapshot: snapshot, preferences: ClawdyPreferences())
        try check(!controller.panel.isVisible, "dismissed actual red panel does not reopen through reconnect")
        controller.enter(surface: "button"); pump(0.15)
        try check(!controller.ignoreHoverUntilLeave, "fresh button hover clears dismissal hover lock")
        if showWindows {
            try check(controller.panel.isVisible, "fresh actual hover can reopen dismissed details")
            controller.showForKeyboard(); pump(0.03)
            try check(controller.panel.canBecomeKey && !controller.panel.canBecomeMain, "explicit keyboard opening allows key navigation only")
            controller.panel.cancelOperation(nil); pump(0.15)
            try check(!controller.panel.isVisible, "native Escape/cancel path dismisses")
        }
        let firstID = "11111111-2222-4333-8444-555555555555"
        let secondID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        try check(AttentionChatTarget(provider: "claude", threadID: firstID) == nil
            && AttentionChatTarget(provider: "codex", threadID: "../" + firstID) == nil
            && AttentionChatTarget(provider: "codex", threadID: "https://example.com") == nil,
            "exact chat locally rejects unsupported providers, paths and URL input")
        snapshot.attention_chats = [ClawdyAttentionChat(provider: "codex", thread_id: firstID)]
        controller.update(snapshot: snapshot, preferences: ClawdyPreferences())
        try check(controller.actionButtons.map(\.title) == ["Open Codex chat"] && controller.targets.isEmpty
            && controller.actionButtons[0].frame.width == 288,
            "verified route replaces generic Codex app action with exact chat")
        let chatButton = controller.actionButtons[0]
        snapshot.working_count += 1; snapshot.phrase = "new phrase"; snapshot.providers = ["cursor"]
        controller.update(snapshot: snapshot, preferences: ClawdyPreferences())
        try check(controller.actionButtons[0] === chatButton, "exact route native focus survives count/provider/phrase churn")
        controller.openApp(chatButton)
        try check(chatURLs.count == 1 && chatURLs[0].scheme == "codex" && chatURLs[0].host == "threads"
            && chatURLs[0].path == "/" + firstID && chatURLs[0].query == nil && chatURLs[0].fragment == nil,
            "explicit fake opener receives only locally constructed fixed Codex thread URI")
        pendingChats.removeFirst()(false); pump(0.02)
        try check(controller.heading.stringValue == "Couldn’t open chat", "exact chat launch failure is visible")
        controller.openApp(chatButton)
        controller.dismiss(); snapshot.state = .working
        controller.update(snapshot: snapshot, preferences: ClawdyPreferences())
        snapshot.state = .attention
        snapshot.attention_chats = [ClawdyAttentionChat(provider: "codex", thread_id: secondID)]
        controller.update(snapshot: snapshot, preferences: ClawdyPreferences())
        pendingChats.removeFirst()(false); pump(0.02)
        try check(controller.heading.stringValue == "A little help?", "old exact-route failure cannot overwrite new route")
        controller.dismiss(); snapshot.state = .working
        controller.update(snapshot: snapshot, preferences: ClawdyPreferences()); snapshot.state = .attention
        snapshot.attention_chats = [ClawdyAttentionChat(provider: "codex", thread_id: firstID),
            ClawdyAttentionChat(provider: "codex", thread_id: secondID)]
        controller.update(snapshot: snapshot, preferences: ClawdyPreferences())
        try check(controller.actionButtons.map(\.title) == ["Codex chat 1", "Codex chat 2"]
            && controller.actionButtons.allSatisfy { $0.frame.width == 140 }, "multiple verified chats use distinct numbered buttons")
        controller.dismiss(); snapshot.state = .working
        controller.update(snapshot: snapshot, preferences: ClawdyPreferences()); snapshot.state = .attention
        snapshot.attention_chats?.append(ClawdyAttentionChat(provider: "codex", thread_id: "33333333-4444-4555-8666-777777777777"))
        controller.update(snapshot: snapshot, preferences: ClawdyPreferences())
        try check(controller.actionButtons.count == 3 && controller.actionButtons.allSatisfy {
            $0.frame.minX >= 22 && $0.frame.maxX <= 310
                && ($0.title as NSString).size(withAttributes: [.font: $0.font!]).width <= $0.frame.width - 16
        }, "three named chat actions stay readable inside the card")
        controller.dismiss(); snapshot.state = .working
        controller.update(snapshot: snapshot, preferences: ClawdyPreferences()); snapshot.state = .attention
        snapshot.attention_providers = ["codex", "claude"]
        snapshot.attention_chats = [ClawdyAttentionChat(provider: "codex", thread_id: firstID)]
        controller.update(snapshot: snapshot, preferences: ClawdyPreferences())
        try check(controller.actionButtons.map(\.title) == ["Open Codex chat", "Open Terminal"], "unsupported CLI target retains honest Terminal fallback")
        controller.resetEpisode()
        snapshot.demo = true; snapshot.confidence = .demo
        controller.update(snapshot: snapshot, preferences: ClawdyPreferences())
        let count = launched.count
        let chatCount = chatURLs.count
        controller.openApp(stableButton)
        try check(controller.actionButtons.isEmpty && launched.count == count && chatURLs.count == chatCount, "demo status cannot launch an app or exact chat")
        var preferences = ClawdyPreferences(); preferences.reducedMotion = true
        controller.update(snapshot: snapshot, preferences: preferences)
        try check(controller.reducedMotion, "system/manual reduced-motion input disables finite transitions")
        controller.shutdown()
        try check(controller.localMonitor == nil && controller.globalMouseMonitor == nil && !controller.panel.isVisible,
            "shutdown removes monitors and visible panel")
        var time: TimeInterval = 100
        var recentCallbacks: [(Bool) -> Void] = []
        let sticky = ClawdyAttentionController(button: nil, appAvailable: { _ in true },
            openChat: { _, complete in recentCallbacks.append(complete) }, clock: { time })
        defer { sticky.shutdown() }
        var red = ClawdySnapshot.local(.attention, demo: false, phrase: "fixture request")
        red.confidence = .reported; red.working_count = 5; red.providers = ["codex"]
        red.attention_providers = ["codex"]; red.attention_chats = [ClawdyAttentionChat(provider: "codex", thread_id: firstID)]
        var current = ClawdySnapshot.local(.working, demo: false, phrase: "other work")
        current.confidence = .reported; current.working_count = 2; current.providers = ["gemini"]
        var stillPreferences = ClawdyPreferences(); stillPreferences.reducedMotion = true
        sticky.update(snapshot: red, preferences: stillPreferences)
        let retainedButton = sticky.actionButtons[0]
        for state in [ClawdyState.working, .ready, .disconnected, .uncertain] {
            time += 86_400; current.state = state
            sticky.update(snapshot: current, preferences: stillPreferences)
            try check(sticky.retainedAlert != nil && sticky.pinnedAt == 100 && sticky.autoPinned
                && sticky.actionButtons[0] === retainedButton && sticky.content?.recent == true
                && sticky.summary.stringValue == "2 WIP  ·  Gemini", "source changes and days of elapsed time cannot expire a pending alert")
        }
        sticky.leave(surface: "button"); sticky.leave(surface: "panel"); pump(0.32)
        sticky.dismissIfOutside(); sticky.hideForMenu()
        let beforeResume = sticky.presentationRequests
        sticky.resumeAfterMenu()
        try check(!sticky.menuSuspended && sticky.presentationRequests > beforeResume && !sticky.panel.canBecomeKey, "menu close restores pending card passively")
        try check(sticky.retainedAlert != nil && sticky.autoPinned, "hover leave, outside click and menu opening do not acknowledge alert")
        sticky.openApp(retainedButton); recentCallbacks.removeFirst()(false); pump(0.02)
        try check(sticky.autoPinned && sticky.retainedAlert != nil && !sticky.actionButtons.isEmpty,
            "failed action leaves pending card usable")
        var otherRed = red; otherRed.state = .error
        otherRed.attention_chats = [ClawdyAttentionChat(provider: "codex", thread_id: secondID)]
        sticky.update(snapshot: otherRed, preferences: stillPreferences)
        try check(sticky.retainedAlert?.attention_chats?.first?.thread_id == firstID,
            "another red target cannot replace the unacknowledged route")
        sticky.openApp(retainedButton); recentCallbacks.removeFirst()(true); pump(0.02)
        try check(sticky.retainedAlert == nil && !sticky.autoPinned, "successful action releases pending alert")
        sticky.update(snapshot: otherRed, preferences: stillPreferences)
        try check(sticky.retainedAlert?.attention_chats?.first?.thread_id == secondID,
            "acknowledging original alert leaves a different active request eligible")
        sticky.dismiss()
        sticky.update(snapshot: otherRed, preferences: stillPreferences)
        try check(sticky.retainedAlert == nil, "acknowledged same red request cannot reopen automatically")
        sticky.update(snapshot: current, preferences: stillPreferences)
        // Unknown/offline is not a confirmed new episode. Working is.
        current.state = .working; sticky.update(snapshot: current, preferences: stillPreferences)
        sticky.update(snapshot: red, preferences: stillPreferences)
        sticky.panel.cancelOperation(nil)
        try check(sticky.retainedAlert == nil && !sticky.autoPinned, "explicit Escape/Close path acknowledges pending alert")
        sticky.update(snapshot: red, preferences: stillPreferences)
        try check(sticky.retainedAlert == nil, "explicitly closed red episode stays acknowledged")
        sticky.update(snapshot: current, preferences: stillPreferences); sticky.update(snapshot: red, preferences: stillPreferences)
        sticky.suspend()
        try check(sticky.retainedAlert != nil && sticky.autoPinned && sticky.sleepSuspended, "sleep hides without acknowledging pending route")
        sticky.hideForMenu(); sticky.resume()
        try check(sticky.retainedAlert != nil && sticky.menuSuspended && !sticky.sleepSuspended, "wake does not bypass an open menu")
        sticky.resumeAfterMenu()
        try check(sticky.retainedAlert != nil && !sticky.panel.canBecomeKey, "wake/menu close restore without stealing focus")
        sticky.update(snapshot: current, preferences: stillPreferences); sticky.update(snapshot: red, preferences: stillPreferences)
        stillPreferences.paused = true; sticky.update(snapshot: red, preferences: stillPreferences)
        try check(sticky.retainedAlert != nil && sticky.autoPinned && sticky.reducedMotion, "pause changes motion without acknowledging pending route")
        sticky.resetEpisode(); sticky.shutdown()
        try check(sticky.retainedAlert == nil && sticky.pinnedAt == nil && sticky.latestSnapshot == nil,
            "mode reset and shutdown clear ephemeral identities")
        print("Clawdy attention tests passed: episode/dismissal, geometry, hover dwell/gap/exit, fixed app actions, failures/stale callbacks, stable native buttons, demo guard and cleanup. UI=\(showWindows)")
    }

    static func renderPreview(to path: String, productImageURL: URL? = nil) throws {
        _ = NSApplication.shared
        let product = productImageURL.map { ClawdyProductArt.load($0) } ?? ClawdyProductArt.image
        let controller = ClawdyAttentionController(button: nil, appAvailable: { _ in true }, productImage: product)
        let states = ClawdyState.allCases
        let stride = attentionCardSize.height + 20
        let height = CGFloat(states.count) * stride + 16
        let image = NSImage(size: NSSize(width: 364, height: height)); image.lockFocus()
        NSColor(srgbRed: 0.16, green: 0.18, blue: 0.22, alpha: 1).setFill()
        NSRect(x: 0, y: 0, width: 364, height: height).fill()
        for (index, state) in states.enumerated() {
            controller.resetEpisode()
            var snapshot = ClawdySnapshot.local(state, demo: false, phrase: "A few good ideas are taking shape.")
            snapshot.working_count = state == .working || state == .attention || state == .error ? 5 : 0
            snapshot.providers = snapshot.working_count > 0 ? ["codex", "claude"] : []
            snapshot.confidence = state == .uncertain || state == .disconnected ? .unknown : .reported
            snapshot.attention_providers = state == .attention ? ["claude"] : state == .error ? ["codex"] : []
            if state == .attention { snapshot.providers = ["codex"] }
            if state == .disconnected { snapshot.phrase = "Waiting for local status." }
            if state == .uncertain { snapshot.phrase = "The last report is getting stale." }
            if state == .idle { snapshot.phrase = "A little quiet. A little Clawdy." }
            if state == .ready { snapshot.phrase = "Your next move." }
            controller.update(snapshot: snapshot, preferences: ClawdyPreferences())
            let bitmap = controller.surface.bitmapImageRepForCachingDisplay(in: controller.surface.bounds)!
            controller.surface.cacheDisplay(in: controller.surface.bounds, to: bitmap)
            NSImage(cgImage: bitmap.cgImage!, size: controller.surface.bounds.size).draw(in:
                NSRect(x: 16, y: height - attentionCardSize.height - 16 - CGFloat(index) * stride,
                    width: attentionCardSize.width, height: attentionCardSize.height))
        }
        image.unlockFocus(); controller.shutdown()
        guard let tiff = image.tiffRepresentation, let bitmap = NSBitmapImageRep(data: tiff),
              let png = bitmap.representation(using: .png, properties: [:]) else { throw ClawdyProtocolError.invalidSnapshot }
        try png.write(to: URL(fileURLWithPath: path))
    }
}

private extension NSPanel {
    func layerAnimationsStop() { contentView?.layer?.removeAllAnimations() }
}
