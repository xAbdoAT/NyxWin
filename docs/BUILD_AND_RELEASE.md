# Build, Packaging & Release

This guide describes NyxWin's development build environment, test workflow, Python distribution process and release verification requirements.

It is intended for project maintainers and contributors.

For end-user installation, see [Installation & Setup](SETUP_GUIDE.md).

---

## 1. Project structure

NyxWin separates application source code, development resources, user data and generated application projects.

### Source repository

The repository contains the application and its development infrastructure:

```text
NyxWin/
├── src/
│   └── nyxwin/
│       ├── build/          # Compilation and packaging pipeline
│       ├── config/         # Configuration and path handling
│       ├── core/           # Project models and migration
│       ├── services/       # Application services
│       ├── tui/             # Terminal user interface
│       └── resources/
│           ├── tools/      # Bundled native tools and runtime files
│           └── templates/  # Application templates
├── docs/
├── pyproject.toml
├── install.ps1
├── install.bat
└── README.md
```

The exact file inventory evolves with the project.

The repository is not intended to be the default destination for user projects, large SDK downloads or generated build intermediates.

### Managed Windows installation

The standard managed installation uses:

```text
%LOCALAPPDATA%\NyxWin/
├── app/          # Managed application installation
├── bin/          # Global command launchers
├── SDKs/         # iOS SDKs and Swift target resources
├── Build/        # Temporary build workspaces
├── Cache/        # Compiler and module caches
├── Backups/      # Project recovery snapshots
├── Logs/         # Build logs and JSON reports
└── Settings/     # Runtime settings
```

User-specific configuration is stored separately under:

```text
%APPDATA%\NyxWin\
```

The default projects directory is:

```text
%USERPROFILE%\NyxProjects\
```

Individual projects may be stored elsewhere.

A generated application package is normally placed in the project's `dist/` directory.

## 2. Development environment

The development environment requires:

- Windows 10 or Windows 11, x64.
- Python 3.10 or newer, subject to release compatibility.
- LLVM Clang and the required linker.
- Swift for Windows for Swift application builds.
- A compatible iOS SDK and Swift target resources.
- NyxWin's bundled runtime tools.
- Python development and testing dependencies.

See [Windows Dependencies](WINDOWS_DEPENDENCIES.md) for the complete dependency overview.

### Install the tool

Contributors and end users use the same installer. From a checkout, run `install.bat` or `install.ps1`. That registers the `nyx` command. Do not pip-install this repository.

Install additional development dependencies according to the project's declared development requirements.

After installation:

```powershell
nyx --version
nyx doctor
```

Verify that the application resolves the expected source checkout and toolchain.

## 3. Build pipeline

NyxWin uses six main build stages:

```text
SCAN → COMPILE → LINK → PATCH → SIGN → PACKAGE
```

| Stage   | Responsibility                                            |
| ------- | --------------------------------------------------------- |
| SCAN    | Inspect project structure, source files and configuration |
| COMPILE | Compile Swift and C-family source files                   |
| LINK    | Resolve frameworks and produce Mach-O executables         |
| PATCH   | Apply required binary-processing operations               |
| SIGN    | Apply the configured signing and entitlement workflow     |
| PACKAGE | Assemble the application bundle and IPA archive           |

A successful build should reach the final packaging stage and report the generated artifact location.

The pipeline also collects build diagnostics and cleanup information.

For internal implementation details, see [Architecture](ARCHITECTURE.md).

## 4. Building a project

Create a test project or use an existing development project.

For example:

```powershell
nyx new swiftui BuildExample --bundle-id com.example.buildexample
```

Build it:

```powershell
nyx build BuildExample
```

Enable verbose output when investigating compiler or linker issues:

```powershell
nyx build BuildExample --verbose
```

A successful build should produce an IPA under:

```text
<ProjectDirectory>\dist\<ProjectName>.ipa
```

Do not treat a successful compiler exit alone as proof that the application is installable or trusted by iOS. Signing, packaging and target-device verification are separate concerns.

## 5. Regression testing

The public repository does not include the local test suite. Maintainer verification covered areas such as:

- Project configuration and migration.
- Canonical path handling.
- Backup and restoration behavior.
- Build pipeline components.
- Process management and cleanup.
- Build logs and structured reports.
- Deterministic packaging.
- CLI and TUI behavior.
- Security and input validation.

### Recorded Stage 1 test evidence

The accepted Stage 1 verification reported:

| Test group                           | Recorded result      |
| ------------------------------------ | -------------------- |
| Full unit suite                      | 287 passed           |
| Stage 1 focused suite                | 73 passed            |
| Integration suite                    | 18 passed, 4 skipped |
| Individually executed live SDK tests | 4 passed             |

The four individually executed SDK tests must remain distinct from the integration-suite result. They were run separately because of test-environment fixture behavior.

Historical results should not be represented as tests rerun against a later release candidate.

## 6. Live toolchain verification

