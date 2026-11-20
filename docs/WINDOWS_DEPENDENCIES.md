# Windows Dependencies & Toolchain

NyxWin coordinates Windows-hosted development tools to compile and package native iOS applications.

This guide describes the required components, their roles and how to verify their availability.

NyxWin targets 64-bit Windows environments and does not require a macOS host, Xcode or WSL.

---

## 1. Dependency overview

The build environment consists of the NyxWin Python application, Windows compiler tools, an iOS SDK and supporting runtime resources.

| Component | Required for | Purpose |
|---|---|---|
| Windows 10 or 11, x64 | All builds | Host operating system |
| Python 3.10 or newer | All builds | NyxWin CLI, TUI and build orchestration |
| LLVM Clang | C, Objective-C and C++ | Native source compilation |
| LLVM LLD / Darwin linker | Application linking | Produces Apple-platform Mach-O executables |
| Swift for Windows | Swift and SwiftUI | Swift compilation |
| iOS SDK | iOS application builds | Platform headers and framework stubs |
| Swift iOS target resources | Swift builds | Target-specific Swift libraries and modules |
| `ldid.exe` | Signing stage | Ad-hoc Mach-O signing and entitlement processing |
| Mach-O patcher | Applicable builds | Binary processing required by the build pipeline |
| Compiler runtime resources | Applicable builds | Additional runtime symbols required by generated binaries |
| Pillow | Icon/resource operations | Image processing used by NyxWin |

Some dependencies are bundled with NyxWin, while others must be installed separately.

## 2. Windows and Python

### Windows

The intended host environment is:

- Windows 10, 64-bit x86.
- Windows 11, 64-bit x86.

A compatible Windows C++ build environment is also required by the Windows Swift toolchain.

### Python

NyxWin requires Python 3.10 or newer, subject to the supported Python versions of the installed release.

Check the installed interpreters:

```powershell
py -0p
```

Check the active interpreter:

```powershell
py -3.10 --version
```

Python packages should be installed through the project's declared dependencies and installation instructions.

Avoid installing arbitrary packages into the global Python environment to solve a project-specific dependency issue.

## 3. LLVM toolchain

LLVM supplies the compiler and linker components used for native and Apple-platform cross-compilation.

The relevant executables include:

| Executable | Role |
|---|---|
| `clang.exe` | C and Objective-C compilation |
| `clang++.exe` | C++ compilation |
| `lld.exe` | LLVM linker driver |
| `ld64.lld.exe` | Darwin/Mach-O linking |

Install LLVM from the official project distribution:

