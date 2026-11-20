# CLI Reference

NyxWin provides a command-line interface for project creation, building, diagnostics, storage management and toolchain operations.

Commands can be invoked through the installed console scripts:

```powershell
nyx <command>
nyxwin <command>
```

The Python module entry point is also available:

```powershell
python -m nyxwin <command>
```

The installed CLI's `--help` output is the authoritative reference for available commands and options.

---

## 1. Global options

| Option | Shorthand | Description |
|---|---|---|
| `--help` | `-h` | Display help for the application or selected command |
| `--version` | `-V` | Display the installed NyxWin version |
| `--workspace <path>` | `-w` | Specify a workspace or project root where supported |

Examples:

```powershell
nyx --help
nyx --version
nyx build --help
```

To select a workspace:

```powershell
nyx -w "C:\Users\User\NyxProjects" doctor
```

The accepted workspace path and command behavior depend on the installed CLI version.

---

## 2. Interactive terminal interface

### Launch the dashboard

Run NyxWin without arguments:

```powershell
nyx
```

Or explicitly:

```powershell
nyx menu
```

The terminal interface provides keyboard-driven access to supported project and toolchain operations.

Navigation controls depend on the active screen. Follow the key hints displayed by the interface.

## 3. Environment diagnostics

### `nyx doctor`

Checks the local development environment and reports the availability of relevant build dependencies.

```powershell
nyx doctor
```

The diagnostic checks cover components such as:

- Python runtime.
- Clang compiler.
- LLVM linker and Darwin linker.
- Swift compiler.
- Swift iOS target resources.
- Installed iOS SDKs.
- Code-signing tool.
- Mach-O patcher.
- Compiler runtime resources.
- Application and user-data paths.

A successful diagnostic indicates that the checked components were resolved. It does not guarantee that every possible project will compile or run on every iOS device.

When reporting a problem, include the relevant diagnostic output.

## 4. Project creation

### `nyx new`

Creates a project from a supported application template.

The current primary application templates are SwiftUI and UIKit.

**Create a SwiftUI application:**

```powershell
nyx new swiftui MyApp --bundle-id com.example.myapp
```

**Create a UIKit application:**

```powershell
nyx new swift-uikit MyUIKitApp
```

The generated project includes its configuration, source files and application resources.

The project configuration uses Canonical Project Schema v2.0.

For additional options, run:

```powershell
nyx new --help
```

## 5. Build an application

### `nyx build`

Compiles and packages a project into an iOS IPA archive.

```powershell
nyx build MyApp
```

A project can also be selected using its path where supported by the CLI.

### Build options

| Option | Description |
|---|---|
| `--verbose` / `-v` | Display additional compiler and linker output |
| `--sdk <version>` | Select an installed iOS SDK version |
| `--target <triple>` | Specify the target architecture and deployment target |
| `--profile <profile>` | Select a supported signing or entitlement profile |

**Verbose build:**

```powershell
nyx build MyApp --verbose
```

**Select an installed SDK:**

```powershell
nyx build MyApp --sdk 26.5
```

**Specify an Apple target triple:**

```powershell
nyx build MyApp --target arm64-apple-ios17.0
```

**Select the TrollStore entitlement profile:**

```powershell
nyx build MyApp --profile trollstore
```

Use an entitlement profile only when it matches the intended application and device environment.

Selecting the TrollStore profile does not install TrollStore, bypass device restrictions by itself or guarantee that an IPA will run on a particular device.

Check the installed command's help output for supported profile values and option combinations.

### Build lifecycle

The build pipeline follows six stages:

```text
SCAN → COMPILE → LINK → PATCH → SIGN → PACKAGE
```

The final application package is normally written to:

```text
<ProjectDirectory>\dist\<ProjectName>.ipa
```

A build is successful only when the pipeline reports successful completion, including packaging.

### Cancellation

**CLI mode**

Press:

```text
Ctrl+C
```

during an active build to request cancellation.

NyxWin coordinates cancellation with its managed build subprocesses and records the final result.

Cancellation does not necessarily complete instantaneously. The process manager attempts graceful termination and escalates when required.

Do not assume that an interrupted build completed successfully.

## 6. Build logs and JSON reports

Each managed build produces persistent diagnostic information.

The standard managed installation stores build records under:

```text
%LOCALAPPDATA%\NyxWin\Logs\builds\<Project>\
```

Available files include:

| File | Purpose |
|---|---|
| `<build_id>.log` | Build-specific text transcript |
| `latest.log` | Convenience copy of the latest transcript |
| `<build_id>.json` | Build-specific structured report |
| `build_report.json` | Convenience copy of the latest JSON report |

The JSON format uses Build Report Schema v1.0.

### Inspect a build

Start with:

```text
latest.log
```

Then inspect:

```text
build_report.json
```

Relevant information can include build status, stage timings, compiler and linker invocations, diagnostics, cleanup information and generated artifact metadata.

Keep both files when reporting a failed build.

## 7. Dashboard cancellation and report viewer

The interactive dashboard provides cancellation and build-result inspection.

### During a build

