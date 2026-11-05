# Changelog

All notable changes to NyxWin are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-11-02

### Added
- **Swift-First Template Architecture:** First-class support for modern **SwiftUI** and **UIKit (Swift)** starter applications.
- **Dynamic Build Workspace:** Dynamic build directory isolation under `%LOCALAPPDATA%\NyxWin\Build\<Project>`.
- **Comprehensive Terminal UX:** Full arrow-key driven interactive dashboard with project switcher, settings menu, and real-time build progress cards.
- **Detailed Build Transcripts:** Persistent structured build transcripts (`.log`) recording compiler invocations, object sizes, linking headers, and Mach-O load command analysis.
- **Deep Type-Sensitive Plist Comparison:** Strict type-checked validation (`plist_deep_equal`) ensuring extracted binary entitlements match `Config/Entitlements.plist` across keys, values, data types, arrays, and nested dictionaries.
- **Pipeline Halting on Entitlement Mismatch:** Build pipeline immediately halts at Stage 5 if an entitlement mismatch is detected, preventing invalid IPA packaging.
- **Standardized Seven-Point Signature Audit Matrix:** Clear separation of structural presence, CDHash extraction, entitlement verification, CodeDirectory integrity, signer identity, trust chain, and provisioning authorization.
- **Automated Web Bootstrap Installer & Self-Updater (`nyx update`):** One-line PowerShell installer (`install.ps1`) installing to `%LOCALAPPDATA%\NyxWin\app` with global CLI shims in `%LOCALAPPDATA%\NyxWin\bin`, plus in-place self-updating from GitHub Releases or the `main` branch.
- **Native Project Schema v1.0:** Pure native `Config/Project.plist` schema with third-party license notices (`THIRD_PARTY_NOTICES.md`).
- **Safety Defenses:** Path traversal protection on caches and backups, zip slip protection, and safe Pillow-based icon resizing.

### Changed
- Default project entitlements now generate clean empty dictionaries (`<dict/>`) instead of hardcoding `get-task-allow`.
- Streamlined project generation by removing redundant artifact-category selection screen.
- Simplified signing profile selection: One-click build with automatic project configuration resolution.

### Removed
- Deprecated legacy starter templates: C Command-Line Tool, C++ Command-Line Tool, Objective-C Command-Line Tool, Swift Command-Line Tool, C Kernel Extension, and UIKit Objective-C template. (Existing compatible projects continue to build seamlessly).

