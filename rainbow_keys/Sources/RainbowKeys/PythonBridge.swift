import Foundation

/// Thin process/IPC bridge to the Python logic layer. Contains no note, color, or polyphony
/// logic of its own -- it only launches the Python process, ships raw key events to it as
/// newline-delimited JSON over stdin, and decodes newline-delimited JSON state messages from its
/// stdout back into plain callbacks.
///
/// Boundary choice: a persistent Python subprocess communicating over stdin/stdout pipes, rather
/// than a Unix domain socket or an embedded interpreter (e.g. PythonKit). See the project's
/// implementation summary for the latency/reliability comparison behind this choice.
final class PythonBridge {
    var onColors: (([String], [String]) -> Void)?
    var onNoteState: ((String, Bool) -> Void)?

    private var process: Process?
    private var stdinHandle: FileHandle?
    private var stdoutHandle: FileHandle?
    private var stdoutBuffer = Data()

    func start() {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = ["python3", PythonBridge.bridgeScriptPath]

        let stdinPipe = Pipe()
        let stdoutPipe = Pipe()
        process.standardInput = stdinPipe
        process.standardOutput = stdoutPipe
        process.standardError = FileHandle.standardError

        stdoutPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty else { return }
            self?.consume(data)
        }

        do {
            try process.run()
            self.process = process
            self.stdinHandle = stdinPipe.fileHandleForWriting
            self.stdoutHandle = stdoutPipe.fileHandleForReading
        } catch {
            FileHandle.standardError.write(
                "PythonBridge: failed to launch Python logic process: \(error)\n".data(using: .utf8)!
            )
        }
    }

    func stop() {
        stdoutHandle?.readabilityHandler = nil
        stdinHandle?.closeFile()
        process?.terminate()
        process = nil
        stdinHandle = nil
        stdoutHandle = nil
    }

    func sendKeyDown(_ key: String) {
        send(["type": "key_down", "key": key])
    }

    func sendKeyUp(_ key: String) {
        send(["type": "key_up", "key": key])
    }

    private func send(_ message: [String: Any]) {
        guard let handle = stdinHandle,
              let data = try? JSONSerialization.data(withJSONObject: message) else { return }
        handle.write(data)
        handle.write("\n".data(using: .utf8)!)
    }

    private func consume(_ data: Data) {
        stdoutBuffer.append(data)
        while let newlineRange = stdoutBuffer.range(of: Data([0x0A])) {
            let lineData = stdoutBuffer.subdata(in: stdoutBuffer.startIndex..<newlineRange.lowerBound)
            stdoutBuffer.removeSubrange(stdoutBuffer.startIndex..<newlineRange.upperBound)
            handleLine(lineData)
        }
    }

    private func handleLine(_ lineData: Data) {
        guard !lineData.isEmpty,
              let json = try? JSONSerialization.jsonObject(with: lineData) as? [String: Any],
              let type = json["type"] as? String else { return }

        switch type {
        case "colors":
            guard let keys = json["keys"] as? [String], let colors = json["colors"] as? [String] else { return }
            onColors?(keys, colors)
        case "note_state":
            guard let key = json["key"] as? String, let active = json["active"] as? Bool else { return }
            onNoteState?(key, active)
        default:
            break
        }
    }

    /// Resolves the Python bridge entry point relative to this source file's location. This
    /// assumes a development/source checkout layout (running via `swift run`); a distributed
    /// .app build would instead bundle the `python/` directory as a resource and resolve it via
    /// `Bundle.main` instead.
    private static var bridgeScriptPath: String {
        let sourceFile = URL(fileURLWithPath: #filePath)
        let packageRoot = sourceFile
            .deletingLastPathComponent()  // PythonBridge.swift -> Sources/RainbowKeys/
            .deletingLastPathComponent()  // Sources/RainbowKeys/ -> Sources/
            .deletingLastPathComponent()  // Sources/ -> package root
        return packageRoot.appendingPathComponent("python/bridge_server.py").path
    }
}