| Key | Action |
|---|---|
| `Esc` | Request build cancellation |
| `Q` | Request build cancellation |

Follow the active screen's displayed key hints.

### After a build

The build summary provides access to the structured report viewer.

Press:

```text
J
```

to open the JSON Build Report Viewer.

Inside the viewer:

| Key | Action |
|---|---|
| `N` | Next page |
| `P` | Previous page |
| `Y` | Copy report path |
| `O` | Open the JSON report in the default editor |
| `C` | Copy the JSON report contents |
| `Esc` | Return to the build summary |

The viewer supports page navigation using the relevant keyboard controls.

## 8. Cleaning build data

### `nyx clean`

Removes supported generated build intermediates for a selected project.

```powershell
nyx clean MyApp
```

This command is intended for generated build data, not project source files.

Inspect the selected project and active storage configuration before cleaning.

### `nyx clean-module-cache`

Clears the supported Swift compiler module cache.

```powershell
nyx clean-module-cache
```

A subsequent build may take longer because the relevant cache entries must be regenerated.

Do not manually delete unrelated directories under the NyxWin runtime or project folders as a substitute for the supported cleaning commands.

## 9. Storage inspection and migration

NyxWin separates application source files, user configuration, runtime data and user projects.

### Inspect configured paths

```powershell
nyx data paths
```

This displays the resolved storage locations and any supported legacy directory detections.

### Preview a migration

```powershell
nyx data migrate --dry-run
```

The dry-run operation inspects the proposed migration without applying the file-copy operation.

Review the source and destination directories, file counts, sizes and reported conflicts.

### Apply a migration

```powershell
nyx data migrate --apply
```

This executes the migration operation.

Make an independent backup of important project data before applying a migration. Verify the destination and migration report before considering any cleanup of the original directories.

See [Data Storage & Migration](DATA_MIGRATION.md).

## 10. SDK management

### `nyx sdk list`

Lists the SDK versions available through the installed SDK manager and identifies installed SDKs.

```powershell
nyx sdk list
```

### `nyx sdk install`

Downloads and installs a selected SDK version.

```powershell
nyx sdk install 26.5
```

Only use SDK versions supported by the installed NyxWin release.

SDK source repositories may be independently maintained third-party collections. Review the source and applicable terms before downloading or redistributing SDK contents.

See [Windows Dependencies](WINDOWS_DEPENDENCIES.md).

## 11. Project configuration

### `nyx config show`

Displays supported configuration information.

**Global configuration:**

```powershell
nyx config show
```

**Project configuration:**

```powershell
nyx config show MyApp
```

Project configuration is stored in:

```text
Config/Project.plist
```

The exact fields depend on the project's schema version and supported build settings.

For project configuration and migration details, see [Architecture](ARCHITECTURE.md).

## 12. Project backups and restoration

NyxWin provides project snapshot and restoration commands.

### Create a backup

```powershell
nyx backup MyApp
```

### List project backups

```powershell
nyx list-backups MyApp
```

### Restore a backup

```powershell
nyx restore MyApp "C:\Path\To\MyApp_Backup.zip"
```

A restore operation can replace existing project contents.

Verify the selected archive and preserve an independent copy of important project data before restoration.

Inspect the operation's result before continuing development.

## 13. Updating NyxWin

NyxWin provides an update interface for checking and selecting supported update channels.

### Check for updates

```powershell
nyx update --check
```

### Run the standard update operation

```powershell
nyx update
```

### Use the development update channel

```powershell
nyx update --dev
```

The development channel can contain changes that have not passed the same release verification as a stable release.

Review the update source, release information and your existing installation state before changing versions.

**Important:** Updating NyxWin and migrating a project configuration are different operations. Preserve important user data before changing installations.

---

## 14. Common command examples

A typical first-use sequence:

```powershell
# Check the installation
nyx --version
nyx doctor

# Create a SwiftUI project
nyx new swiftui MyApp --bundle-id com.example.myapp

# Build it
nyx build MyApp

# Inspect the build result
nyx
```

A typical diagnostic sequence:

```powershell
# Check toolchain availability
nyx doctor

# Inspect installed SDKs
nyx sdk list

# Rebuild with additional output
nyx build MyApp --verbose
```

A typical data-management sequence:

```powershell
# Inspect active paths
nyx data paths

# Preview a migration
nyx data migrate --dry-run

# Create a project backup
nyx backup MyApp
```

---

## 15. Finding additional help

Use the CLI's built-in help when an option or command is unavailable:

```powershell
nyx --help
nyx build --help
nyx new --help
nyx sdk --help
```

For more information:

- [Installation & Setup](SETUP_GUIDE.md)
- [Architecture](ARCHITECTURE.md)
- [Windows Dependencies](WINDOWS_DEPENDENCIES.md)
- [Data Storage & Migration](DATA_MIGRATION.md)
- [Build & Release](BUILD_AND_RELEASE.md)
- [Troubleshooting](TROUBLESHOOTING.md)
- [Roadmap & Development](ROADMAP_AND_ENHANCEMENTS.md)