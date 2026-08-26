import AppKit
import SwiftUI

/// A single playable key's on-screen element (Req 2.1). Purely a renderer: it draws whatever
/// base color and active/inactive state it is told, and owns no note, pitch, or color-assignment
/// logic of its own -- that all lives in the Python logic layer.
final class KeyButtonView: NSView {
    let keyIdentifier: String

    private let label = NSTextField(labelWithString: "")
    private var baseColor: NSColor = .darkGray
    private var isActive: Bool = false

    init(keyIdentifier: String) {
        self.keyIdentifier = keyIdentifier
        super.init(frame: .zero)

        wantsLayer = true
        layer?.cornerRadius = 10
        layer?.backgroundColor = baseColor.cgColor

        label.stringValue = KeyButtonView.displayText(for: keyIdentifier)
        label.alignment = .center
        label.font = .systemFont(ofSize: 16, weight: .semibold)
        label.textColor = .white
        label.isBezeled = false
        label.drawsBackground = false
        label.isEditable = false
        label.isSelectable = false
        addSubview(label)

        translatesAutoresizingMaskIntoConstraints = false
        label.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            widthAnchor.constraint(equalToConstant: 56),
            heightAnchor.constraint(equalToConstant: 140),
            label.centerXAnchor.constraint(equalTo: centerXAnchor),
            label.centerYAnchor.constraint(equalTo: centerYAnchor),
        ])
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) is not supported")
    }

    private static func displayText(for keyIdentifier: String) -> String {
        switch keyIdentifier {
        case "semicolon": return ";"
        case "quote": return "'"
        default: return keyIdentifier.uppercased()
        }
    }

    /// Applies the base color assigned by the Python logic layer (Req 2.3).
    func setBaseColor(hex: String) {
        guard let color = NSColor(rainbowKeysHex: hex) else { return }
        baseColor = color
        refreshBackground()
    }

    /// Reflects whether this key's note is currently sounding (Req 2.2). The engine (Python)
    /// decides *when* a key is active; this view only decides *how* active looks.
    func setActive(_ active: Bool) {
        isActive = active
        refreshBackground()
    }

    private func refreshBackground() {
        let color = isActive ? baseColor.rainbowKeysLightened(by: 0.35) : baseColor
        layer?.backgroundColor = color.cgColor
    }
}

/// Container for all 10 playable keys (Req 2.1): lays them out left to right in physical
/// keyboard order and captures raw key-down/key-up events (Req 1.4) to forward unmodified.
/// Contains no note-selection, pitch, color-assignment, or polyphony logic -- see
/// `python/key_mapping.py` and `python/audio_logic.py` for that.
final class KeyboardView: NSView {
    /// Physical keys this instrument responds to, left to right (Req 2.1). This is keyboard
    /// layout identity only -- no pitch or color data lives here; that comes from Python.
    static let keyOrder: [String] = [
        "a", "s", "d", "f", "g",
        "j", "k", "l", "semicolon", "quote",
    ]

    /// macOS virtual key codes (Carbon HIToolbox kVK_ANSI_* values) for the keys above. Using
    /// virtual key codes rather than characters makes key capture independent of the active
    /// input source / modifier state, i.e. it tracks physical key position as required by 1.1/1.2.
    private static let keyCodeToIdentifier: [UInt16: String] = [
        0x00: "a", 0x01: "s", 0x02: "d", 0x03: "f", 0x05: "g",
        0x26: "j", 0x28: "k", 0x25: "l", 0x29: "semicolon", 0x27: "quote",
    ]

    var onKeyDown: ((String) -> Void)?
    var onKeyUp: ((String) -> Void)?

    private var buttons: [String: KeyButtonView] = [:]

