# Troubleshooting

This guide covers common problems encountered when configuring NyxWin, compiling iOS applications and packaging IPA files on Windows.

Start with the diagnostic commands below. They help establish whether a problem comes from the Windows environment, the compiler toolchain, project configuration, signing or the target device.

---

## 1. Start with diagnostics

When a command fails, collect the basic environment information first.

In PowerShell:

```powershell
nyx --version
nyx doctor
```

Check whether the required tools are available:

```powershell
Get-Command nyx, nyxwin, clang, lld, swiftc -ErrorAction SilentlyContinue
```

Check installed Python interpreters:

```powershell
py -0p
```

If an SDK-related problem occurs, inspect the installed SDKs:

```powershell
nyx sdk list
```

Record the NyxWin version, Python version, SDK version and the complete error message before changing the project configuration.

Do not update several toolchain components at once. Change one variable, rerun the diagnostic and test again.

---

## 2. Installation and environment problems

### 2.1 `nyx` is not recognized as a command

**Possible causes**

- The NyxWin installation directory is not on the user `PATH`.
- The installer did not complete successfully.
- The terminal was opened before the installation or PATH update.
- NyxWin was installed into a different Python environment.

**What to do**

1. Close and reopen PowerShell.
2. Run:

   ```powershell
   Get-Command nyx -ErrorAction SilentlyContinue
   ```

3. Check that the NyxWin command directory is included in your user `PATH`.
4. Run `nyx doctor` after the command becomes available.

For a managed installation, inspect the configured NyxWin installation and command directories rather than copying executable files manually.

### 2.2 `nyx doctor` reports a missing compiler or linker

**Possible causes**

- LLVM is not installed.
- The executable directory is not on `PATH`.
- The selected LLVM installation does not contain the required linker.
- NyxWin is resolving an older or incompatible executable.

**What to do**

Check the detected commands:

```powershell
Get-Command clang, lld -ErrorAction SilentlyContinue
```

Then inspect their versions:

```powershell
clang --version
lld --version
```

Use an LLVM release compatible with the NyxWin version you are running.

Do not copy random linker binaries into the NyxWin resource directory. Correct the configured toolchain path instead.

### 2.3 Swift is missing or cannot be resolved

**Possible causes**

- Swift for Windows is not installed.
- The terminal has an outdated PATH.
- Required Windows development dependencies are missing.
- The installed toolchain version is incompatible with the configured target resources.

**What to do**

Check:

```powershell
Get-Command swiftc -ErrorAction SilentlyContinue
swiftc --version
```

