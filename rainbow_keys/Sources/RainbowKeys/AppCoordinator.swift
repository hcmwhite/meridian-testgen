import Combine
import SwiftUI

@main
struct RainbowKeysApp: App {
    @StateObject private var coordinator = AppCoordinator()

    var body: some Scene {
        WindowGroup("Rainbow Keys") {
            KeyboardViewRepresentable(coordinator: coordinator)
                .frame(minWidth: 700, minHeight: 220)
                .onAppear {
                    // Launched as a bare SPM executable (no .app bundle), the process
                    // is not activated by macOS, so its window never becomes key and
                    // keyboard events go elsewhere. Claim regular-app status and
                    // activate explicitly so key capture works immediately.
                    NSApp.setActivationPolicy(.regular)
                    NSApp.activate(ignoringOtherApps: true)
                    coordinator.start()
                }
                .onDisappear { coordinator.stop() }
        }
    }
}

/// Wires UI key events to the Swift/Python boundary and relays the resulting state back to the
/// UI. Owns no note, color, or polyphony logic itself -- all of that is decided by the Python
/// logic layer; this class only routes messages between `KeyboardView` and `PythonBridge`.
final class AppCoordinator: ObservableObject {
    private let bridge = PythonBridge()
    private weak var keyboardView: KeyboardView?

    func attach(_ view: KeyboardView) {
        keyboardView = view
        view.onKeyDown = { [weak self] key in self?.bridge.sendKeyDown(key) }
        view.onKeyUp = { [weak self] key in self?.bridge.sendKeyUp(key) }
    }

    func start() {
        bridge.onColors = { [weak self] keys, colors in
            DispatchQueue.main.async {
                self?.keyboardView?.applyColors(keys: keys, colors: colors)
            }
        }
        bridge.onNoteState = { [weak self] key, active in
            DispatchQueue.main.async {
                self?.keyboardView?.setActive(active, forKey: key)
            }
        }
        bridge.start()
    }

    func stop() {
        bridge.stop()
    }
}
