# Contributing

Thank you for your interest in NyxWin.

NyxWin is an independent Windows-hosted toolchain for building native iOS applications. Contributions that improve reliability, maintainability, documentation and developer experience are welcome.

The public release is NyxWin v1.1.0. Later releases may add features. The public name of this release is NyxWin.

## Development environment

NyxWin development currently targets 64-bit Windows.

The development environment may require:

- Windows 10 or Windows 11.
- Python 3.10 or a compatible newer version.
- LLVM Clang and LLD.
- Swift for Windows for Swift-related development and builds.
- A compatible iOS SDK and Swift target resources.
- The dependencies declared by the project.

See [Windows Dependencies](docs/WINDOWS_DEPENDENCIES.md) for toolchain information.

## Setting up a development checkout

Clone the repository:

```powershell
git clone https://github.com/xAbdoAT/NyxWin.git
cd NyxWin
```

Install NyxWin the same way an end user does. From the checkout, run `install.bat` or `install.ps1`. That registers the `nyx` command. Do not pip-install this repository.

Before working on the code, verify the environment:

```powershell
nyx --version
nyx doctor
```

The public repository is the v1.1.0 release. Do not pip-install it.

## Testing

The public repository does not include the local test suite or the device-test tools. Those stay on the maintainer's machine.

## Development principles

### Preserve the architecture

Keep responsibilities clearly separated between:

- Project configuration and migration.
- Compilation and linking.
- Mach-O processing and signing.
- Application packaging.
- Process management and cancellation.
- Persistent build diagnostics.
- User interface and application services.

Avoid introducing unnecessary coupling between these components.

### Maintain Windows compatibility

Windows is the intended host platform.

Do not introduce a required dependency on macOS, Xcode or WSL.

### Preserve project and user data

Changes involving project configuration, backups, migration, path handling or cleanup require particular care.

Do not introduce destructive defaults or overwrite existing user data without explicit safeguards.

### Protect the signing boundary

The code-signing implementation is a protected component.

Do not modify `src/nyxwin/build/signer.py` or its behavior without explicit maintainer authorization.

Changes affecting entitlement validation must preserve the required failure behavior when extracted and configured entitlements do not match.

### Keep documentation accurate

Documentation should describe implemented and tested functionality.

Do not document planned features as completed. Keep examples, paths, CLI options and keybindings consistent with the actual implementation.

## Code and test expectations

- Follow the existing Python conventions and formatting used by the project.
- Prefer clear names and focused functions.
- Add regression tests for bug fixes and behavior changes.
- Avoid introducing unnecessary dependencies.
- Keep error handling explicit.
- Preserve existing public interfaces unless a change is intentional and documented.
- Check generated files and temporary artifacts before including them in a change.

## Submitting changes

Before proposing a contribution:

1. Explain the problem or motivation.
2. Describe the intended change.
3. Identify affected components.
4. Include relevant tests and verification results.
5. Document any behavior or compatibility changes.
6. Identify any new dependencies and their licenses.

Submit changes through a descriptive pull request or another contribution method agreed upon by the maintainers.

Do not include unrelated formatting changes, generated binaries, private credentials, local SDK archives or build artifacts.

## Contributor licensing and contribution policy

NyxWin operates under a source-available, non-commercial licensing model designed to keep the tool freely accessible to students, hobbyists, and researchers while preserving single-entity commercial licensing authority for the project owner.

### Current contribution status

* **Issues & Discussions Welcome:** Bug reports, architectural discussions, and improvement suggestions are welcome via GitHub Issues. Prospective contributors are encouraged to discuss proposed features or design changes before investing time in implementation.
* **Code Contributions on Hold Pending Legal Review:** External code contributions and pull requests cannot be accepted or merged into the official repository at this time. Before code contributions can be merged, the appropriate contributor agreement must complete qualified legal review, and a formal signing and acceptance procedure must be established.
* **Unsigned Drafts Transfer No Rights:** Unsigned draft agreements transfer no rights, grant no authorizations, and cannot serve as legal authorization for merging code.
* **Community Forks & Experimentation:** This policy in no way restricts community members from creating forks, experimenting, adapting the software, or sharing independent modified versions for permitted non-commercial purposes under the terms of the PolyForm Noncommercial License 1.0.0.

### Contributor agreement architecture (drafts under legal review)

When the formal contribution process is ready, NyxWin plans to utilize contributor agreements. Two draft frameworks are maintained in the repository for public evaluation and qualified legal review:

1. **Copyright Assignment Agreement (CAA) with Non-Commercial License-Back (Preferred):**
   - **Mechanism:** The contributor assigns transferable copyright in their contribution to the Project Owner, unifying copyright title and commercial licensing authority under a single entity.
   - **Contributor Rights:** The Project Owner grants back to the contributor a perpetual, worldwide, royalty-free license to use, modify, and distribute their own contribution for personal, research, educational, and other non-commercial purposes.
   - **Authorship Credit:** Contributor attribution is preserved in Git commit history and documentation.
   - **Draft document:** [CAA.md](CAA.md) *(DRAFT — SUBJECT TO QUALIFIED LEGAL REVIEW — NOT YET APPROVED FOR EXECUTION)*

2. **Contributor License Agreement (CLA) (Fallback):**
   - **Mechanism:** The contributor retains copyright ownership and grants the Project Owner a broad, perpetual, royalty-free license to use, sublicense, and commercially exploit the contribution.
   - **Limitation:** A CLA does **not** transfer copyright ownership and does **not** make the Project Owner the sole copyright owner. It leaves copyright title fragmented across individual contributors.
   - **Draft document:** [CLA.md](CLA.md) *(DRAFT — SUBJECT TO QUALIFIED LEGAL REVIEW — NOT YET APPROVED FOR EXECUTION)*

The CAA and CLA represent fundamentally different legal instruments and are not equivalent. External contributors must not attempt to sign or submit either agreement until formal legal review is complete and official execution instructions are published.

### Third-party material

Preserve applicable copyright notices and license information for any bundled component.

Do not copy, adapt or repackage third-party code without checking its license and applicable obligations.

NyxWin is inspired in part by [Nyxian](https://github.com/emexlab/Nyxian). It is a separate project, and contributions must respect the licensing requirements of any source material used.

See the repository's `LICENSE` and third-party notices (`THIRD_PARTY_NOTICES.md`) for additional information.

## Questions and discussions

For questions about implementation, proposed features or development direction, use the project's GitHub repository:

[NyxWin on GitHub](https://github.com/xAbdoAT/NyxWin)

Contributions should prioritize correctness, maintainability and user safety over adding features for their own sake.