Unit tests alone do not establish that the complete toolchain can build real applications.

Before accepting changes to the compiler, linker, SDK, runtime or packaging pipeline, verify real application builds.

The Stage 1 acceptance procedure included:

- A SwiftUI application build.
- A UIKit application build.
- Full execution of the six-stage build pipeline.
- Inspection of generated IPA files.
- Inspection of persistent text logs and JSON reports.
- Deterministic packaging verification.
- Process cancellation and cleanup tests.

Device validation should be recorded separately from build validation.

Manual testing performed by a user must be identified as user-reported. Automated MCP testing must be reported separately.

Do not claim universal compatibility based on a limited set of devices or operating-system versions.

## 7. Persistent build evidence

Managed installations record build information under:

```text
%LOCALAPPDATA%\NyxWin\Logs\builds\<Project>\
```

The directory may contain:

```text
<build_id>.log
latest.log
<build_id>.json
build_report.json
```

The text log records human-readable build output.

The JSON report stores structured information about the build, including applicable:

- Build status.
- Start and finish timestamps.
- Stage durations.
- Toolchain information.
- Command invocations and exit codes.
- Warnings and errors.
- Cleanup results.
- Artifact metadata.

Build Report JSON Schema v1.0 is distinct from Canonical Project Schema v2.0.

Do not conflate the version numbers or responsibilities of these schemas.

## 8. Deterministic IPA packaging

The packaging system is designed so that an unchanged, already-signed application bundle can produce a reproducible IPA archive.

Deterministic packaging relies on normalized archive metadata and consistent ordering.

The verification process should confirm:

- The same input application bundle is used for each run.
- Archive entries use deterministic ordering.
- Timestamps are normalized.
- File permissions are normalized.
- Unwanted operating-system and temporary files are excluded.
- The resulting IPA SHA-256 hashes are identical.

Do not use different application inputs when comparing packaging results.

The canonical timestamp and other archive metadata must be verified against the current implementation and regression tests before documenting an exact value.

## 9. Cancellation and cleanup verification

NyxWin manages external build processes and supports graceful cancellation.

Test cancellation at relevant points in the build lifecycle.

Verify:

- The cancellation request propagates to the running build.
- Associated subprocesses are terminated or reaped.
- Cleanup diagnostics are recorded.
- Temporary output is handled safely.
- Previously completed application artifacts are preserved.
- The final build result correctly distinguishes success, failure and cancellation.

Cancellation tests should include both normal termination and cases requiring forced cleanup.

Do not rely only on the root process exit code to establish that its descendants have terminated.

## 10. Release distribution model & assets

NyxWin is distributed as a standalone Windows command-line developer tool, **not** as a Python library or prebuilt wheel package. End users must not be instructed to install a `.whl` or source tarball via `pip`.

The product is the `nyx` and `nyxwin` command-line interface available from any Windows console.

### Official release assets

Future public GitHub Releases distribute exclusively:

1. `install.ps1` — Automated PowerShell installer and environment bootstrap script.
2. `install.bat` — One-click batch launcher wrapping `install.ps1`.
3. `swift_resources.zip` — Architecture resources (`arm64`, `arm64e`) for the Swift iOS cross-compiler.
4. `SHA256SUMS.txt` — Cryptographic checksums covering the three assets above.

No `.whl` or `.tar.gz` packages are published as user-facing release assets.

### Internal packaging metadata

`pyproject.toml` remains only so tests and the project version keep working. It is not an install method. Do not pip-install this repository.

## 11. Clean installation & CLI shim testing

Release testing must verify the installer and CLI shims independently of the developer checkout, without requiring a prebuilt wheel.

### CLI shim verification

The supported command execution model relies on standalone Windows command shims (`nyx.cmd` and `nyxwin.cmd`) written to `%LOCALAPPDATA%\NyxWin\bin`. These shims set `PYTHONPATH` to the managed application source directory and execute `main.py`.

To test CLI shims in an isolated environment outside the repository:

```powershell
# 1. Create an isolated temporary directory for the shim test
$testDir = Join-Path $env:TEMP "NyxWinShimTest"
New-Item -ItemType Directory -Force -Path $testDir | Out-Null

# 2. Generate a test shim pointing to the application source tree
$repoRoot = "C:\Path\To\NyxWin"
$srcDir = Join-Path $repoRoot "src"
$mainPy = Join-Path $repoRoot "main.py"
$shim = "@echo off`r`nset `"PYTHONPATH=$srcDir;%PYTHONPATH%`"`r`n`"py.exe`" `"$mainPy`" %*`r`n"
Set-Content -Path (Join-Path $testDir "nyx.cmd") -Value $shim -Encoding UTF8

# 3. Test execution from an unrelated working directory
$workDir = Join-Path $env:TEMP "NyxWinWorkDir"
New-Item -ItemType Directory -Force -Path $workDir | Out-Null

& (Join-Path $testDir "nyx.cmd") --version
& (Join-Path $testDir "nyx.cmd") --help
```

