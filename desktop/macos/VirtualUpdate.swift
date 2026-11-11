import AppKit

final class VirtualUpdate {
    struct Reply: Decodable {
        let status: String
        let revision: String?
        let path: String?
        let message: String?

        var stagedApp: URL? {
            guard status == "ready", let revision, let path, let expected = VirtualUpdate.stagedApp(revision),
                  URL(fileURLWithPath: path).resolvingSymlinksInPath().path == expected.path else { return nil }
            return expected
        }
    }

    private static let preference = "AutomaticVirtualClawdyUpdates"
    private static var cache: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Caches/ClawdyPrototype/Updates")
    }
    static var automatic: Bool {
        get { UserDefaults.standard.bool(forKey: preference) }
        set { UserDefaults.standard.set(newValue, forKey: preference) }
    }

    private static func sourceRevision(in bundle: Bundle) -> String? {
        guard let stamp = bundle.url(forResource: "ClawdySourceRevision", withExtension: nil),
              let raw = try? String(contentsOf: stamp, encoding: .utf8) else { return nil }
        let revision = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        return validRevision(revision) ? revision : nil
    }

    private static func validRevision(_ value: String) -> Bool {
        value.utf8.count == 40 && value.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) }
    }

    private static func stagedApp(_ revision: String, cache: URL = cache) -> URL? {
        guard validRevision(revision) else { return nil }
        let app = cache.appendingPathComponent(revision).appendingPathComponent("VirtualClawdy.app")
        guard app.resolvingSymlinksInPath().path == app.standardizedFileURL.path,
              FileManager.default.isExecutableFile(atPath:
                  app.appendingPathComponent("Contents/MacOS/VirtualClawdy").path),
              let bundle = Bundle(url: app), sourceRevision(in: bundle) == revision else { return nil }
        return app.standardizedFileURL
    }

    static func pendingApp() -> URL? {
        guard automatic, let revision = sourceRevision(in: .main) else { return nil }
        return pendingApp(after: revision, cache: cache)
    }

    static func pendingApp(after current: String, cache: URL) -> URL? {
        guard validRevision(current) else { return nil }
        var revision = current
        var seen: Set<String> = [revision]
        var destination: URL?
        for _ in 0..<16 {
            let marker = cache.appendingPathComponent("pending").appendingPathComponent(revision)
            guard let values = try? marker.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey]),
                  values.isRegularFile == true, values.isSymbolicLink == false,
                  let file = try? FileHandle(forReadingFrom: marker) else { break }
            let data = try? file.read(upToCount: 42)
            try? file.close()
            guard let data, data.count == 41, data.last == 10,
                  let next = String(data: data.dropLast(), encoding: .ascii),
                  seen.insert(next).inserted, let app = stagedApp(next, cache: cache) else { break }
            revision = next; destination = app
        }
        return destination
    }

    static func stage(_ complete: @escaping (Reply?) -> Void) {
        DispatchQueue.global(qos: .utility).async {
            let result = run()
            DispatchQueue.main.async { complete(result) }
        }
    }

    private static func run() -> Reply? {
        guard let script = Bundle.main.url(forResource: "update_virtual_clawdy", withExtension: "py"),
              let revision = sourceRevision(in: .main) else {
            return Reply(status: "unavailable", revision: nil, path: nil,
                         message: "Rebuild from the public Clawdy-Virtual checkout to enable updates.")
        }
        let process = Process()
        let output = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.arguments = ["-I", script.path, "install",
                             "--current", revision,
                             "--app", Bundle.main.bundleURL.path]
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        process.standardInput = FileHandle.nullDevice
        do {
            try process.run()
            let data = output.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            guard process.terminationStatus == 0 else { return nil }
            return try JSONDecoder().decode(Reply.self, from: data)
        } catch { return nil }
    }
}
