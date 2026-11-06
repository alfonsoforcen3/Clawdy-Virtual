import Foundation

enum ClawdyState: String, Codable, CaseIterable {
    case idle, working, ready, attention, error, disconnected, uncertain
}

enum ClawdyConfidence: String, Codable {
    case demo, reported, unknown
}

struct ClawdyAttentionChat: Codable, Equatable {
    var provider: String
    var thread_id: String

    var isValid: Bool {
        provider == "codex" && UUID(uuidString: thread_id)?.uuidString.lowercased() == thread_id
    }
}

struct ClawdySnapshot: Codable, Equatable {
    var version: Int
    var instance_id: String
    var revision: Int
    var state: ClawdyState
    var working_count: Int
    var providers: [String]
    var demo: Bool
    var phrase: String
    var confidence: ClawdyConfidence? = nil
    var attention_providers: [String]? = nil
    var attention_chats: [ClawdyAttentionChat]? = nil

    var effectiveConfidence: ClawdyConfidence { confidence ?? (demo ? .demo : .unknown) }

    private enum CodingKeys: String, CodingKey {
        case version, instance_id, revision, state, working_count, providers, demo, phrase, confidence, attention_providers, attention_chats
    }

    static let allowedProviders: Set<String> = ["claude", "codex", "gemini", "cursor", "other", "unknown"]

    func validate() throws {
        guard version == 1, !instance_id.isEmpty, instance_id.utf8.count <= 128,
              !instance_id.unicodeScalars.contains(where: { $0.value < 32 || $0.value == 127 }),
              revision >= 0, (0...9999).contains(working_count), providers.count <= 8, Set(providers).count == providers.count,
              providers.allSatisfy({ Self.allowedProviders.contains($0) }),
              (attention_providers ?? []).count <= 8,
              Set(attention_providers ?? []).count == (attention_providers ?? []).count,
              (attention_providers ?? []).allSatisfy({ Self.allowedProviders.contains($0) }),
              (attention_providers ?? []).isEmpty || state == .attention || state == .error,
              (attention_chats ?? []).count <= 3,
              (attention_chats ?? []).allSatisfy({ $0.isValid }),
              Set((attention_chats ?? []).map(\.thread_id)).count == (attention_chats ?? []).count,
              (attention_chats ?? []).isEmpty || (!demo && (state == .attention || state == .error)
                  && (attention_providers ?? []).contains("codex")),
              phrase.utf8.count <= 256,
              !phrase.unicodeScalars.contains(where: { $0.value < 32 || $0.value == 127 }),
              (effectiveConfidence == .demo) == demo else {
            throw ClawdyProtocolError.invalidSnapshot
        }
    }

    func forRenderer() -> ClawdySnapshot {
        var copy = self
        copy.attention_chats = nil
        return copy
    }

    static func local(_ state: ClawdyState, demo: Bool, phrase: String) -> ClawdySnapshot {
        ClawdySnapshot(version: 1, instance_id: "host-placeholder", revision: 0,
                       state: state, working_count: 0, providers: [], demo: demo, phrase: phrase)
    }
}

extension ClawdySnapshot {
    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        version = try values.decode(Int.self, forKey: .version)
        instance_id = try values.decode(String.self, forKey: .instance_id)
        revision = try values.decode(Int.self, forKey: .revision)
        state = try values.decode(ClawdyState.self, forKey: .state)
        working_count = try values.decode(Int.self, forKey: .working_count)
        providers = try values.decode([String].self, forKey: .providers)
        demo = try values.decode(Bool.self, forKey: .demo)
        phrase = try values.decode(String.self, forKey: .phrase)
        // Old v1 snapshots can omit confidence; explicit null/unknown values
        // are malformed. No reported record establishes provider liveness.
        confidence = values.contains(.confidence) ? try values.decode(ClawdyConfidence.self, forKey: .confidence) : nil
        attention_providers = values.contains(.attention_providers) ? try values.decode([String].self, forKey: .attention_providers) : nil
        attention_chats = values.contains(.attention_chats) ? try values.decode([ClawdyAttentionChat].self, forKey: .attention_chats) : nil
    }
}

struct ClawdyPreferences: Codable, Equatable {
    var hidden = false
    var paused = false
    var reducedMotion = false
    var moveMode = false
}

struct ParentMessage: Codable {
    var type: String
    var snapshot: ClawdySnapshot?
    var hidden: Bool?
    var paused: Bool?
    var reducedMotion: Bool?
    var moveMode: Bool?
    var nonce: Int?

    init(type: String, snapshot: ClawdySnapshot? = nil, hidden: Bool? = nil,
         paused: Bool? = nil, reducedMotion: Bool? = nil, moveMode: Bool? = nil, nonce: Int? = nil) {
        self.type = type; self.snapshot = snapshot; self.hidden = hidden
        self.paused = paused; self.reducedMotion = reducedMotion; self.moveMode = moveMode; self.nonce = nonce
    }