Verify that both commands exit with code 0 and output the expected NyxWin version.

### Installer verification

Test that `install.ps1` and `install.bat` succeed in bootstrapping the source tree, writing the CLI shims, and registering user environment variables without requiring a `.whl` package to be built or downloaded.

## 12. Installer and updater verification

The bootstrap installer and self-updater are separate release components and require independent verification.

Before a production release, test:

- Fresh installation.
- Update from an existing installation.
- Failed network download.
- Failed dependency installation.
- Failed package replacement.
- Recovery of the previous working installation.
- Correct PATH configuration.
- Correct application and SDK paths.
- Integrity verification of external downloads.
- Accurate error reporting and process exit codes.

The installer must not destroy a working installation before a replacement has been downloaded and validated.

External binaries and SDK archives should be checked against trusted, pinned integrity information. Never invent or guess expected hashes.

**Installer status:** The installer is the public install path and stops with fail if a required download does not succeed.

## 13. Release source integrity

A release must be built from a complete, intentional source snapshot.

The source snapshot must include all required production changes and their dependencies.

Before release preparation:

1. Confirm the repository root, active branch and commit.
2. Inspect all tracked modifications.
3. Inspect all untracked files.
4. Identify the intended production source set.
5. Confirm tests and development tooling are accounted for.
6. Verify the package and source-distribution contents.
7. Confirm the protected signer file remains unchanged.

Do not use `git add -u` as a substitute for reviewing new production files. New files required by modified code must be explicitly included in the intended integration.

The `signer.py` integrity baseline recorded for the current project is:

```text
C82F781ADC1BEC520D82330F8D1174E4E7DF2F2812812011DA348FB08712BAB0
```

A release verification should compare the actual file hash with this expected value.

## 14. Versioning and release metadata

NyxWin's application version and the version of a generated iOS project are different concepts.

The NyxWin package version is defined by its application packaging metadata.

The `MARKETING_VERSION` value in generated project templates refers to the user's iOS application and must not be changed merely to bump the NyxWin package version.

Before preparing a release, reconcile:

- `pyproject.toml`.
- `src/nyxwin/__init__.py`.
- CLI version output.
- README and release documentation.
- Changelog.
- Package metadata.
- Release archive filenames.
- Installer and updater references.

Historical release records should remain historical.

## 15. Release verification checklist

Before publication, complete the following checks.

### Source and metadata

- [ ] All intended source changes are integrated.
- [ ] Required new modules are present.
- [ ] Test and development files are accounted for.
- [ ] Version metadata is consistent.
- [ ] Historical changelog entries remain unchanged.
- [ ] Signer integrity hash matches.

### Automated verification

- [ ] Full unit suite passes.
- [ ] Integration results and skips are explained.
- [ ] Live SDK tests are completed.
- [ ] SwiftUI and UIKit builds succeed.
- [ ] Deterministic packaging is verified.
- [ ] Cancellation and cleanup are tested.

### Distribution

- [ ] `install.bat` and `install.ps1` are the only install path.
- [ ] No wheel or source tarball is attached to the release.
- [ ] After install, `nyx` runs from a folder that is not the repository.
- [ ] Clean-environment installation succeeds.
- [ ] Required runtime resources are present.
- [ ] External dependency integrity is verified.

### Installation and device verification

- [ ] Fresh installation succeeds.
- [ ] Update and rollback behavior is tested.
- [ ] Failed installations produce clear errors.
- [ ] Manual or automated device tests are separately documented.
- [ ] Signing and installation limitations are accurately described.

### Publication

- [ ] Release notes are reviewed.
- [ ] Artifact SHA-256 checksums are generated.
- [ ] Artifacts are independently verified.
- [ ] The release commit and tag are reviewed.
- [ ] The public tag is v1.1.0, the first tag of this repository.
- [ ] Licensing reset documentation and PolyForm Noncommercial notice are verified.
- [ ] Publication is explicitly authorized.

Do not publish a release merely because the local working tree passes tests.

---

## 16. Safe handling of build artifacts

Packaging and testing may generate temporary directories such as:

```text
build/
dist/
*.egg-info/
.pytest_cache/
__pycache__/
```

These directories may contain useful outputs and release artifacts.

Inspect their contents before removing anything.

Avoid broad recursive deletion commands against the repository root. Never remove an existing `dist/` directory without checking whether it contains artifacts that need to be retained.

Prefer dedicated temporary directories for isolated packaging and installation tests.

---

## 17. Release and development separation

NyxWin's release workflow must remain separate from future feature development.

Stage 2 and later roadmap work follows the published v1.1.0 release.

v1.1.0 is the published source baseline, with the installer as the public install path.

Future development continues on the approved roadmap.

For current development priorities, see [Roadmap & Development](ROADMAP_AND_ENHANCEMENTS.md).