- [LLVM Releases](https://github.com/llvm/llvm-project/releases)
- [LLVM Project](https://llvm.org/)

A typical Windows installation places the executables under:

```text
C:\Program Files\LLVM\bin\
```

Verify that the executables are accessible:

```powershell
clang --version
lld --version
```

The presence of `lld.exe` alone does not guarantee that the required Darwin linker driver is available. Confirm that `ld64.lld.exe` is also detected by NyxWin.

Use a toolchain version compatible with the installed NyxWin release. Avoid mixing linker binaries from unrelated LLVM installations.

## 4. Swift for Windows

Swift is required for Swift and SwiftUI application builds.

Official installation instructions:

- [Swift for Windows](https://www.swift.org/install/windows/)
- [Swift for Windows — Manual Installation](https://www.swift.org/install/windows/manual/)

The Swift Windows toolchain has additional platform prerequisites, including an appropriate Visual Studio C++ toolchain and Windows SDK.

Follow the requirements documented for the Swift version being installed.

Verify the compiler:

```powershell
swiftc --version
```

A working `swiftc.exe` installation does not by itself prove that the iOS target is configured.

NyxWin also requires the corresponding iOS target resources and SDK files.

## 5. iOS SDK and Swift target resources

The iOS SDK provides the headers and framework stubs required by the compiler and linker.

Swift target resources provide the platform-specific Swift modules and libraries used when building Swift applications for iOS.

The SDK and target resources must be compatible with the selected compiler and build target.

### SDK management

Use NyxWin's SDK commands:

```powershell
# Inspect available and installed SDKs
nyx sdk list

# Install a selected SDK version
nyx sdk install 26.5
```

Use only versions supported by the installed NyxWin release.

### Default storage

The managed Windows layout uses:

```text
%LOCALAPPDATA%\NyxWin\SDKs\
```

This directory may contain:

```text
SDKs/
├── iPhoneOS26.5.sdk/
└── swift_resources/
```

The actual contents depend on the installed SDKs and Swift target resources.

### SDK provenance

Community-maintained SDK collections may be used by cross-compilation workflows, including:

- [xybp888/iOS-SDKs](https://github.com/xybp888/iOS-SDKs)

This is a third-party repository, not an official Apple distribution channel.

Review the source, licensing conditions and redistribution restrictions before downloading or redistributing SDK files. Do not assume that a publicly accessible SDK archive is automatically licensed for redistribution.

## 6. Bundled NyxWin resources

NyxWin includes additional resources used by its build and packaging pipeline.

The application package contains resources under:

```text
src/nyxwin/resources/
```

Relevant components include:

| Resource | Purpose |
|---|---|
| `ldid.exe` | Ad-hoc code signing |
| `libclang_rt.ios.a` | Compiler runtime support |
| `patch_macho.py` | Mach-O binary processing |
| `platform_check.c` | Platform availability support |
| `templates/` | Project scaffolding templates |
| NyxWin core | PolyForm Noncommercial License 1.0.0 (source-available, non-commercial) |
| Third-party notices | License and attribution information for external tools and libraries |

These resources should be used from the installed package rather than manually copied from an unrelated development checkout.

### Code signer

NyxWin uses `ldid.exe` for its current ad-hoc signing workflow.

The resulting signature is not equivalent to an Apple-issued signing identity or provisioning profile.

See [Setup & Installation](SETUP_GUIDE.md) for signing and device-installation considerations.

### Compiler runtime

The bundled runtime archive provides additional symbols needed by applicable build configurations.

Do not replace it with an archive from an unrelated LLVM or Apple SDK release without verifying compatibility.

## 7. Diagnostics

Run:

```powershell
nyx doctor
```

The diagnostic command checks the toolchain components and relevant storage paths.

The exact output depends on the installed release and detected environment.

Investigate any missing or incorrectly resolved component before attempting to build.

Useful independent checks include:

```powershell
py --version
clang --version
lld --version
swiftc --version
```

For the complete diagnostic process, see [Troubleshooting](TROUBLESHOOTING.md).

## 8. Reference test environment

The following environment was used for the documented Stage 1 Windows build verification.

| Component | Recorded environment |
|---|---|
| Operating system | Windows 10 Pro x64, 22H2, build 19045.5487 |
| Python | 3.10.11 |
| Clang / LLD | 23.1.4 |
| Swift | 6.4.1 |
| iOS SDK | iPhoneOS26.5 SDK |
| SDK metadata | Version 26.5, ProductVersion 26.5.1, build 23F81a |
| Build target | `arm64-apple-ios17.0` |
| Code signer | ldid 2.1.5-procursus7 |

This is a recorded test configuration, not a declaration that these are the minimum versions required by every NyxWin release.

The SDK version and iOS deployment target are separate settings.

## 9. Dependency maintenance

When updating a dependency:

1. Record its existing version and resolved path.
2. Check compatibility with the NyxWin build target.
3. Update one component at a time.
4. Run `nyx doctor`.
5. Execute the relevant regression tests.
6. Perform real SwiftUI and UIKit builds when changing a core compiler, linker, SDK or runtime dependency.
7. Retain the previous working configuration until the new one is verified.

External downloads should be verified against trusted integrity information before being accepted into a release or managed installation.

Do not invent expected hashes or treat an HTTPS download as proof of file integrity.

---

## 10. Related documentation

- [Installation & Setup](SETUP_GUIDE.md)
- [Architecture](ARCHITECTURE.md)
- [Build & Release](BUILD_AND_RELEASE.md)
- [Troubleshooting](TROUBLESHOOTING.md)