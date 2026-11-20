# NyxWin

**Build native iOS applications on Windows.**

NyxWin is a Windows-based cross-compilation toolchain for building native iOS applications from Swift, SwiftUI, UIKit, C, Objective-C and C++ projects.

It brings the essential stages of an iOS build workflow to Windows — without requiring a macOS host, Xcode or WSL.

> **Status:** NyxWin v1.1.0 is the current public release. Install it from PowerShell, then use the `nyx` command.

---

## Overview

NyxWin provides a complete build workflow for turning source code into iOS application packages.

The build pipeline handles:

`SCAN` → `COMPILE` → `LINK` → `PATCH` → `SIGN` → `PACKAGE`

Its main components include:

- **Native compilation** — Swift and C-family compilation using Windows-hosted toolchains.
- **iOS project templates** — Start with SwiftUI or UIKit application projects.
- **Mach-O processing** — Link and prepare compiled binaries for iOS.
- **Code signing and packaging** — Assemble application bundles and IPA archives.
- **Build diagnostics** — Persistent logs, structured JSON reports and stage-level timing information.
- **Build control** — Graceful cancellation and subprocess cleanup.
- **Project safety** — Configuration validation, data migration and backup facilities.

## Install

Open PowerShell and paste this. It downloads NyxWin, installs anything missing, skips what is already installed, and puts `nyx` on your PATH.

```powershell
iex (irm https://raw.githubusercontent.com/xAbdoAT/NyxWin/main/install.ps1)
```

Close that window and open a new one. Then:

```powershell
nyx doctor
```

`nyx` works from any folder after that. Details are in the [Installation & Setup Guide](docs/SETUP_GUIDE.md).

## Getting started

Once installed, the usual workflow looks like this:

```powershell
# Check the toolchain
nyx doctor

# Create a SwiftUI project
nyx new swiftui MyApp --bundle-id com.example.myapp

# Or create a UIKit project
nyx new swift-uikit MyUIKitApp

# Build the application
nyx build MyApp

# Open the interactive menu
nyx
```

The resulting application package is placed in the project's `dist` directory.

For additional commands and options, see the [CLI Reference](docs/COMMANDS.md).

## Documentation

NyxWin's documentation is organized by topic. You do not need to understand the entire toolchain to get started.

| Guide | Description |
|---|---|
| [Installation & Setup](docs/SETUP_GUIDE.md) | Environment requirements, installation and initial configuration |
| [CLI Reference](docs/COMMANDS.md) | Commands, options and usage examples |
| [Architecture](docs/ARCHITECTURE.md) | Build pipeline, internal components and system design |
| [Build & Release](docs/BUILD_AND_RELEASE.md) | Packaging, distribution and release procedures |
| [Data Migration](docs/DATA_MIGRATION.md) | Project data locations, migration and preservation |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | Common issues and diagnostic procedures |
| [Roadmap](docs/ROADMAP_AND_ENHANCEMENTS.md) | Completed milestones and planned development |

## Signing and device compatibility

NyxWin's current build workflow uses ad-hoc code signing and produces iOS application packages.

A successfully generated IPA is not automatically trusted by every iOS device. Installation and execution depend on the device, iOS version, signing method and applicable platform restrictions.

Standard non-jailbroken devices generally require an appropriate trusted signing and provisioning workflow. Jailbroken and other specialized installation environments have their own compatibility requirements.

See the setup and troubleshooting guides before relying on a particular device or installation method.

## Project status

NyxWin is actively developed, and its architecture and feature set are still evolving.

The current priorities include improving build reliability, installation safety, distribution, diagnostics and the overall developer experience.

The public name of this release is **NyxWin**.

## Inspiration

The original direction and naming of this project were influenced in part by [Nyxian](https://github.com/emexlab/Nyxian), an iOS-focused development project by emexLabs.

NyxWin pursues a different workflow, focusing on building iOS applications from a Windows development environment. It is a separate project and is not affiliated with or endorsed by emexLabs.

## License & Commercial Use

NyxWin source code and project documentation are published under the **PolyForm Noncommercial License 1.0.0**.

Under this license:
* **Personal & Hobbyist Use:** Free to run, study, modify, and build iOS applications for personal projects, research, self-study, hobbyist pursuits, and amateur experimentation.
* **Permitted Organizations:** Educational institutions, charitable organizations, public research organizations, public safety or health organizations, environmental protection organizations, and government institutions may freely use, modify, and deploy NyxWin royalty-free, regardless of funding sources or obligations.
* **Community Forks & Sharing:** You may create forks, build independent modified versions, and distribute them for permitted non-commercial purposes, provided you include the original copyright notice and license terms.
* **No Forced Sharing of Private Modifications:** You are under no copyleft obligation to publish private modifications or internal tools.
* **Commercial Authorization Required:** Any use primarily intended for or directed towards commercial advantage or monetary compensation by commercial businesses or developers (outside the expressly permitted organizational exceptions above) requires a separate written commercial license agreement executed with the project owner. Commercial licensing terms will be made available directly by the project owner upon request.
* **Source-Available, Not OSI Open Source:** Because this license restricts commercial use, it is classified as a source-available, non-commercial community license rather than an OSI-approved open-source license.

### Third-Party Components & Notices

Third-party tools, libraries, runtimes, and template resources carry their own separate licenses and attribution notices and are **not** governed by the PolyForm Noncommercial License. See [THIRD_PARTY_NOTICES.md](src/nyxwin/resources/tools/THIRD_PARTY_NOTICES.md) for full details:
* **ldid (`src/nyxwin/resources/tools/ldid.exe`):** Mach-O code signing utility. Bundled with `LICENSE-GPLv3.txt`; upstream source header specifies AGPL-3.0-only; statically embeds OpenSSL and libplist. (Licensing status is recorded as deferred).
* **LLVM / Clang Runtime (`src/nyxwin/resources/tools/libclang_rt.ios.a`):** Universal ARM64/ARM64e compiler runtime builtins archive. Associated with Apache License 2.0 with LLVM Exception (`LICENSE-APACHE2-LLVM.txt`), with upstream provenance recorded as deferred.
* **iOS Starter Templates (`src/nyxwin/resources/templates/`):** Standard Apple API boilerplate adapted from open community layouts.
* **Apple iOS SDK Management (`src/nyxwin/services/sdk_manager.py`):** Automated download helper for community-hosted iOS SDK packages (`xybp888/iOS-SDKs`). Redistribution rights and platform copyright caveats remain deferred.