    static func rendererSnapshot(_ value: ClawdySnapshot) -> ParentMessage {
        ParentMessage(type: "snapshot", snapshot: value.forRenderer())
    }

    static func preferences(_ value: ClawdyPreferences) -> ParentMessage {
        ParentMessage(type: "preferences", hidden: value.hidden, paused: value.paused,
                      reducedMotion: value.reducedMotion, moveMode: value.moveMode)
    }
}

struct ChildMessage: Codable {
    var type: String
    var nonce: Int?
}

enum ClawdyProtocolError: Error {
    case frameTooLarge, invalidSnapshot
}

struct NDJSONFramer {
    let maximumBytes: Int
    private var pending = Data()
    init(maximumBytes: Int = 65_536) { self.maximumBytes = maximumBytes }

    mutating func append(_ chunk: Data) throws -> [Data] {
        pending.append(chunk)
        var frames: [Data] = []
        while let newline = pending.firstIndex(of: 10) {
            let size = pending.distance(from: pending.startIndex, to: newline)
            guard size <= maximumBytes else { pending.removeAll(); throw ClawdyProtocolError.frameTooLarge }
            let frame = Data(pending[..<newline])
            pending.removeSubrange(...newline)
            if !frame.isEmpty { frames.append(frame) }
        }
        guard pending.count <= maximumBytes else { pending.removeAll(); throw ClawdyProtocolError.frameTooLarge }
        return frames
    }
}

struct SnapshotTracker {
    private(set) var snapshot: ClawdySnapshot?
    private(set) var lastReceived: TimeInterval?
    private var retiredInstances: [String] = []

    mutating func receive(_ value: ClawdySnapshot, at now: TimeInterval) throws -> Bool {
        try value.validate()
        if let old = snapshot {
            if old.instance_id == value.instance_id && value.revision <= old.revision { return false }
            if old.instance_id != value.instance_id {
                guard !retiredInstances.contains(value.instance_id) else { return false }
                retiredInstances.append(old.instance_id)
                if retiredInstances.count > 8 { retiredInstances.removeFirst() }
            }
        }
        snapshot = value; lastReceived = now
        return true
    }

    mutating func invalidateFreshness() { lastReceived = nil }

    func presented(at now: TimeInterval, demo: Bool) -> ClawdySnapshot {
        guard let value = snapshot, let received = lastReceived else {
            return .local(.disconnected, demo: demo, phrase: demo ? "Waking the little brain…" : "Waiting for local status")
        }
        let age = max(0, now - received)
        if age >= 10 { return .local(.disconnected, demo: demo, phrase: "Status link is unavailable") }
        if age >= 3 { return .local(.uncertain, demo: demo, phrase: "Status is getting stale…") }
        return value
    }
}

struct RestartBudget {
    private var failures: [TimeInterval] = []
    mutating func register(at now: TimeInterval) -> TimeInterval? {
        failures.removeAll { now - $0 > 300 }
        failures.append(now)
        guard failures.count <= 3 else { return nil }
        return pow(2, Double(failures.count - 1))
    }
    mutating func reset() { failures.removeAll() }
}

// Watchdogs measure child progress while the host itself is being scheduled.
// A delayed main queue or OS wake earns one normal watchdog interval to drain
// input; this does not change snapshot freshness or certify provider liveness.
struct HostWatchdog {
    private(set) var sleeping = false
    private var lastTick: TimeInterval?
    private var resumedAt: TimeInterval?

    mutating func suspend() { sleeping = true; lastTick = nil }
    mutating func resume(at now: TimeInterval) {
        sleeping = false; lastTick = now; resumedAt = now
    }
    mutating func tick(at now: TimeInterval) -> Bool {
        guard !sleeping else { return false }
        defer { lastTick = now }
        guard let previous = lastTick else { resumedAt = now; return false }
        guard now < previous || now - previous > 5 else { return false }
        resumedAt = now; return true
    }
    func timedOut(lastProgress: TimeInterval, at now: TimeInterval, after timeout: TimeInterval) -> Bool {
        !sleeping && now - max(lastProgress, resumedAt ?? lastProgress) > timeout
    }
}

struct RestartTicket: Equatable {
    let generation: Int
    let notBefore: TimeInterval

    func isReady(generation current: Int, at now: TimeInterval, sleeping: Bool, closing: Bool) -> Bool {
        generation == current && !sleeping && !closing && now >= notBefore
    }
}

func encodedLine<T: Encodable>(_ value: T) throws -> Data {
    var data = try JSONEncoder().encode(value)
    guard data.count <= 65_536 else { throw ClawdyProtocolError.frameTooLarge }
    data.append(10)
    return data
}
