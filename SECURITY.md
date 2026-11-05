# Security Policy

## Reporting Security Issues

If you discover a security vulnerability or sensitive credential disclosure within NyxWin, please report it privately rather than opening a public issue.

**Contact:**
- Email: [abdoat@users.noreply.github.com](mailto:abdoat@users.noreply.github.com)
- GitHub Security Advisories: Submit a report via GitHub's private vulnerability reporting feature on the repository.

Please include:
- A description of the issue and potential impact.
- Steps to reproduce or proof-of-concept scripts.
- Any suggested fixes or mitigations.

We will acknowledge receipt within 48 hours and work with you on a coordinated disclosure timeline.

## Supported Versions

Only the latest release on the `main` branch is actively supported with security updates.

| Version | Supported |
| :--- | :--- |
| 1.0.x | Yes |
| < 1.0.0 | No |

## Scope & Defenses

NyxWin includes defensive mechanisms against common path and packaging vulnerabilities:
- **Path Traversal Defense:** `is_safe_subpath()` guards cache, backup, and restore routines to prevent directory escape.
- **Zip Slip Protection:** Backup restore operations validate archive member destinations before extraction.
- **Command Injection Prevention:** Uses typed subprocess argument arrays; icon processing uses native Pillow routines instead of external shell scripts.