    /// Keys currently physically held, tracked so they can be released if the window loses key
    /// status mid-press (macOS delivers no keyUp after focus moves away; without this, notes
    /// would sound forever). Raw event bookkeeping only -- no note logic.
    private var heldKeys: Set<String> = []
    private var resignKeyObserver: NSObjectProtocol?

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)

        let stack = NSStackView()
        stack.orientation = .horizontal
        stack.spacing = 8
        stack.translatesAutoresizingMaskIntoConstraints = false

        for key in KeyboardView.keyOrder {
            let button = KeyButtonView(keyIdentifier: key)
            buttons[key] = button
            stack.addArrangedSubview(button)
        }

        addSubview(stack)
        NSLayoutConstraint.activate([
            stack.centerXAnchor.constraint(equalTo: centerXAnchor),
            stack.centerYAnchor.constraint(equalTo: centerYAnchor),
        ])
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) is not supported")
    }

    override var acceptsFirstResponder: Bool { true }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        window?.makeFirstResponder(self)

        if let observer = resignKeyObserver {
            NotificationCenter.default.removeObserver(observer)
            resignKeyObserver = nil
        }
        if let window {
            resignKeyObserver = NotificationCenter.default.addObserver(
                forName: NSWindow.didResignKeyNotification, object: window, queue: .main
            ) { [weak self] _ in
                self?.releaseAllHeldKeys()
            }
        }
    }

    /// Emits a key-up for every key still held when keyboard focus is lost, since macOS will not
    /// deliver their real keyUp events to this window anymore.
    private func releaseAllHeldKeys() {
        for key in heldKeys {
            onKeyUp?(key)
        }
        heldKeys.removeAll()
    }

    /// Applies the color assignment decided by the Python logic layer (Req 2.3). This view does
    /// not compute colors itself -- it only renders the mapping it is given.
    func applyColors(keys: [String], colors: [String]) {
        for (key, colorHex) in zip(keys, colors) {
            buttons[key]?.setBaseColor(hex: colorHex)
        }
    }

    /// Reflects note-sounding state decided by the Python logic layer (Req 1.3/1.4/2.2).
    func setActive(_ active: Bool, forKey key: String) {
        buttons[key]?.setActive(active)
    }

    // MARK: - Raw key capture (Req 1.4) -- forwarded verbatim; no note/pitch logic here.

    override func keyDown(with event: NSEvent) {
        guard !event.isARepeat, let key = KeyboardView.keyCodeToIdentifier[event.keyCode] else {
            super.keyDown(with: event)
            return
        }
        heldKeys.insert(key)
        onKeyDown?(key)
    }

    override func keyUp(with event: NSEvent) {
        guard let key = KeyboardView.keyCodeToIdentifier[event.keyCode] else {
            super.keyUp(with: event)
            return
        }
        heldKeys.remove(key)
        onKeyUp?(key)
    }
}

/// Hosts the AppKit `KeyboardView` inside the SwiftUI view hierarchy.
struct KeyboardViewRepresentable: NSViewRepresentable {
    @ObservedObject var coordinator: AppCoordinator

    func makeNSView(context: Context) -> KeyboardView {
        let view = KeyboardView(frame: .zero)
        coordinator.attach(view)
        return view
    }

    func updateNSView(_ nsView: KeyboardView, context: Context) {}
}

// MARK: - Color rendering helpers (Req 2.2's "lighter shade" is a rendering detail; the base
// color itself still comes entirely from the Python logic layer via Req 2.3).

private extension NSColor {
    convenience init?(rainbowKeysHex hex: String) {
        var hexString = hex.trimmingCharacters(in: .whitespacesAndNewlines)
        if hexString.hasPrefix("#") { hexString.removeFirst() }
        guard hexString.count == 6, let value = UInt32(hexString, radix: 16) else { return nil }
        let r = CGFloat((value >> 16) & 0xFF) / 255.0
        let g = CGFloat((value >> 8) & 0xFF) / 255.0
        let b = CGFloat(value & 0xFF) / 255.0
        self.init(srgbRed: r, green: g, blue: b, alpha: 1.0)
    }

    /// Returns a visibly lighter shade of this color, used to render the "active" state of a key
    /// (Req 2.2). Blends each channel toward white rather than raising HSB brightness, because
    /// fully-saturated primaries (red, green, blue, yellow...) are already at maximum brightness
    /// and would otherwise barely change.
    func rainbowKeysLightened(by amount: CGFloat) -> NSColor {
        guard let converted = usingColorSpace(.sRGB) else { return self }
        return NSColor(
            srgbRed: converted.redComponent + (1.0 - converted.redComponent) * amount,
            green: converted.greenComponent + (1.0 - converted.greenComponent) * amount,
            blue: converted.blueComponent + (1.0 - converted.blueComponent) * amount,
            alpha: converted.alphaComponent
        )
    }
}
