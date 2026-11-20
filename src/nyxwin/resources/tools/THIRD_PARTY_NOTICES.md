# Third-Party Notices & Component Provenance

This document identifies third-party software and supporting components distributed with NyxWin.

Components included in the application may have their own copyright notices, license terms and redistribution requirements. The license governing NyxWin itself does not automatically replace those component-specific terms.

This inventory must be kept synchronized with the actual files included in each release.

---

## 1. ldid — Link Identity Editor

**Bundled file:** `ldid.exe`

**Upstream project:** [ProcursusTeam/ldid](https://github.com/ProcursusTeam/ldid)

**Reported upstream version:** `2.1.5-procursus7`

**Upstream release:** [v2.1.5-procursus7](https://github.com/ProcursusTeam/ldid/tree/v2.1.5-procursus7)

**License:** GNU Affero General Public License v3 (AGPL-3.0 family).

### License and provenance

The ProcursusTeam source repository identifies `ldid` as AGPL-licensed. The `ldid.cpp` source at the referenced release tag contains an `AGPL-3.0-only` SPDX identifier.

The upstream release package metadata identifies the version as `AGPL-3.0-or-later`.

These declarations must be reconciled against the exact source snapshot used to produce the Windows executable before its distribution terms are finalized.

The existing NyxWin notice previously identified this component as GPLv3. That classification should not be relied upon without further verification.

### Use in NyxWin

NyxWin uses `ldid.exe` for Mach-O ad-hoc signing and related signature and entitlement operations.

An ad-hoc signature is not an Apple-issued signing identity or a standard Apple provisioning profile.

### Source and license information

- [ProcursusTeam/ldid source repository](https://github.com/ProcursusTeam/ldid)
- [Version 2.1.5-procursus7 source](https://github.com/ProcursusTeam/ldid/tree/v2.1.5-procursus7)
- [Upstream COPYING file](https://github.com/ProcursusTeam/ldid/blob/v2.1.5-procursus7/COPYING)
- [GNU Affero General Public License v3](https://www.gnu.org/licenses/agpl-3.0.html)

When distributing this executable, preserve its applicable copyright and license notices and satisfy the corresponding-source requirements applicable to the exact distributed binary.

If the Windows executable contains local modifications or is built from a different source revision, the corresponding source must reflect those modifications.

**Release verification requirement:** Confirm the executable's actual source revision, build provenance and license metadata. Verify that the corresponding AGPL license text and source are made available as required.

---

## 2. LLVM Compiler Runtime

**Bundled file:** `libclang_rt.ios.a`

**Upstream project:** [LLVM Project](https://github.com/llvm/llvm-project)

**Upstream component:** [compiler-rt](https://github.com/llvm/llvm-project/tree/main/compiler-rt)

**Declared license:** Apache License 2.0 with LLVM Exceptions.

**License notice:** `LICENSE-APACHE2-LLVM.txt`

### Description

The LLVM compiler runtime provides runtime support required by compiled programs.

NyxWin includes a runtime archive used by its iOS cross-compilation workflow to resolve applicable compiler runtime symbols.

The LLVM Project's licensing framework identifies Apache License 2.0 with LLVM Exceptions as its primary license framework. The exact provenance and applicable notices for the bundled archive must still be checked against the source revision from which it was obtained.

### Attribution and license information

- [LLVM Project](https://llvm.org/)
- [LLVM compiler-rt](https://github.com/llvm/llvm-project/tree/main/compiler-rt)
- [LLVM License](https://github.com/llvm/llvm-project/blob/main/llvm/LICENSE.TXT)
- [LLVM Developer Policy](https://www.llvm.org/docs/DeveloperPolicy.html)

Retain the applicable copyright and license notices accompanying the component.

**Release verification requirement:** Verify the archive's source revision, target architecture, integrity and applicable license notices before redistributing it.

---

## 3. Platform Availability Helper

**Bundled file:** `platform_check.c`

**Role:** Platform availability support for applicable iOS build configurations.

The helper provides availability-checking symbols used by the build workflow.

**Previously declared license:** MIT.

**Provenance status:** Requires final source-origin verification.

### Attribution and licensing

The current project documentation identifies this helper as a NyxWin-maintained component. However, its original source history, authorship and any third-party material used during development must be verified before making a definitive independent-authorship or MIT licensing claim.

Any original copyright notices, license headers or third-party attribution must be preserved.

This notice does not override a license or attribution requirement that may apply to portions of the source.

**Release verification requirement:** Inspect the complete source file and its development history, identify any borrowed or adapted material, and establish the applicable license before release distribution.

---

## 4. Mach-O Processing Helper

**Bundled file:** `patch_macho.py`

**Role:** Mach-O binary inspection and processing during the build pipeline.

The helper performs the binary-processing operations required by the current NyxWin build workflow.

**Previously declared license:** MIT.

**Provenance status:** Requires final source-origin verification.

### Attribution and licensing

The current project documentation identifies this helper as a NyxWin-maintained component.

Its original source, implementation history and any material adapted from third-party projects must be reviewed before claiming that the entire file is independently authored and licensed under MIT.

Existing copyright notices and third-party license requirements must be preserved.

**Release verification requirement:** Complete source provenance review and confirm that the license and attribution statements match the actual contents of the distributed file.

---

## 5. License and attribution principles

NyxWin includes components with different origins and licensing terms.

The following principles apply:

1. Each component retains its applicable license and copyright notices.
2. Component-specific license obligations must be respected when distributing application packages.
3. Modified third-party components must not be described as entirely original implementations.
4. Required corresponding-source material must be made available where the applicable license requires it.
5. Third-party copyright notices must not be removed merely to make documentation appear consistent.
6. The NyxWin project license must not be assumed to override the terms of separately distributed components.

The presence of a component in the same application distribution does not, by itself, establish that every part of NyxWin has the same license. The legal treatment of combined or modified works depends on the actual relationship between their code and distribution.

For significant licensing or redistribution questions, obtain appropriate legal review.

---

## 6. Binary integrity and release records

File sizes and SHA-256 hashes describe individual binary artifacts, not their licenses.

They should be recorded from the exact files selected for each release.

For example, PowerShell can calculate the relevant metadata:

```powershell
Get-Item .\src\nyxwin\resources\tools\ldid.exe |
    Select-Object Name, Length

Get-FileHash .\src\nyxwin\resources\tools\ldid.exe -Algorithm SHA256
```

Repeat the procedure for each bundled native component.

Record the resulting hashes in the release checksum manifest rather than relying on manually maintained values in this document.

When comparing a packaged file with its original disk copy, distinguish between the uncompressed file size and the compressed archive-entry size.

A SHA-256 comparison must use the actual uncompressed bytes of the component.

---

## 7. Distribution checklist

Before publishing a NyxWin release, verify the following:

- [ ] Every bundled executable and resource has an identified origin.
- [ ] The `ldid.exe` binary has a verified version and corresponding source revision.
- [ ] The applicable AGPL license and corresponding-source requirements for `ldid` are satisfied.
- [ ] LLVM runtime provenance and license notices are verified.
- [ ] `platform_check.c` authorship, provenance and license are established.
- [ ] `patch_macho.py` authorship, provenance and license are established.
- [ ] Applicable copyright notices are retained.
- [ ] Required license files are included in the distribution.
- [ ] The final wheel contains the intended resources and notices.
- [ ] Release checksums match the exact distributed artifacts.

This inventory should be reviewed whenever a bundled component is replaced, updated, patched or redistributed.

---

## 8. Project independence and third-party acknowledgments

NyxWin is an independent project. Its development was influenced in part by [Nyxian](https://github.com/emexlab/Nyxian).

That acknowledgment does not imply that NyxWin is affiliated with or endorsed by the Nyxian developers.

Any source code, adapted implementations, retained notices or other material originating from Nyxian must be identified and handled according to its actual provenance and applicable license.

General inspiration and independently implemented ideas should not be confused with copied or derivative source code.

---

**Document scope:** Bundled tools and supporting components under `src/nyxwin/resources/tools/`.

**Maintenance:** Update this document whenever the distributed component inventory or its verified licensing information changes.