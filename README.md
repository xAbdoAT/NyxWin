# NyxWin 🚀
### Native iOS Toolchain & IPA Builder for Windows (No macOS & No WSL)
**Developed by Abdo AT ([@xAbdoAT](https://github.com/xAbdoAT))**

[![Platform: Windows](https://img.shields.io/badge/Platform-Windows%2010%2F11-blue.svg)](https://microsoft.com/windows)
[![Target: iOS ARM64](https://img.shields.io/badge/Target-iOS%20ARM64%20%2F%20ARM64e-orange.svg)](https://apple.com/ios)
[![Compiler: LLVM/Clang](https://img.shields.io/badge/Compiler-LLVM%2FClang-green.svg)](https://llvm.org)
[![Swift: 6.x](https://img.shields.io/badge/Swift-6.x%20for%20Windows-F05138.svg)](https://swift.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)

**NyxWin** allows you to create, compile, link, patch, and package native iOS applications (Swift, SwiftUI, UIKit, and Objective-C/C bridging) directly on **Windows** into installable `.ipa` packages for iPhone and iPad without requiring macOS, Xcode, virtual machines, or WSL.

> [!NOTE]
> **Compatibility & Target Environments**: NyxWin produces universal ARM64/ARM64e Mach-O binaries:
> - **TrollStore** (iOS 14.0 – 17.0): Supports root and unsandboxed capabilities when installed via TrollStore.
> - **Jailbroken Devices (AppSync Unified)**: Native execution and direct installation on Dopamine, RootHide, and checkra1n environments.
> - **LiveContainer**: Runs guest apps on stock, non-jailbroken iOS with JIT support.
> - **Standard Non-Jailbroken Devices**: Requires re-signing with an Apple Developer or personal certificate via AltStore, SideStore, Sideloadly, or Apple Developer provisioning (as iOS requires an Apple trust chain for standard execution).

---

## 📚 Documentation Suite

- **[Architecture & Pipeline Design](docs/ARCHITECTURE.md)**: Deep dive into the 6-stage compiler pipeline, Mach-O Patch #31, and security hardening.
- **[CLI Command Reference](docs/COMMANDS.md)**: Full syntax, flags, and usage examples for all `nyx` commands.
- **[Setup & Installation Guide](docs/SETUP_GUIDE.md)**: Step-by-step installation instructions for Windows.
- **[Windows Toolchain Dependencies](docs/WINDOWS_DEPENDENCIES.md)**: Minimal toolchain footprint, Swift for Windows, iOS SDKs, and helper binaries.
- **[Safe Data Migration](docs/DATA_MIGRATION.md)**: How to inspect and migrate legacy repository data to standard user folders with zero data loss.
- **[Build & Release Guide](docs/BUILD_AND_RELEASE.md)**: Wheel packaging, directory layouts, and distribution instructions.
- **[Troubleshooting & FAQ](docs/TROUBLESHOOTING.md)**: Solutions for common compiler, linker, signing, and runtime device issues.

---

## ✨ Key Features in NyxWin 1.0.0

- **Modular Python Package (`src/nyxwin`)**:
  - Clean `src/` layout installable via `pip install -e .` or `pyproject.toml`.
  - Exposes canonical console commands `nyx` and `nyxwin` globally on Windows.
- **Swift-First Application Scaffolding**:
  - First-class templates for **SwiftUI** and **UIKit (Swift)** applications conforming to the native Project Schema v1.0.
  - Built-in Objective-C bridging header auto-discovery (`find_bridging_header`) for mixed Swift/C/Objective-C codebases.
- **Modern Terminal TUI (`nyx` or `nyx menu`)**:
  - Full keyboard-driven navigation with scrollable boxed views and color-coded status.
  - Interactive project creation, configuration editor, SDK manager, diagnostics viewer, and backup dashboard.
- **6-Stage Compilation & Packaging Pipeline**:
  - Multi-threaded C, Objective-C, and C++ compilation using Windows Clang.
  - Swift compilation using the official Swift toolchain for Windows (`swiftc.exe`) with Whole-Module Optimization.
  - Automatic `platform_check.o` compilation for Darwin availability symbols (`__isPlatformVersionAtLeast`).
  - Mach-O linking via LLVM's `ld64.lld` linker.
  - In-place **Mach-O Patch #31** (`patch_macho_binary`) ensuring crash-free SwiftUI execution on iOS 17+.
  - Type-sensitive recursive plist comparison and ad-hoc code signing via native `ldid.exe`.
  - Standard `.app` and `.ipa` bundle assembly.
- **Build Transparency & Persistent Transcripts**:
  - One-click build experience automatically resolving project entitlements without modal interruptions.
  - Deterministic build transcripts recorded to `.nyxwin/transcripts/` with CDHash extraction, signature structural checks, and exact duration reporting.
- **Robust Path Safety & Security Hardening**:
  - Strict ancestor path-traversal prevention (`is_safe_subpath`) guarding cache and build cleanup.
  - Zip-slip vulnerability protection on project backup restoration.
  - Native Pillow LANCZOS icon resizing preventing script injection.
  - Automatic safety snapshots prior to project restoration or modification.

---

## ⚡ Quick Start

### 1. One-Line Automated PowerShell Install (Recommended)
Open **PowerShell** and run:
```powershell
irm https://raw.githubusercontent.com/xAbdoAT/NyxWin/main/install.ps1 | iex
```
This automated bootstrap installer:
- Installs NyxWin into `%LOCALAPPDATA%\NyxWin\app` and sets up global CLI launchers (`nyx` and `nyxwin`) in `%LOCALAPPDATA%\NyxWin\bin` on your User `PATH`.
- Automatically checks and installs Python, LLVM (`clang`/`lld`), Swift for Windows, the iOS SDK (`iPhoneOS26.5.sdk`), and iOS ARM64 Swift target libraries (`swift_resources`).

*(Alternatively, if you cloned the repository locally, run `install.bat` or `powershell -ExecutionPolicy Bypass -File .\install.ps1`).*

### 2. Verify Your Toolchain & Check for Updates
```powershell
nyx doctor
nyx update --check
```

### 3. Launch the Interactive Menu
Simply run `nyx` with no arguments (or run `nyx menu`):
```powershell
nyx
```

### 4. Create and Build an iOS Application
```powershell
# Create a modern SwiftUI application
nyx new swiftui MyApp --bundle-id com.example.myapp

# Or create a UIKit Swift application
nyx new swift-uikit MyUIKitApp

# Build and package into an installable IPA
nyx build MyApp

# Find your generated IPA inside the project's dist directory:
# MyApp/dist/MyApp.ipa
```

---

## 🛠️ Essential Commands

```powershell
# Toolchain diagnostics & storage status
nyx doctor

# Interactive TUI dashboard
nyx menu

# Project scaffolding
nyx new swiftui <Name>
nyx new swift-uikit <Name>

# Build pipeline (one-click automatic build)
nyx build <Name>
nyx build <Name> --verbose
nyx build <Name> --profile trollstore

# Cache management
nyx clean <Name>
nyx clean-module-cache

# Storage inspection & safe migration
nyx data paths
nyx data migrate --dry-run
nyx data migrate --apply

# Project snapshots & backups
nyx backup <Name>
nyx list-backups <Name>
nyx restore <Name> <BackupZip>

# iOS SDK management
nyx sdk list
nyx sdk install 26.5

# Self-Updater (Stable Releases or Dev Branch)
nyx update
nyx update --check
nyx update --dev
```

---

## 🙏 Acknowledgments & Inspiration

- **[Nyxian](https://github.com/emexlab/Nyxian)** by **emexLabs**: Special thanks and credit to the Nyxian project for inspiring the vision and name origin of **NyxWin** — bringing accessible, self-contained iOS application compilation to developers everywhere. NyxWin is an independent, ground-up Python implementation designed specifically for Windows cross-compilation (`clang.exe`, `swiftc.exe`, and `ld64.lld.exe`).
- **[ProcursusTeam / ldid](https://github.com/ProcursusTeam/ldid)** & **[LLVM Project](https://llvm.org)**: For providing the open-source Mach-O code-signing and compiler runtime utilities.

---

## 📜 License
MIT License. Developed by Abdo AT ([@xAbdoAT](https://github.com/xAbdoAT)).
See [LICENSE](LICENSE) for full details and [THIRD_PARTY_NOTICES.md](src/nyxwin/resources/tools/THIRD_PARTY_NOTICES.md) for bundled toolchain binary licenses (`ldid` under GPLv3 and `libclang_rt.ios.a` under Apache-2.0 with LLVM Exception).
