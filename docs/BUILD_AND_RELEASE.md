# NyxWin — Build, Packaging & Architecture Guide

This document outlines the architecture, data separation, and step-by-step procedures for building, testing, and packaging NyxWin for distribution.

---

## 1. Architectural Directory Layout

NyxWin enforces a strict separation between the **tool source code**, the **machine-local runtime data**, and **user app projects**.

```text
NyxWin Repository (Tool Source Only)
├── src/nyxwin/             <- Core Python package, build pipeline, TUI, CLI
│   └── resources/
│       ├── tools/          <- ldid.exe, libclang_rt.ios.a, patch_macho.py
│       └── templates/      <- UIKit, SwiftUI, and C/C++ project templates
├── docs/                   <- Documentation, architecture guides, reports
├── tests/                  <- Unit and integration test suites
├── main.py                 <- Root script entrypoint
├── nyx.bat / nyxwin.bat    <- Command-line launchers for Windows
├── install.bat / .ps1      <- Automated one-click installer
└── pyproject.toml          <- Build system and package metadata

%LOCALAPPDATA%\NyxWin\ (Authoritative Runtime & Managed Installation Root)
├── app/                    <- Managed NyxWin application installation (via install.ps1)
├── bin/                    <- Global CLI command shims (nyx.cmd, nyxwin.cmd) on User PATH
├── SDKs/                   <- Downloaded iOS SDKs & Swift target libraries
│   ├── iPhoneOS26.5.sdk/
│   └── swift_resources/
├── Build/                  <- External build intermediates (<app>-<uuid>/)
├── Cache/                  <- External compiler object/module cache (<uuid>/)
├── Backups/                <- Project recovery snapshots (<app>-<uuid>/)
└── Settings/               <- Tool settings & recent_projects.json

User App Projects (Standalone Folders Anywhere)
├── Config/
│   ├── Project.plist       <- Scheme, target iOS, compiler, bundle ID
│   ├── Entitlements.plist  <- App capabilities & sandbox entitlements
│   └── .nyxproject         <- Machine-local UUID (excluded from git)
├── Sources/                <- User Swift / Objective-C / C source code
├── Resources/              <- AppIcon, Assets.car, storyboards, audio
└── dist/                   <- Packaged release deliverables (<App>.ipa)
```

> **Rule:** The repository root is strictly for source code and tools. Runtime caches, intermediate object files, backups, and large SDK installations must never be written into the tool source repository.

---

## 2. Requirements & Prerequisites

To develop, build, and run NyxWin:

1. **Operating System:** Windows 10 or Windows 11 (64-bit AMD64).
2. **Python:** Python 3.10 or newer (tested with Python 3.10 and 3.12).
3. **LLVM Toolchain:** Clang and LLD (`winget install LLVM.LLVM` or from `C:\Program Files\LLVM\bin`).
4. **Swift Toolchain (Optional for Swift/SwiftUI):** Official Windows Swift Toolchain (`swift.org/install/windows` or `winget install Swift.Toolchain`).
5. **Python Build Dependencies:**
   ```powershell
   pip install build setuptools wheel pytest rich pillow
   ```

---

## 3. Automated Bootstrap Distribution & Self-Updater (Primary Method)

NyxWin is distributed primarily via its automated PowerShell bootstrap installer (`install.ps1`), inspired by `TheosWin` and `xtool`:

```powershell
irm https://raw.githubusercontent.com/xAbdoAT/NyxWin/main/install.ps1 | iex
```

1. **Managed Installation:** Downloads or syncs the NyxWin repository into `%LOCALAPPDATA%\NyxWin\app`.
2. **Global CLI Shims:** Creates `nyx.cmd` and `nyxwin.cmd` in `%LOCALAPPDATA%\NyxWin\bin` and registers that folder in the Windows User `PATH` (no manual `.whl` building required).
3. **Self-Updater (`nyx update`):** Users can update in-place from official GitHub Releases (`nyx update`) or from the `main` branch (`nyx update --dev`).

### Optional: Building a Standalone Python Wheel (`.whl`)

If you prefer to package NyxWin into a Python wheel (`.whl`) containing all native tools (`ldid.exe`, `libclang_rt.ios.a`, `patch_macho.py`, and license notices) and templates:

```powershell
# From the repository root:
python -m build --wheel
```

- **Output:** `dist/nyxwin-1.0.0-py3-none-any.whl` (~1.81 MB compressed).
- **Resource Verification:** All templates and binary tools under `src/nyxwin/resources/` are automatically packaged via the `[tool.setuptools.package-data]` configuration in `pyproject.toml`.

### Installing the Built Wheel in Any Environment
```powershell
pip install dist/nyxwin-1.0.0-py3-none-any.whl
```
Once installed, the `nyx` and `nyxwin` console commands become globally available in your Windows PATH.

---

## 4. How to Clean Development Artifacts

After packaging or running tests, clean build artifacts from the repository root to keep it pristine:

```powershell
# Clean build and distribution outputs:
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

# Clean Python bytecode and test caches:
Get-ChildItem -Path . -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Remove-Item -Recurse -Force .pytest_cache -ErrorAction SilentlyContinue
```

*(These directories are also ignored by `.gitignore` so they will never be committed).*

---

## 5. Running the Toolchain & Tests

### Running NyxWin in Development Mode
You can run directly from the repository without installing the wheel:
```powershell
# Interactive Terminal Menu (TUI):
.\nyx.bat
# or
python main.py

# Toolchain Doctor (Dependency Check):
python main.py doctor

# Build a Project:
python main.py build "C:\Path\To\MyProject"
```

### Running the Automated Test Suite
```powershell
# Fast Unit Tests (52 tests):
pytest tests/unit

# CLI Integration Tests (8 tests):
pytest tests/integration/test_cli.py

# Build Pipeline Smoke Tests:
pytest tests/integration/test_build_pipeline.py -k "test_clean_separates_build_from_external_cache_and_backups"
```

---

## 6. iOS SDK Management

1. **Storage Location:** All SDKs are downloaded and stored strictly in `%LOCALAPPDATA%\NyxWin\SDKs\`.
2. **Download an SDK via CLI:**
   ```powershell
   nyx sdk install 26.5
   # or
   nyx sdk install 27.0
   ```
3. **Interactive SDK Manager:**
   Run `nyx` -> Select `[🛠️ Global Tools]` -> Select `[📱 iOS SDK Manager]`.
4. **Clean Swift Compiler Module Cache:**
   ```powershell
   nyx clean-module-cache
   ```
