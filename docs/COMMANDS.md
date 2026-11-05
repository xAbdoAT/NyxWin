# NyxWin CLI Command Reference

NyxWin provides a unified, cross-environment CLI interface. Commands can be invoked using:
- `nyx <command>` (Console Script or Batch Launcher)
- `nyxwin <command>` (Alias Launcher)
- `python -m nyxwin <command>` (Module Invocation)

---

## 1. Global Options

| Option | Shorthand | Description |
|---|---|---|
| `--help` | `-h` | Display global help message or help for a specific command |
| `--version` | `-V` | Output installed NyxWin version |
| `--workspace <path>` | `-w` | Explicitly specify the standalone project or workspace root directory |

---

## 2. Command Index

### 2.1 `nyx` (No Arguments) & `nyx menu`
Launches the full-screen interactive terminal TUI dashboard. Provides keyboard-driven navigation (Arrow keys, Enter, Backspace, Esc) to manage projects, edit configurations, trigger builds, and manage SDKs.

```powershell
nyx
nyx menu
```

---

### 2.2 `nyx doctor`
Performs a deep diagnostic scan of all toolchain prerequisites:
- **Clang Compiler**: Verifies `clang.exe` and reports version.
- **LLD Linker**: Verifies `lld.exe` and `ld64.lld.exe`.
- **Swift Compiler**: Verifies `swiftc.exe` and version.
- **Swift Target Libs**: Verifies `iphoneos/arm64` and `arm64e` definition directories.
- **iOS SDK**: Verifies installed SDKs and framework counts.
- **Code Signer**: Verifies `ldid.exe`.
- **Mach-O Patcher**: Verifies Patch #31 engine.
- **Compiler Runtime**: Verifies universal ARM64 `libclang_rt.ios.a`.
- **Storage Layout**: Displays active workspace, config directory, runtime data, and legacy directory detection status.

```powershell
nyx doctor
```

---

### 2.3 `nyx new <type> <name> [options]`
Scaffolds a new native iOS project using original application templates and native Project Schema v1.0.

```powershell
nyx new swiftui MyApp
nyx new swift-uikit MyUIKitApp --bundle-id com.company.myapp --target 17.0
```

**Supported Project Types:**
- `swiftui`: Modern Swift + SwiftUI application.
- `swift-uikit` (or `swift`, `uikit`): Swift + UIKit application with SceneDelegate, AppDelegate, and storyboard/code.

*(Note: Legacy starter templates such as standalone C/ObjC command-line utilities have been retired from new scaffolding to focus on production Swift applications; existing C/C++/Objective-C source files and bridging headers remain fully supported by the build pipeline).*

**Options:**
- `--out <path>`: Custom destination directory (defaults to current directory or active workspace).
- `--bundle-id <id>`: Custom bundle identifier (defaults to `com.example.<name>`).
- `--target <version>`: Minimum deployment target (defaults to `17.0`).

---

### 2.4 `nyx build [project] [options]`
Compiles, links, patches, ad-hoc signs, and packages an iOS project into a valid `.ipa` bundle.

```powershell
nyx build MyApp
nyx build MyApp --verbose
nyx build MyApp --profile trollstore
nyx build MyApp --target arm64-apple-ios16.0 --sdk 26.5
```

**Options:**
- `project`: Project directory path or project name located in active workspace `Projects/`.
- `--profile <auto|trollstore|sandboxed>`: Entitlement profile to inject:
  - `auto`: Uses project's existing `Config/Entitlements.plist`.
  - `trollstore`: Injects root permissions (`platform-application`, `no-sandbox`, `get-task-allow`).
  - `sandboxed`: Standard iOS app sandbox permissions.
- `--sdk <version>`: Explicitly select installed SDK version (e.g. `26.5`, `27.0`).
- `--target <triple>`: Target architecture triple (defaults to `arm64-apple-ios<DeploymentTarget>`).
- `--verbose`, `-v`: Output full raw compiler and linker commands.

---

### 2.5 `nyx clean [project]` & `nyx clean-module-cache`
Cleans intermediate object files and compilation caches with path-traversal safeguards. External build intermediates in `%LOCALAPPDATA%\NyxWin\Build\<name>-<id>\` are safely removed without touching project sources.

```powershell
# Cleans build cache and external intermediates for a specific project
nyx clean MyApp

# Cleans Swift compiler module cache
nyx clean-module-cache
```

---

### 2.6 `nyx data <subcommand>`
Inspects active storage directories and manages safe migration of legacy repository-local data to standard Windows user directories.

```powershell
# Inspect active configuration, data, project, and legacy paths
nyx data paths

# Preview data migration (file counts, size, disk space, conflicts) without copying
nyx data migrate --dry-run

# Execute non-destructive verified migration (original source files are never deleted)
nyx data migrate --apply
```

---

### 2.7 `nyx config show [project]`
Displays global workspace configuration or active project settings.

```powershell
# Display global configuration and recent workspaces
nyx config show

# Display parsed Project.plist settings for a project
nyx config show MyApp
```

---

### 2.8 `nyx workspace <subcommand>` (Retired / Deprecated)
Multi-app studio workspaces have been retired in favor of the standalone single-project architecture. Invoking `nyx workspace` commands displays a friendly deprecation notice advising that each project is now a self-contained standalone application directory.

```powershell
# Displays deprecation advisory
nyx workspace list
```

---

### 2.9 `nyx sdk <subcommand>`
Lists installed iOS SDKs and downloads upstream SDK archives from `xybp888/iOS-SDKs`.

```powershell
# List installed SDKs and available remote versions
nyx sdk list

# Download and install a specific iOS SDK version
nyx sdk install 27.0
nyx sdk install 26.5
```

---

### 2.10 `nyx backup`, `nyx list-backups`, `nyx restore`
Provides safe version snapshotting and recovery for projects.

```powershell
# Create a timestamped .zip snapshot in Backups/
nyx backup MyApp

# List all snapshot backups available for a project
nyx list-backups MyApp

# Restore a project from a backup archive (automatically creates pre-restore safety snapshot)
nyx restore MyApp C:\Path\To\MyApp_20261027_074500.zip
```

---

### 2.11 `nyx set-icon <project> <image>`
Generates all 15 required iPhone and iPad icon resolutions from a high-resolution PNG/JPG source and updates `Config/Project.plist`.

```powershell
nyx set-icon MyApp C:\Images\app_icon.png
```

---

### 2.12 `nyx export <project>` & `nyx import <archive>`
Exports projects to shareable ZIP archives or imports existing project archives into the active workspace.

```powershell
nyx export MyApp
nyx import C:\Downloads\SharedApp.zip
```

---

### 2.13 `nyx setup-path`
Creates global `nyx.cmd` and `nyxwin.cmd` command shims in `%LOCALAPPDATA%\NyxWin\bin` and registers that directory to the Windows User `PATH` environment variable.

```powershell
nyx setup-path
```

---

### 2.14 `nyx update [options]`
Checks for and installs NyxWin updates directly from GitHub (`xAbdoAT/NyxWin`). Supports both official GitHub Releases (default) and the latest `main` development branch.

```powershell
# Check for updates and install the latest stable GitHub Release
nyx update

# Only check whether an update is available without installing
nyx update --check

# Update from the latest commit on the 'main' branch
nyx update --dev

# Force reinstall the latest version even if already up to date
nyx update --force
```
