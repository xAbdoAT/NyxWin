# NyxWin Architectural Roadmap & Enhancements Guide
### Native Windows iOS Development Engine
**Maintained by Abdo AT ([@xAbdoAT](https://github.com/xAbdoAT))**

This document outlines the architectural roadmap for **NyxWin** (native Windows iOS toolchain), cataloging upcoming features, system enhancements, and integration guides for **`pymobiledevice3`** for one-click deployment, live log streaming, and device installation from Windows.

---

## 1. Feature Status & Capabilities Matrix

| Feature | Current NyxWin Architecture | Planned Enhancement | Status |
| :--- | :---: | :---: | :---: |
| **Cross-Compilation (C/ObjC)** | ✅ (`clang.exe` 23+) | Parallel multithreaded builds | Completed |
| **Cross-Compilation (Swift/SwiftUI)** | ✅ (`swiftc.exe` 6.4+) | Whole-module optimization & caching | Completed |
| **Mach-O Linking** | ✅ (`ld64.lld.exe`) | Auto-links Apple `.tbd` text stubs | Completed |
| **SwiftUICore Compatibility** | ✅ **Patch #31** | Rewrites weak dylib & chained fixups | Completed |
| **Ad-Hoc Signing & Entitlements** | ✅ (`ldid.exe`) | Custom & Least-privilege profile resolution | Completed |
| **Native Project Schema v1.0** | ✅ Native Independent Schema | Lossless normalization of legacy projects | Completed |
| **C/ObjC <-> Swift Bridging Header** | ❌ Manual flags | Auto-detect `Bridging-Header.h` (`-import-objc-header`) | **P1 (Next)** |
| **Instant Device Install Service** | ❌ Manual file transfer | One-click local HTTP server + QR code / URL | **P2** |
| **VS Code / Desktop IDE IntelliSense** | ❌ Configuration needed | `nyx ide-setup` (c_cpp_properties & Swift LSP) | **P3** |
| **Native `Assets.car` Compilation** | ⚠️ Loose asset flattener | Compile with native `actool.exe` (Rust) | **P4** |
| **Live Device Logs & Debugging** | ❌ None | Live `oslog` streaming via `pymobiledevice3` | **P5** |
| **USB Direct Sideload / Install** | ❌ None | Direct USB deployment via `pymobiledevice3` | **P5** |
| **XCFramework Slicing & Static Libs** | ⚠️ `.framework` only | Auto-slice `ios-arm64` & link `.a` archives | **P6** |
| **Debian `.deb` Packaging** | ❌ (Only `.ipa`) | `nyx package --deb` for Sileo/Zebra | **P7** |
| **TUI Project Search & Filtering** | ❌ Linear list | Filter bar (`/`) in TUI dashboard | **P8** |

---

## 2. Priority Enhancements Breakdown

### P1: Objective-C / C Bridging Header Support
* **Problem**: Many low-level iOS apps (such as `ProcKill`) use Mach kernel APIs, Darwin `sysctl`, and private Objective-C classes alongside SwiftUI. Currently, Swift files cannot access types defined in C/ObjC headers without manual flags.
* **Solution**:
  1. In build pipeline (Step 1), check for `Bridging-Header.h` or `<ProjectName>-Bridging-Header.h` in `project_dir` or `Config/`.
  2. If detected, pass `-import-objc-header <path/to/header.h>` to `swiftc.exe`.
  3. Ensure include paths (`-I`) are propagated to the Swift compiler invocation.

### P2: One-Click Instant TrollStore Install (Local HTTP + QR Code)
* **Problem**: After compiling an `.ipa`, the developer must manually send the file over AirDrop, iCloud Drive, or cable.
* **Solution**:
  1. Add a command: `nyx serve <Project>` or option in TUI menu.
  2. Spawns a background Python HTTP server serving the `.ipa`.
  3. Displays an ASCII QR code in the terminal and generates the standard TrollStore URL:
     ```text
     apple-magnifier://install?url=http://<PC_LOCAL_IP>:<PORT>/<AppName>.ipa
     ```
  4. Scanning with the iPhone Camera or tapping the link in Safari triggers TrollStore to immediately download and install the app in under 2 seconds.

### P3: VS Code / Cursor IDE Integration (`nyx ide-setup`)
* **Problem**: Opening NyxWin projects in VS Code produces red error squiggles for `import SwiftUI`, `#include <UIKit/UIKit.h>`, etc., because VS Code doesn't know where the Windows-hosted iOS SDK headers are.
* **Solution**:
  1. Add `nyx ide-setup <Project>` command.
  2. Generates `.vscode/c_cpp_properties.json`:
     - Sets include paths to `sdk/iPhoneOS26.5.sdk/usr/include` and `System/Library/Frameworks`.
     - Configures IntelliSense mode for `clang-arm64`.
  3. Generates `.vscode/settings.json`:
     - Configures `sourcekit-lsp.serverPath` pointing to Swift for Windows.
     - Adds SDK sysroot flags so Swift autocomplete works out of the box.

### P4: Native `Assets.car` Compilation (`viraptor/actool`)
* **Problem**: Apple's closed-source `actool` is macOS-only. On Windows, compiling `.car` asset catalogs requires a dedicated tool, and NyxWin currently flattens assets to loose PNGs.
* **Solution**:
  1. Build `viraptor/actool` (open-source Rust rewrite of Apple's BOM/CoreUI asset catalog compiler) for Windows target `x86_64-pc-windows-msvc`.
  2. Place `actool.exe` into `tools/`.
  3. Update Step 6 of `cmd_build` to compile `.xcassets` into real `Assets.car`, supporting dynamic colors, vector assets, and system symbol images.

---

## 3. Deep Dive: `pymobiledevice3`

### What is `pymobiledevice3`?
[`pymobiledevice3`](https://github.com/doronz88/pymobiledevice3) is a pure-Python 3 implementation of Apple's proprietary **Lockdown protocol** and associated iOS system services. It communicates with connected iPhones, iPads, and Apple TVs over USB (via the `usbmuxd` Windows service installed with iTunes / Apple Mobile Device Support) or wirelessly over Wi-Fi.

Unlike legacy C libraries like `libimobiledevice`, `pymobiledevice3` is actively maintained for modern iOS versions (including the radical architectural changes introduced in iOS 17 and iOS 18).

---

### What is it Capable of Doing?

1. **Lockdown & Device Pairing**:
   - Performs SSL handshake with iOS devices.
   - Reads UDID, device model, battery health, iOS build version, and serial number.
2. **App Management & Installation**:
   - Queries installed apps, bundle IDs, and container paths via `installation_proxy`.
   - Installs and uninstalls developer-signed or enterprise `.ipa` packages.
3. **Developer Disk Image (DDI) & RemoteXPC Tunneling**:
   - In iOS 17 and iOS 18, Apple deprecated old lockdown services and migrated developer services over a secure **RemoteXPC / QUIC tunnel**.
   - `pymobiledevice3` includes a built-in `remote tunneld` daemon that handles this tunnel on Windows, allowing Developer Mode features to function.
4. **Live System & App Log Streaming**:
   - Streams unified console logs (`oslog`) and `syslog` in real time with line filtering by process name or bundle ID.
5. **Debugging & Process Control**:
   - Mounts `debugserver` to connect LLDB directly to running iOS processes.
   - Launches apps via Developer Launch Services (`developer app launch <bundle_id>`).
   - Retrieves crash logs and stack traces (`crash report`).
6. **File System Access (AFC / HouseArrest)**:
   - Reads and writes files to app sandbox document directories via Apple File Conduit (AFC).

---

### Which iOS Versions Are Supported?

* **iOS 8.0 through iOS 16.7**: Full native support via standard lockdown sockets and USBMUX.
* **iOS 17.0 through iOS 18.x+**: Fully supported via the `pymobiledevice3 remote tunneld` service (Personalized Developer Disk Image and RemoteXPC QUIC handshake).

---

### Can `pymobiledevice3` Install an `.ipa` from Windows to a Non-Jailbroken iPhone with TrollStore?

#### The Short Answer:
**Indirectly, YES (and with near-zero friction); directly via Apple's `installation_proxy`, NO.**

#### Why Apple's Normal Service Fails for TrollStore IPAs:
* When `pymobiledevice3 apps install MyApp.ipa` is run, it speaks to Apple's native iOS daemon: **`mobile_installation_proxy`**.
* Even if the device has TrollStore installed, Apple's `installation_proxy` is strictly enforced by iOS kernel code-signing policies (`amfid`).
* It checks for:
  1. An official Apple Developer certificate.
  2. An embedded `.mobileprovision` provisioning profile containing the device's UDID.
* Because NyxWin generates **ad-hoc / pseudo-signed** binaries with root or unsandboxed entitlements (`platform-application`, `no-sandbox`, etc.), passing them through Apple's normal `installation_proxy` will immediately throw:
  ```text
  ApplicationVerificationFailed (0xe8008015): The signature was not valid.
  ```

#### How TrollStore Actually Installs Apps:
TrollStore works by exploiting Apple's **CoreTrust bug** (CVE-2022-26766 / CVE-2023-41991). It bypasses `amfid` entirely by registering fake root certificates and modifying the system launch services database directly on disk. Only **TrollStore itself** (or its helper binary `trollstorehelper`) can perform this rootless installation.

---

### How to Achieve Seamless Installation from Windows to TrollStore:

To get a 1-click install experience from Windows to a TrollStore iPhone, NyxWin can use three methods:

#### Method 1: Automated Local Web Server + Safari / TrollStore URL Scheme (Zero Dependencies)
1. NyxWin builds `MyApp.ipa` into `Output/`.
2. NyxWin starts a lightweight, temporary Python HTTP server bound to your local Wi-Fi IP (e.g. `http://<LOCAL_IP>:8080/MyApp.ipa`).
3. TrollStore natively registers the custom URL handler:
   ```text
   apple-magnifier://install?url=http://<LOCAL_IP>:8080/MyApp.ipa
   ```
4. **Triggering on iOS**:
   - NyxWin prints a QR code in PowerShell. Point your iPhone camera at the screen and tap the yellow button -> TrollStore immediately downloads and installs it.
   - *Optionally with `pymobiledevice3`*: If connected via USB with Developer Mode, `pymobiledevice3` can send a command to SpringBoard to open this URL automatically on your device screen!

#### Method 2: AFC Push to Shared Folder + TrollStore Auto-Import
1. Using `pymobiledevice3 afc`, NyxWin pushes the `.ipa` over USB directly into a monitored folder on the device (e.g., inside TrollStore's container or a shared iCloud/Documents folder).
2. TrollStore picks up the `.ipa` and installs it.

#### Method 3: Dropship via Dropbear / OpenSSH (For Devices with SSH Installed)
1. If the user installed an SSH package through TrollStore or a rootless jailbreak:
2. NyxWin connects over USB via `usbmuxd` port forwarding (port 22 -> 2222).
3. Pushes the `.ipa` via SCP and runs:
   ```bash
   trollstorehelper install /var/mobile/MyApp.ipa
   ```
4. Complete silent, zero-touch installation in 1.5 seconds!

#### Real Device Testing Verification Note:
Automated device testing during NyxWin development was performed against a physical iPhone XS (iOS 17.0, RootHide jailbreak) using `mcp-appinst` / AppSync Unified over USB. AppSync Unified dynamically patches `amfid` and `MobileInstallation`, allowing ad-hoc signed IPAs to be installed and verified without `trollstorehelper` or Apple Developer certificates. TrollStore installation remains a separate deployment pathway for end-users on iOS 14.0–17.0.

---

## 4. Implementation Status & Next Milestones

> [!NOTE]
> All features and enhancements documented below are preserved as prioritized roadmap milestones for future development. No changes are currently being made to the core build engine or menu until ready to begin implementation.

* **Milestone 1**: Objective-C / C Bridging Header auto-detection (`-import-objc-header`) in compiler pipeline
* **Milestone 2**: Instant TrollStore HTTP micro-server & terminal QR code installer (`nyx serve`)
* **Milestone 3**: VS Code / Cursor IDE environment generator (`nyx ide-setup`)
* **Milestone 4**: Native `Assets.car` asset catalog compiler (`tools/actool.exe` via Rust)
* **Milestone 5**: Device log streaming & USB diagnostics integration (`pymobiledevice3`)
* **Milestone 6**: Debian `.deb` rootless packaging (`nyx package --deb`)
* **Milestone 7**: TUI quick search & project filtering in TUI menu
