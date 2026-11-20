# Data Storage & Migration

NyxWin separates its application files from user projects, configuration, build data and downloaded SDKs.

This separation keeps the development repository clean and reduces the risk of losing user data when updating or reinstalling the application.

This guide explains the storage layout, legacy directory detection and the migration workflow.

---

## 1. Why storage locations changed

Older NyxWin development layouts could store user data directly inside the application repository:

```text
NyxWin/
├── Projects/       # User projects
├── Cache/          # Compiler caches and temporary files
├── Output/         # Generated application packages
├── Backups/        # Project backups
└── sdk/            # Downloaded SDKs
```

This arrangement creates several problems:

- Application updates and source-code operations interact with user data.
- Large SDKs and build artifacts unnecessarily occupy the repository.
- Multiple installations can conflict over shared directories.
- Removing or replacing an application directory can put user projects at risk.

The current storage architecture keeps application files and mutable user data separate.

## 2. Current storage layout

The standard Windows layout uses the following locations:

| Category | Default location | Purpose |
|---|---|---|
| Application | Python package or managed application directory | NyxWin source and bundled resources |
| User configuration | `%APPDATA%\NyxWin` | User settings and configuration |
| Runtime data | `%LOCALAPPDATA%\NyxWin` | Build data, caches, backups and logs |
| User projects | `%USERPROFILE%\NyxProjects` | Default location for user projects |
| iOS SDKs | `%LOCALAPPDATA%\NyxWin\SDKs` | Downloaded iOS SDKs and related resources |

The runtime directory may contain:

```text
%LOCALAPPDATA%\NyxWin/
├── app/           # Managed application installation
├── bin/           # Global command launchers
├── SDKs/          # iOS SDKs and Swift target resources
├── Build/         # Temporary build workspaces
├── Cache/         # Compiler and module caches
├── Backups/       # Project recovery snapshots
├── Logs/          # Build logs and structured reports
└── Settings/      # Runtime settings and recent-project data
```

The exact contents depend on the installation method and NyxWin version.

Projects remain independent directories and can be stored outside the default projects folder.

A project may contain its own generated application package under `dist/`.

## 3. Environment overrides

NyxWin supports configurable storage locations through environment variables:

| Variable | Purpose |
|---|---|
| `NYXWIN_CONFIG_DIR` | Overrides the user configuration directory |
| `NYXWIN_DATA_DIR` | Overrides the runtime data directory |
| `NYXWIN_PROJECTS_DIR` | Overrides the default projects directory |
| `NYXWIN_SDK_DIR` | Overrides the SDK directory |

Use these overrides only when you intentionally want to change the default storage layout.

When changing an existing installation, verify the resolved paths using `nyx data paths` before running builds or migrations.

## 4. Legacy directory detection

When older repository-local directories are detected, NyxWin can report their presence so that users can inspect them.

Examples include:

- `Projects/`
- `Cache/`
- `Output/`
- `Backups/`
- `sdk/`

Detection does not mean that the directories are automatically migrated.

**Do not assume that an update, installation or migration command will automatically move or delete these directories.**

The user should inspect the existing data and decide when it is safe to migrate.

## 5. Inspect the current storage configuration

Run:

```powershell
nyx data paths
```

This displays the resolved application, configuration, runtime-data and project locations, along with any detected legacy directories.

Review the output carefully.

Pay particular attention to:

- The current project directory.
- The destination for user projects.
- The runtime data directory.
- The SDK directory.
- Any existing legacy directories.

Do not start a migration until you understand which locations contain your existing data.

## 6. Preview a migration

Use the dry-run option to inspect the proposed migration:

```powershell
nyx data migrate --dry-run
```

Review the information reported by NyxWin, including:

- Source and destination locations.
- Number of files and total data size.
- Destination conflicts.
- Available disk space.
- Any warnings or skipped items.

A dry run is an inspection step. It does not mean that the destination has been verified or that the migration has completed.

Resolve unexpected paths and destination conflicts before proceeding.

## 7. Apply the migration

After reviewing the migration plan:

```powershell
nyx data migrate --apply
```

Follow the command output and inspect the migration report.

The migration workflow is designed to avoid blindly overwriting existing destination files and to retain the original source data.

However, no migration process should be treated as a substitute for an independent backup.

**Before migrating important projects, make a separate backup that you can restore without relying on the migration operation itself.**

Do not interrupt the process unless necessary. If it fails, retain the output and inspect the resulting source and destination directories before attempting another migration.

## 8. Verify the result

After migration:

1. Run `nyx data paths` again.
2. Confirm that the expected destination directories are being used.
3. Open several migrated projects.
4. Inspect their project configuration and source files.
5. Verify any important resources and backups.
6. Compare the migration report with the original migration plan.
7. Perform a test build where appropriate.

Keep the original directories untouched until the destination has been independently checked.

Only after confirming that the migrated data is complete and usable should you consider archiving the old directories.

Never remove the only remaining copy of a project merely to clean up the repository.

## 9. Data relocation and project-schema migration are different

NyxWin has two distinct migration concerns.

**Storage migration**

Moves or copies existing user data from older repository-local locations into the standard Windows storage layout.

The relevant commands are:

```powershell
nyx data paths
nyx data migrate --dry-run
nyx data migrate --apply
```

**Project-schema migration**

Updates older project configuration formats to the canonical project schema supported by newer NyxWin versions.

Project-schema migration is concerned with configuration compatibility, not simply relocating directories.

Automatic migration and backup behavior depend on the project format and installed NyxWin implementation.

Do not manually edit schema-version fields just to suppress a migration warning.

## 10. Recovery and support

If a migration produces an unexpected result:

- Stop making further changes to the affected directories.
- Preserve the original project data.
- Retain the migration report and command output.
- Inspect the destination for partial or conflicting files.
- Restore from an independent backup if necessary.

When reporting an issue, provide the NyxWin version, the source and destination paths, the migration mode and the complete error output.

For additional help:

- [Installation & Setup](SETUP_GUIDE.md)
- [Troubleshooting](TROUBLESHOOTING.md)
- [Architecture](ARCHITECTURE.md)

## 11. Data preservation

An earlier copy was published under MIT and later removed. Anyone who already has that copy may keep using it under MIT. This repository's first release is v1.1.0 under PolyForm Noncommercial 1.0.0. Only 1.1.x is supported.

That license note does not alter, restrict, or modify ownership of user application source code, user project configurations (`Config/Project.plist`), user assets, or generated build deliverables. User data and source code remain the exclusive property of the user.
