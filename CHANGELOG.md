# Changelog

Significant changes to NyxWin are documented here.

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-11-20

Published first release of this repository.

An earlier copy was published under MIT and later removed. Anyone who already has that copy may keep using it under MIT. This repository's first release is v1.1.0 under PolyForm Noncommercial 1.0.0. Only 1.1.x is supported.

### Changed
- **Contributor Governance:** Established Contributor License Agreement (CLA) and Copyright Assignment Agreement (CAA) requirements for community contributions to maintain clear licensing title and sole commercial licensing authority.
- **Documentation Reconciliation:** Completely updated project documentation suite to reflect the new licensing model, community non-commercial permissions, commercial licensing process, and third-party license boundaries.

### Added (Stage 1 Improvements)
- **Persistent Build Logs:** Automatic creation of per-project, per-build persistent log files under `%LOCALAPPDATA%\NyxWin\Logs\builds\<project>\build_<id>.log` capturing complete compiler/linker command lines, stdout/stderr, diagnostics, and build outcomes.
- **Structured JSON Build Reports:** Generation of atomic, schema-versioned `build_report.json` files for every build (success, failure, or cancellation) recording tool metadata, stage durations, process exit codes, and artifact hashes.
- **Deterministic IPA Packaging:** Normalized archive timestamps (1980-01-01 00:00:00 / MS-DOS epoch), fixed Unix file permissions (0o100644 for files, 0o40755 for directories), stable directory ordering, and consistent compression (DEFLATE level 9) ensuring identical SHA-256 IPA packages from identical signed input bundles.
- **Graceful Cancellation & Windows Process-Tree Cleanup:** Cooperative cancellation across build pipeline stages, cancellation token propagation, and targeted Windows process-tree termination using `taskkill /PID <pid> /T /F` ensuring child compiler/linker processes are safely reaped upon cancellation without leaving orphaned workers.
