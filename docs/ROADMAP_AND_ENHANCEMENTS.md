# Roadmap & Development

This document describes the development direction of NyxWin, its completed engineering milestones and the work planned for future releases.

NyxWin is a Windows-based iOS cross-compilation project. Its development priorities are build reliability, reproducibility, project compatibility and a maintainable developer experience.

The roadmap is organized into engineering stages. A planned feature is not considered implemented until it has been developed, tested and accepted.

---

## 1. Project direction

The long-term goal is to provide a reliable native iOS build workflow on Windows without requiring a macOS host, Xcode or WSL.

The project focuses on:

- Swift and SwiftUI application builds.
- UIKit application builds.
- C, Objective-C and C++ compilation.
- Apple platform linking and Mach-O processing.
- Application packaging and signing workflows.
- Project configuration and migration.
- Reproducible builds and useful diagnostics.
- A maintainable Windows-native development environment.

NyxWin is the name of the v1.1.0 public release.

## 2. Completed engineering milestones

The following milestones have been completed in the development working tree and accepted through their respective engineering reviews.

### Phase 4 — Canonical Project Schema v2.0

Established a standardized project configuration model.

Key work:

- Canonical project configuration.
- Structured build settings and target information.
- Project validation and serialization.
- Migration support for older project configurations.
- Improved support for Apple-style project settings.
- Objective-C bridging-header discovery for mixed Swift and C-family projects.

### Stage 0 — Build and data safety

Focused on making the core application safer and more predictable.

Key work:

- Canonical path resolution.
- Safer workspace handling.
- Backup and restoration protections.
- Improved temporary-file cleanup.
- Project export and migration safeguards.
- Additional validation for application resources and icons.

### Stage 1 — Observability, reproducibility and cancellation

Improved the build lifecycle and operational reliability.

Key work:

- Persistent build logs.
- Structured JSON build reports.
- Build-stage timing and diagnostics.
- Deterministic IPA packaging.
- Windows-native subprocess management.
- Graceful build cancellation.
- Process cleanup and recovery diagnostics.
- Interactive dashboard cancellation.
- Structured report viewing.
- Documentation and regression coverage.

The six-stage build lifecycle is:

```text
SCAN → COMPILE → LINK → PATCH → SIGN → PACKAGE
```

### Verification evidence

The accepted Stage 1 evidence recorded:

| Verification | Result |
|---|---|
| Full unit suite | 287 passed |
| Stage 1 focused suite | 73 passed |
| Integration suite | 18 passed, 4 skipped |
| Individually executed live SDK tests | 4 passed |
| SwiftUI live build | Successful |
| UIKit live build | Successful |
| Deterministic packaging verification | Successful |
| Windows subprocess cancellation tests | Successful |
| Manual physical-device validation | PASS (USER-REPORTED) |

Manual device validation was reported on two iPhones. This evidence should not be interpreted as universal device compatibility or as automated MCP verification.

The automated MCP hardware verification channel remained blocked.

These results describe the accepted development evidence for the work included in v1.1.0.

## 3. Current release — v1.1.0

NyxWin v1.1.0 is published. Install it with the PowerShell one-liner in the README, then run `nyx`.

The public repository is that release. It is not a pip package. Third-party components are documented separately and are not fully cleared.

## 4. Planned engineering stages

The following stages describe the approved development direction after release preparation.

### Stage 2 — Dependency tracking and build caching

Improve the build system's understanding of source and dependency relationships.

Planned areas:

- Track source-file dependencies.
- Track relevant compiler and linker inputs.
- Track SDK and configuration changes.
- Introduce reliable cache invalidation.
- Reuse compilation outputs when inputs remain unchanged.
- Improve cache diagnostics and consistency.

The priority is correctness. A cache must never reuse an output that is no longer valid for the current build inputs.

### Stage 3 — Incremental build graph

Build on dependency tracking to introduce a structured incremental build system.

Planned areas:

- Represent compilation and linking work as a dependency graph.
- Identify which outputs must be rebuilt after a source or configuration change.
- Reuse unaffected build outputs.
- Improve scheduling and build parallelism.
- Provide visibility into skipped and repeated work.

The existing build lifecycle must remain reliable while the internal build orchestration evolves.

### Stage 4 — Static and dynamic framework support

Expand support for reusable libraries and framework-based projects.

Implementation order:

1. Static libraries.
2. XCFramework inspection and platform/architecture selection.
3. Static framework integration.
4. Dynamic frameworks and dynamic libraries.

The implementation must account for platform compatibility, architecture selection, linking behavior, packaging and runtime requirements.

### Stage 5 — Resources and localization

Improve the handling of application resources.

Planned areas:

- Structured resource discovery.
- Resource-directory preservation.
- Asset catalog support.
- Localization resources.
- Resource validation.
- More predictable inclusion of application assets.

The goal is to move beyond basic resource copying and toward a more complete application packaging workflow.

### Stage 6 — Swift Package Manager feasibility

Investigate whether Swift Package Manager can be integrated reliably into the Windows-hosted cross-compilation workflow.

The first activity is a feasibility study, not immediate implementation.

Priority areas:

- Dependency resolution.
- Local package support.
- Cross-compilation constraints.
- SDK and target integration.
- Build output handling.
- Reproducibility and caching.

Local Swift packages should be investigated before introducing remote dependency management.

This work must preserve the Windows-native architecture. WSL is not a required solution.

### Stage 7 — SourceKit-LSP and IDE integration

Improve the development experience beyond the terminal interface.

Planned areas:

- SourceKit-LSP feasibility and integration.
- Swift editor support.
- Correct target and SDK configuration for language services.
- C and Objective-C IntelliSense configuration.
- Project-aware editor settings.
- Better diagnostics for editor and compiler configuration differences.

IDE integration must complement the actual build configuration rather than generate misleading editor settings.

## 5. Features not currently promised

Some ideas have been discussed for possible future investigation, including:

- USB device deployment.
- Live device log streaming.
- Integrated debugging.
- Additional asset compilation capabilities.
- Additional package formats.

These are not commitments or implemented features unless they are formally added to the roadmap and accepted as development work.

In particular, a future device-deployment integration would require separate research into device pairing, operating-system compatibility, signing requirements and installation restrictions.

No one-click TrollStore installation capability is currently promised.

## 6. Roadmap principles

Future implementation should follow these principles:

**Reliability first**

A feature is not complete merely because its primary workflow works once. Error handling, cleanup and regression coverage are part of implementation.

**Preserve compatibility**

Project configurations and existing user data must remain protected during architectural changes.

**No unnecessary platform dependency**

Windows remains the target development environment. WSL or a macOS host must not become hidden requirements.

**Keep boundaries clear**

Compiler execution, project configuration, packaging, installation and IDE integration should remain distinct responsibilities.

**Verify before declaring completion**

Milestones require tests and documented evidence. Planned work must not be presented as an existing capability.

---

## 7. Project status

NyxWin remains under active development.

The completed engineering milestones describe the validated development implementation. Release integration, installation hardening and publication are separate activities.

The next objective is a dependable v1.1.0 release baseline before beginning Stage 2.