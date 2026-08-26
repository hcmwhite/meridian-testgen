// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "RainbowKeys",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "RainbowKeys",
            path: "Sources/RainbowKeys"
        )
    ]
)
