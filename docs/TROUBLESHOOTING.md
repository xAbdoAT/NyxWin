# NyxWin Troubleshooting Guide

This guide covers common errors, causes, and solutions encountered when compiling and packaging iOS applications on Windows.

---

## 1. Toolchain & Environment Diagnostics

Whenever an unexpected error occurs, run:
```powershell
nyx doctor
```
Verify that all 8 toolchain items are marked with `[OK]`. If any tool shows `[MISSING]`, follow the resolution steps printed by `doctor`.

---

## 2. Compilation Errors

### 2.1 `error: unknown argument: '-fobjc-arc'`
- **Cause**: Clang-specific compilation flags were passed to `swiftc.exe`.
- **Solution**: NyxWin separates `ClangFlags` and `SwiftFlags` in `src/nyxwin/build/pipeline.py`. If modifying project plists manually, ensure Clang arguments (`-fobjc-arc`, `-isysroot`) remain under `ClangFlags` and Swift options remain under `SwiftFlags`.

### 2.2 `error: cannot find 'SwiftUI' in scope` or `no such module 'SwiftUI'`
- **Cause**: Missing iOS target definitions in Swift resource directory.
- **Solution**: Ensure `%LOCALAPPDATA%\Programs\Swift\Toolchains\<version>\usr\lib\swift\iphoneos` contains `arm64` and `arm64e` target definitions. NyxWin automatically checks `sdk/swift_resources/swift/iphoneos`. If missing, run `install.bat` to restore bundled target resources.

### 2.3 `error: unexpected input file: arm64-apple-ios17.0`
- **Cause**: An option flag in `SwiftFlags` (such as `-target`) was omitted or stripped, causing the compiler to interpret the option argument as a source file.
- **Solution**: Check `Config/Project.plist` in your project. Ensure flags and arguments are properly paired.

### 2.4 C/ObjC Header Not Found (`'MyHeader.h' file not found`)
- **Cause**: Missing header search path in `Config/Project.plist`.
- **Solution**: Add `-I` followed by the directory path under `ClangFlags` in `Project.plist`:
  ```xml
  <string>-I</string>
  <string>Source/Include</string>
  ```
  Or if using an Objective-C Bridging Header with Swift, ensure it is named `<AppName>-Bridging-Header.h` and placed in the project root, `Config/`, or `Source/`.

---

## 3. Linker Errors (`ld64.lld`)

### 3.1 `undefined symbol: ___isPlatformVersionAtLeast`
- **Cause**: Swift standard library binaries on iOS 17+ call Darwin availability checking builtins not present in standard Windows cross-compilation environments.
- **Solution**: NyxWin automatically compiles `src/nyxwin/resources/tools/platform_check.c` into `platform_check.o` and links it into every binary. If missing, run `nyx doctor` to verify `platform_check.c`.

### 3.2 `framework not found <FrameworkName>`
- **Cause**: The framework is not present in the selected SDK.
- **Solution**:
  1. Check the SDK with `nyx doctor`.
  2. If using custom frameworks, place the `.framework` directory inside `Projects/<Project>/Frameworks/`. NyxWin automatically discovers, embeds, and signs custom frameworks into `Payload/<App>.app/Frameworks/`.

### 3.3 `symbol(s) not found for architecture arm64`
- **Cause**: A required C or Objective-C library was not linked, or an implementation file was omitted from compilation.
- **Solution**:
  1. If linking system frameworks, add `-framework <Name>` to `LinkerFlags` in `Config/Project.plist`.
  2. For C/ObjC projects, ensure your entry point function (`int main(...)`) exists.

---

## 4. Signing & Packaging Errors

### 4.1 `ldid.exe: fatal error: unable to parse entitlements`
- **Cause**: Malformed XML or unclosed tags in `Config/Entitlements.plist`.
- **Solution**: Open `Config/Entitlements.plist` in an XML editor or run `nyx menu -> 3. Edit Entitlements` to inspect and regenerate clean XML.

### 4.2 App Installs but Immediately Crashes on Device
- **Cause 1 (TrollStore Apps)**: TrollStore applications requiring root or unsandboxed execution must have `platform-application` and `com.apple.private.security.no-sandbox` enabled in entitlements. Rebuild with:
  ```powershell
  nyx build MyApp --profile trollstore
  ```
- **Cause 2 (SwiftUI Apps)**: Missing Mach-O patch for `SwiftUICore`. NyxWin automatically applies Mach-O Patch #31 to redirect and resolve dynamic symbols. Verify that `src/nyxwin/resources/tools/patch_macho.py` is present and reported `[OK]` in `nyx doctor`.

---

## 5. Device Execution & Installation Context

### 5.1 Ad-Hoc Signatures vs Stock iOS Security
NyxWin uses `ldid.exe` to produce ad-hoc pseudo-signatures (`LC_CODE_SIGNATURE` load command with embedded entitlements). These signatures:
- Contain no Apple certificate authority or cryptographic trust chain.
- Are accepted by jailbroken devices running **AppSync Unified** (which hooks `amfid` and `MobileInstallation` at runtime).
- Are accepted by **TrollStore** on iOS 14.0 – 17.0 (which leverages Apple CoreTrust vulnerabilities CVE-2022-26766 / CVE-2023-41991).
- **Will fail to install or launch on stock, un-jailbroken iOS** without being re-signed using AltStore, Sideloadly, or Xcode using a valid Apple Developer ID or free Apple ID personal certificate.

### 5.2 Real Device Testing Verification Facts
During Phase 1 and 2 verification, physical device execution was verified under the following exact conditions:
- **Target Device:** Physical iPhone XS running iOS 17.0.
- **Environment:** RootHide jailbreak with AppSync Unified.
- **Installation Mechanism:** `mcp-appinst` tool installing ad-hoc signed IPAs over USB.
- Note: TrollStore was **not** used during these automated test runs; AppSync Unified provided the signature bypass.

## 5. Terminal & Shell Issues

### 5.1 UnicodeEncodeError (`charmap codec can't encode character...`)
- **Cause**: Windows CMD or PowerShell using legacy code pages (e.g. CP1252, CP1256) unable to print Unicode symbols.
- **Solution**: NyxWin automatically reconfigures `sys.stdout` and `sys.stderr` to UTF-8 with error replacement. In PowerShell, you can also run:
  ```powershell
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  ```

### 5.2 `ExecutionPolicy: File install.ps1 cannot be loaded`
- **Cause**: Windows PowerShell execution policy restricts running unsigned local scripts.
- **Solution**: Launch using `install.bat` (which automatically passes `-ExecutionPolicy Bypass`), or run:
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\install.ps1
  ```
