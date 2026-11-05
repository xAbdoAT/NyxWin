# Third-Party Notices and Binary Provenance

This directory (`src/nyxwin/resources/tools/`) contains binary and helper components used by NyxWin for Mach-O linking, signing, and runtime compatibility.

---

## 1. ldid.exe (Link Identity Editor)

- **File:** `ldid.exe`
- **Version:** `Link Identity Editor v2.1.5-procursus7`
- **File Size:** 3,904,000 bytes
- **SHA-256:** `77A3F012E09619F8CFB5902EBA38A00B973DA5561AC592C530EFB68155F7E6F3`
- **License:** GNU General Public License v3.0 (GPLv3)
- **License File:** `LICENSE-GPLv3.txt`
- **Upstream Project:** Procursus Team (`ldid` fork maintained for modern Apple platforms)
- **Source Code Repository:** [https://github.com/ProcursusTeam/ldid](https://github.com/ProcursusTeam/ldid)
- **Upstream Authors:** Jay Freeman (saurik), Procursus Team contributors
- **Usage in NyxWin:** Used for ad-hoc Mach-O pseudo-signing (`-S`), CDHash extraction (`-h`), and entitlement verification (`-e`).
- **GPLv3 Source Code Availability:** Under GPLv3 Section 6, the corresponding source code for this binary is publicly available at the upstream repository linked above.

---

## 2. libclang_rt.ios.a (LLVM Compiler Runtime)

- **File:** `libclang_rt.ios.a`
- **Type:** Mach-O Universal/ARM64 static archive (`compiler-rt`)
- **File Size:** 416,776 bytes
- **SHA-256:** `6FBA0113F18ABAAE2E8FA41C224DECC253AE985CACFF52BBA3DA65A85475221A`
- **License:** Apache License v2.0 with LLVM Exception
- **License File:** `LICENSE-APACHE2-LLVM.txt`
- **Upstream Project:** LLVM Project (`compiler-rt` runtime library)
- **Source Code Repository:** [https://github.com/llvm/llvm-project/tree/main/compiler-rt](https://github.com/llvm/llvm-project/tree/main/compiler-rt)
- **Copyright:** Copyright (c) 2003-2026 LLVM Team / University of Illinois at Urbana-Champaign
- **Usage in NyxWin:** Static runtime library linked into iOS binaries to provide compiler builtins, atomic operations, and runtime symbols.

---

## 3. platform_check.c (Dynamic Darwin Platform Check Helper)

- **File:** `platform_check.c`
- **File Size:** 2,539 bytes
- **License:** MIT License (part of NyxWin)
- **Author:** Abdo AT (NyxWin Project)
- **Description:** Original implementation providing `__isPlatformVersionAtLeast` and `__isOSVersionAtLeast` through dyld's `_availability_version_check` API, enabling runtime compatibility across iOS versions without hard dependency on Xcode host SDK stubs.

---

## 4. patch_macho.py (Mach-O Load Command Patcher)

- **File:** `patch_macho.py`
- **File Size:** 5,691 bytes
- **License:** MIT License (part of NyxWin)
- **Author:** NyxWin Project Contributors
- **Description:** Pure Python Mach-O binary parser and patcher for adjusting `@rpath` load commands and runtime framework references.

