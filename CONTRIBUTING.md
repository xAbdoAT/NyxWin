# Contributing to NyxWin

Thank you for your interest in contributing to NyxWin! NyxWin provides a native iOS compilation and packaging toolchain for Windows without requiring macOS or WSL.

## Development Setup

1. **Prerequisites:**
   - Windows 10/11 x64
   - Python 3.10 or higher
   - Swift for Windows toolchain (Swift 6.x)
   - Apple iPhoneOS SDK (installed via `nyx sdk install` or placed in `%LOCALAPPDATA%\NyxWin\SDKs\`)

2. **Clone and Install in Editable Mode:**
   ```powershell
   git clone https://github.com/xAbdoAT/NyxWin.git
   cd NyxWin
   py -3.10 -m pip install -e ".[dev]"
   ```

3. **Running the Test Suite:**
   ```powershell
   py -3.10 -m pytest
   ```

## Development Guidelines

- **Supported Templates:** NyxWin focuses exclusively on **SwiftUI** (`swiftui`) and **UIKit Swift** (`swift-uikit`) applications. Legacy C/C++/CLI/Kext templates have been decommissioned.
- **Cross-Platform Boundaries:** NyxWin produces arm64/arm64e iOS binaries on Windows using LLVM `ld64.lld` and performs ad-hoc pseudo-signing with `ldid`. Do not add macOS-only tool dependencies.
- **Entitlement Integrity:** Source `Config/Entitlements.plist` files are validated using deep, type-sensitive comparisons. Any proposed changes to the signer must ensure entitlement mismatches halt the build before the packaging stage.
- **Code Style:** Follow PEP 8 guidelines. Write clear docstrings and maintain clickable links in documentation.
- **Submitting Pull Requests:** Open a descriptive PR explaining the feature, bugfix, or optimization. Ensure all unit and integration tests pass before submitting.

