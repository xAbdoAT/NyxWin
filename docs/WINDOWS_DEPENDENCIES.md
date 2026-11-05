# NyxWin Windows Dependencies and Toolchain Setup

NyxWin executes native iOS builds directly on Windows 10/11 x64 without requiring macOS, Xcode, virtual machines, or WSL. To achieve this, it orchestrates standard cross-compilation binaries available on Windows.

---

## 1. Prerequisites Overview

| Component | Minimum Version | Recommended Source | Required For |
|---|---|---|---|
| **Windows OS** | Windows 10 20H2+ / Windows 11 | Microsoft | Base OS |
| **Python** | 3.10.x - 3.12.x (x64) | `winget install Python.Python.3.10` or python.org | NyxWin CLI, build orchestrator, TUI |
| **LLVM Toolchain** | 17.0+ (Tested with LLVM 23.1) | `winget install LLVM.LLVM` or github.com/llvm | `clang.exe`, `lld.exe`, `ld64.lld.exe` |
| **Swift Toolchain** | Swift 5.9+ / 6.0+ (Tested with 6.4) | `winget install Swift.Toolchain` or swift.org/install/windows | `swiftc.exe` (Swift & SwiftUI projects) |
| **iOS SDK** | iOS 16.0 - 18.0 (Tested with 17.0, 26.5) | `nyx sdk install 26.5` (xybp888/iOS-SDKs) | System headers, frameworks, dylibs |
| **ldid** | Link Identity Editor v2.1.5-procursus7 | Bundled in `src/nyxwin/resources/tools/ldid.exe` (GPLv3) | Ad-hoc codesigning & TrollStore entitlements |
| **Compiler-RT** | Universal ARM64/ARM64e | Bundled in `src/nyxwin/resources/tools/libclang_rt.ios.a` (Apache 2.0 with LLVM Exception) | Mach-O low-level runtime symbols |
| **Pillow** | 9.0+ | `pip install pillow` (installed automatically) | iOS icon generation & scaling |

---

## 2. Automated One-Click Installation

The fastest way to install all dependencies is running the bundled `install.bat` installer:

```cmd
install.bat
```

Or via PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

### What `install.ps1` Does:
1. Detects Python 3.10+; offers automatic installation via `winget` if missing.
2. Detects LLVM (`clang.exe`, `ld64.lld.exe`); offers automated `winget` installation.
3. Detects Swift toolchain; guides installation if compiling Swift/SwiftUI.
4. Validates or downloads `iPhoneOS26.5.sdk`.
5. Verifies bundled `ldid.exe`, `libclang_rt.ios.a`, and `platform_check.c`.
6. Installs `nyxwin` package into Python environment (`pip install -e .`).
7. Registers NyxWin in the Windows User `PATH` environment variable.
8. Runs `nyx doctor` to verify environment health.

---

## 3. Manual Installation & Verification

### 3.1 Install Python 3.10+
Install Python from the Microsoft Store or via Winget:
```powershell
winget install Python.Python.3.10
```
> [!IMPORTANT]
> Ensure "Add Python to PATH" was selected during Python installation.

### 3.2 Install LLVM
LLVM provides the Clang C/Objective-C compiler and the `ld64.lld` Mach-O linker:
```powershell
winget install LLVM.LLVM
```
Default installation directory: `C:\Program Files\LLVM\bin`.

### 3.3 Install Swift for Windows
To compile Swift and SwiftUI apps, install the official Swift for Windows toolchain:
- Follow instructions at [swift.org/install/windows](https://www.swift.org/install/windows/).
- Or install via winget:
  ```powershell
  winget install Swift.Toolchain
  ```
Default installation directory: `%LOCALAPPDATA%\Programs\Swift\Toolchains` or `C:\Program Files\Swift\Toolchains`.

### 3.4 Install iOS SDK
NyxWin downloads patched, clean iOS SDKs containing frameworks, system libraries, and header maps:
```powershell
nyx sdk install 26.5
```
SDKs are stored in `%LOCALAPPDATA%\NyxWin\SDKs\` (or the repository `sdk/` directory).

---

## 4. Environment Verification

To verify that all tools are properly detected by NyxWin:

```powershell
nyx doctor
```

Expected output:
```
Checking NyxWin Toolchain Environment...

  [OK] Clang Compiler:      C:\Program Files\LLVM\bin\clang.exe
  [OK] LLVM Linker (lld):   C:\Program Files\LLVM\bin\lld.exe
  [OK] Mach-O Linker (ld64): C:\Program Files\LLVM\bin\ld64.lld.exe
  [OK] Swift Compiler:      C:\...\swiftc.exe
  [OK] Swift Target Libs:   C:\...\sdk\swift_resources\swift
  [OK] iOS SDK (iPhoneOS26.5.sdk): Verified (277 frameworks)
  [OK] Code Signer (ldid):  src/nyxwin/resources/tools/ldid.exe
  [OK] Mach-O Patcher:      src/nyxwin/resources/tools/patch_macho.py (Patch #31)
  [OK] Compiler Runtime:    src/nyxwin/resources/tools/libclang_rt.ios.a (Universal ARM64/ARM64e)
```
