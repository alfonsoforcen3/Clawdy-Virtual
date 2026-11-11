import AppKit

final class VirtualUpdate {
    struct Reply: Decodable {
        let status: String
        let revision: String?
        let path: String?
        let message: String?

        var stagedApp: URL? {
            guard status == "ready", let revision, let path,
                  revision.range(of: "^[a-f0-9]{40}$", options: .regularExpression) != nil else { return nil }
            let expected = FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Library/Caches/ClawdyPrototype/Updates")
                .appendingPathComponent(revision).appendingPathComponent("VirtualClawdy.app")
            let app = URL(fileURLWithPath: path)
            guard app.resolvingSymlinksInPath() == expected.standardizedFileURL,
                  FileManager.default.isExecutableFile(atPath:
                      app.appendingPathComponent("Contents/MacOS/VirtualClawdy").path) else { return nil }
            return expected
        }
    }

    private static let preference = "AutomaticVirtualClawdyUpdates"
    static var automatic: Bool {
        get { UserDefaults.standard.bool(forKey: preference) }
        set { UserDefaults.standard.set(newValue, forKey: preference) }
    }

    static func stage(_ complete: @escaping (Reply?) -> Void) {
        DispatchQueue.global(qos: .utility).async {
            let result = run()
            DispatchQueue.main.async { complete(result) }
        }
    }

    private static func run() -> Reply? {
        guard let script = Bundle.main.url(forResource: "update_virtual_clawdy", withExtension: "py"),
              let stamp = Bundle.main.url(forResource: "ClawdySourceRevision", withExtension: nil),
              let revision = try? String(contentsOf: stamp, encoding: .utf8) else { return nil }
        let process = Process()
        let output = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.arguments = ["-I", script.path, "install",
                             "--current", revision.trimmingCharacters(in: .whitespacesAndNewlines),
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