Review the official [Swift for Windows installation instructions](https://www.swift.org/install/windows/).

Swift on Windows also requires appropriate Windows C++ build tools and SDK components. A Swift executable being present does not prove that the complete development environment is configured correctly.

### 2.4 Installer reports an error

Do not assume that an installer succeeded just because its PowerShell window closed.

Record:

- The exact command used.
- The complete installer output.
- The last reported operation.
- The relevant exit code, when available.

Do not delete the existing managed installation or manually remove its directories to work around a failed update.

Use the installation and recovery instructions associated with your NyxWin release.

---

## 3. Swift and compilation errors

### 3.1 `cannot find 'SwiftUI' in scope` or `no such module 'SwiftUI'`

**Likely cause**

The Swift compiler cannot resolve the iOS target modules or their matching target resources.

**What to do**

1. Run `nyx doctor`.
2. Confirm that Swift is detected.
3. Verify that the required iOS SDK is installed.
4. Confirm that the Swift target resources match the installed toolchain and target architecture.
5. Check the selected target and SDK in the project configuration.

Do not copy target-resource folders from unrelated Swift releases. Mismatched compiler and target resources can create additional problems.

### 3.2 `error: unexpected input file: arm64-apple-ios17.0`

**Likely cause**

A Swift compiler option and its argument have become separated or incorrectly configured.

**What to do**

Inspect `Config/Project.plist` and check the `OTHER_SWIFT_FLAGS` configuration.

Ensure options such as `-target` and their corresponding values are passed as separate, correctly paired arguments.

Compare your configuration with a freshly generated project of the same template.

### 3.3 `error: unknown argument: '-fobjc-arc'`

**Likely cause**

A Clang-specific option was supplied to the Swift compiler.

**What to do**

Review the build settings in `Config/Project.plist`.

Use the appropriate setting for each compiler:

| Setting | Intended compiler |
|---|---|
| `OTHER_CFLAGS` | Clang C and Objective-C compilation |
| `OTHER_CPLUSPLUSFLAGS` | Clang C++ compilation |
| `OTHER_SWIFT_FLAGS` | Swift compilation |

Keep language-specific compiler options in their respective settings.

### 3.4 `'stdio.h' file not found` or another C header is missing

**Possible causes**

- An incorrect SDK or include path.
- The selected SDK does not contain the expected headers.
- A custom header search path is missing.
- The build is resolving an unintended SDK.

**What to do**

1. Run `nyx doctor`.
2. Confirm the selected iOS SDK.
3. Inspect the SDK's `usr/include` directory.
4. Check any custom header search paths in the project configuration.
5. Verify that the required header actually exists.

For a project-specific header, use the appropriate include directory in `OTHER_CFLAGS`.

Example:

```text
-I
Source/Include
```

The directory must exist in the project and be accessible to the build.

---

## 4. Linker errors

### 4.1 `unknown argument: -flavor darwin`

**Likely cause**

The build is using an incompatible linker executable or resolving the wrong LLVM installation.

**What to do**

Run:

```powershell
nyx doctor
```

Confirm that NyxWin resolves the expected Darwin linker from its configured LLVM installation.

Do not assume that every `lld.exe` installation exposes identical driver behavior. Use the linker configuration documented for your installed NyxWin version.

### 4.2 `undefined symbol: ___isPlatformVersionAtLeast`

**Possible cause**

The build is missing the platform availability support required by the selected Swift runtime and target configuration.

**What to do**

1. Run `nyx doctor`.
2. Confirm that the compiler runtime resources are detected.
3. Check that the required platform support source and runtime archive are present in the installed NyxWin resources.
4. Rebuild after resolving any missing-resource diagnostics.

Do not substitute a random runtime archive from another toolchain release.

### 4.3 `framework not found`

**Possible causes**

- The selected SDK does not contain the requested framework.
- The framework name is misspelled.
- A custom framework path is incorrect.
- The framework is not included in the project configuration.

**What to do**

1. Confirm that the framework exists in the selected SDK.
2. Check the `Frameworks` configuration in `Config/Project.plist`.
3. For third-party frameworks, verify their expected location and integration requirements.
4. Check the linker output for the resolved search paths.

### 4.4 `symbol(s) not found for architecture arm64`

**Possible causes**

- A required implementation file was not compiled.
- A framework or library was not linked.
- A required function or entry point is missing.
- A library does not contain a compatible ARM64 binary.

**What to do**

Check the source files included in the project and the framework/library configuration.

For a system framework, confirm that it exists in the selected SDK and is listed in the project settings.

For a third-party library, verify its architecture and platform compatibility before linking it.

---

## 5. Signing and packaging problems

### 5.1 `ldid.exe: fatal error: unable to parse entitlements`

**Likely cause**

The entitlement property list contains malformed XML or an invalid property-list structure.

**What to do**

Inspect:

```text
Config/Entitlements.plist
```

Check for:

- Missing closing tags.
- Invalid XML structure.
- Incorrect property-list types.
- Duplicate or malformed keys.

You can test whether Python can parse the file:

```powershell
py -c "import plistlib; plistlib.load(open('Config/Entitlements.plist', 'rb')); print('Property list is valid')"
```

Only add entitlements required by the application's intended capabilities and installation environment.

### 5.2 The IPA was created, but iOS refuses to install it

**Important distinction**

A successfully generated IPA does not guarantee that the device will trust its signature.

The current NyxWin ad-hoc signing workflow does not create an Apple-issued certificate or a standard Apple provisioning profile.

**What to check**

1. Identify the device's installation environment.
2. Check whether that environment accepts the signing method used.
3. Verify the device's OS version and applicable installation requirements.
4. Determine whether the IPA needs to be re-signed with an appropriate trusted identity.

For standard non-jailbroken devices, an appropriate signing and provisioning workflow is normally required.

### 5.3 The application installs but immediately crashes

An application that installs successfully can still fail at runtime.

Possible causes include:

- Incompatible signing or entitlements.
- Missing or incorrectly linked frameworks.
- Incorrect deployment target.
- Runtime or dynamic-library incompatibility.
- Application-specific startup errors.
- Device or installation-environment restrictions.

**What to do**

Separate the failure into two questions:

1. Does the application launch in the target environment?
2. If it launches, does it fail when loading a particular framework, performing an operation or opening a screen?

Inspect the relevant application and device logs where available.

For SwiftUI applications, also ensure that the binary-processing stage completed successfully and inspect the NyxWin build report for patching or linking errors.

Do not automatically add private or privileged entitlements as a crash workaround.

### 5.4 The IPA is missing or has an unexpected size

**Possible causes**

- The build failed before packaging.
- Packaging was cancelled.
- The output path is not the path you expected.
- A previous successful artifact was preserved after a failed build.

**What to do**

Inspect the build-specific log and JSON report before attempting another build.

Confirm that the final pipeline stage completed successfully and that the reported output path points to the expected project.

---

## 6. Shell and terminal issues

### 6.1 Unicode characters display incorrectly

**Possible cause**

The current terminal is using an encoding that does not support the output characters.

**What to do**

In PowerShell, run:

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

Then reopen the terminal if the output remains incorrect.

### 6.2 PowerShell blocks `install.ps1`

**Possible cause**

The current execution policy prevents the script from running.

For a script you have obtained from a trusted NyxWin release, you can launch it with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

Review the script and its source before execution. Do not use execution-policy bypass as a reason to run an untrusted downloaded script.

---

## 7. Build logs and reports

NyxWin records build activity to help diagnose failures, cancellations and cleanup problems.

For the managed Windows installation, inspect:

```text
%LOCALAPPDATA%\NyxWin\Logs\builds\<Project>\
```

The directory can contain:

| File | Purpose |
|---|---|
| `<build_id>.log` | Build-specific human-readable log |
| `latest.log` | Convenience copy of the latest log |
| `<build_id>.json` | Build-specific structured report |
| `build_report.json` | Convenience copy of the latest report |

The exact files present depend on the build and the installed version.

### 7.1 What to inspect

Start with `latest.log` for readable compiler, linker and pipeline output.

Then inspect `build_report.json` for structured information.

Useful fields include:

- `status`: Whether the build succeeded, failed or was cancelled.
- `diagnostics`: Recorded warnings and errors.
- `command_invocations`: Tool commands, working directories and exit codes.
- `cleanup`: Process cleanup information and related results.
- Artifact information: The generated output and its recorded metadata, where available.

### 7.2 Opening the JSON report

The interactive report viewer is available in supported TUI builds.

Use the report-viewer shortcut shown by your installed NyxWin version. The viewer supports navigation and opening or copying report information.

See the [CLI and TUI Reference](COMMANDS.md) for the current keybindings.

### 7.3 Reporting a failed build

When asking for help, include:

1. NyxWin version.
2. Relevant `nyx doctor` output.
3. SDK version and deployment target.
4. The complete error message.
5. The build-specific `.log` file.
6. The matching JSON report.

Remove passwords, access tokens, private signing material and other sensitive information before sharing diagnostic files.

---

## 8. Cancellation and process cleanup

NyxWin supports graceful build cancellation.

Depending on the interface:

- **CLI:** Use `Ctrl+C`.
- **Interactive TUI:** Use the cancellation key supported by the active build screen, including `Esc` or `Q` where applicable.

When a build is cancelled, NyxWin attempts to stop the associated build processes and clean up temporary resources.

### 8.1 A build appears stuck after cancellation

**What to do**

1. Check whether the terminal is still processing cleanup.
2. Inspect the build log for cancellation and cleanup messages.
3. Open the corresponding JSON report.
4. Check whether the report records a cleanup warning or unreaped process identifiers.

Do not terminate arbitrary processes based only on a PID copied from an old report. Windows can reuse process identifiers.

If manual intervention appears necessary, identify the process and confirm that it belongs to the cancelled NyxWin build before terminating it.

### 8.2 An existing IPA disappeared or became corrupted

NyxWin's packaging workflow is designed to avoid replacing a previously completed IPA with a partially written archive.

If an interruption occurs:

1. Check the build report.
2. Inspect the project's `dist` directory.
3. Confirm the output timestamp and file size.
4. Rebuild only after determining whether the previous artifact is valid.

Keep the relevant temporary and diagnostic evidence when reporting a reproducible packaging issue.

---

## 9. When to report a bug

If the problem persists after following this guide, provide a reproducible report containing:

- NyxWin version and Windows version.
- Python, Swift and LLVM versions.
- Selected iOS SDK and deployment target.
- The command that failed.
- The complete error output.
- The relevant build log and JSON report.
- A minimal project or source example that reproduces the issue, where possible.

A precise reproduction is considerably more useful than a screenshot of an error message.

For project design and implementation questions, see [Architecture](ARCHITECTURE.md). For supported commands and options, see [CLI Reference](COMMANDS.md).

## 10. Licensing and commercial use inquiries

### 10.1 "Can I use NyxWin for personal projects or open-source apps?"
Yes. Under the PolyForm Noncommercial License 1.0.0, personal use, hobbyist experimentation, academic research, education, and non-commercial software development are fully permitted without payment or royalty.

### 10.2 "Can our company use NyxWin internally or build commercial apps with it?"
Commercial use, including commercial iOS app production, fee-earning development, or proprietary integration, requires a separate commercial license agreement signed by the project owner. Commercial licensing terms will be made available directly by the project owner upon request.

### 10.3 "Are third-party tools like ldid covered by the PolyForm license?"
No. Third-party tools such as `ldid` (GPLv3/AGPLv3) and LLVM runtime libraries (Apache-2.0 with LLVM Exception) remain under their own respective licenses. See `src/nyxwin/resources/tools/THIRD_PARTY_NOTICES.md`.
