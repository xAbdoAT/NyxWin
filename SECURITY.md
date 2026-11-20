# Security Policy

Security vulnerabilities affecting NyxWin should be reported privately.

Please do not publish exploitable vulnerabilities, sensitive credentials or detailed attack instructions in public issues.

## Reporting a vulnerability

Report it through GitHub private vulnerability reporting:

[NyxWin Security](https://github.com/xAbdoAT/NyxWin/security)

Please include as much relevant information as possible:

- A description of the vulnerability.
- The affected NyxWin version or commit.
- The affected component or file.
- Steps to reproduce the issue.
- Potential security impact.
- Relevant logs or proof-of-concept material.
- Suggested mitigation, if available.

Do not include real passwords, access tokens, private signing keys or other unrelated sensitive information.

Reports will be reviewed for impact and reproducibility. Acknowledgment and remediation depend on the issue and the available resources.

Please allow an opportunity for investigation and coordinated disclosure before sharing details publicly.

## Supported versions

Security fixes are primarily intended for the latest published stable release.

| Version | Licensing Model | Security support |
|---|---|---|
| 1.1.x | PolyForm Noncommercial 1.0.0 | Supported |

An earlier copy was published under MIT and later removed. Anyone who already has that copy may keep using it under MIT. This repository's first release is v1.1.0 under PolyForm Noncommercial 1.0.0. Only 1.1.x is supported.

This table reflects the current published release line. It must be updated when a new stable version is published.

Development branches and unreleased commits may contain incomplete or unreviewed changes and should not be treated as equivalent to a stable release.

## Security considerations

NyxWin interacts with compilers, linkers, external executables, application archives, project files and user-controlled paths.

Security-sensitive areas include:

### Filesystem safety

Path validation helps prevent operations such as cache cleanup and project restoration from escaping their intended directories.

### Archive extraction

Backup restoration validates archive entry paths to reduce the risk of archive path traversal, commonly known as Zip Slip.

### External process execution

Build tools are executed using structured process arguments rather than constructing shell commands from arbitrary user input.

### Application resources

Image processing and project resource handling include validation intended to reduce unsafe input handling.

### Backups and migration

Operations involving project data require safeguards to reduce accidental overwrites and preserve recoverability.

These defenses reduce specific classes of risk. They are not a guarantee that every component or dependency is free of vulnerabilities.

## Third-party components

NyxWin includes and depends on third-party tools, libraries, SDK resources and other external components.

Each component may have its own security advisories, update requirements and licensing obligations.

Security reports involving bundled or third-party components should identify the affected component and version whenever possible.

See the repository's third-party notices for applicable licensing information.

## Scope

Security reports are welcome for vulnerabilities that materially affect NyxWin users or the integrity of their systems, including:

- Arbitrary file access or destructive path handling.
- Unsafe archive extraction.
- Command or process execution vulnerabilities.
- Exposure of credentials or sensitive data.
- Dependency or bundled-tool vulnerabilities.
- Integrity failures affecting downloaded or packaged components.

General usage problems, build failures and feature requests should normally be reported through the project's issue tracker instead.

## Responsible disclosure

Please avoid exploiting vulnerabilities against systems you do not own or have permission to test.

Do not access, modify or disclose another person's data.

The goal of coordinated disclosure is to give maintainers a reasonable opportunity to understand, reproduce and address a vulnerability before technical details become public.

---

**Project:** [NyxWin](https://github.com/xAbdoAT/NyxWin)  
**Security contact:** [160148781+xAbdoAT@users.noreply.github.com](mailto:160148781+xAbdoAT@users.noreply.github.com)