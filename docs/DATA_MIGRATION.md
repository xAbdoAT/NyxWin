# NyxWin Safe Data Migration Guide

## 1. Background and Motivation

In earlier versions of NyxWin and prototype installations, all project files, compiler object caches, generated IPA archives, project backups, and downloaded SDKs were placed directly inside the source code repository directory:

```
NyxWin (Repository Root)/
├── Projects/         <-- User Projects (Mutable)
├── Cache/            <-- Build Artifacts & Objects (Mutable)
├── Output/           <-- Packaged .ipa Files (Mutable)
├── Backups/          <-- Zip Snapshots (Mutable)
└── sdk/              <-- Multi-gigabyte iOS SDKs (Mutable)
```

This legacy layout creates several risks:
1. **Source Code Pollution**: Git status displays hundreds of untracked build artifacts and gigabytes of SDK headers.
2. **Upgrade Friction**: Updating or reinstalling the Python package risks overwriting or losing user project files.
3. **Multi-User Conflicts**: Hardcoded repository paths prevent installing NyxWin into shared or read-only directories.

---

## 2. The Modern Storage Architecture

NyxWin 1.0.0 separates immutable application source code from mutable user data:

| Asset Category | Standard Modern Location | Environment Override |
|---|---|---|
| **Application Package** | Python `site-packages` or git clone | N/A |
| **User Configuration** | `%APPDATA%\NyxWin` (`workspaces.json`, user settings) | `NYXWIN_CONFIG_DIR` |
| **Runtime Data & Caches** | `%LOCALAPPDATA%\NyxWin` (`Cache/`, `Output/`, `Backups/`, `sdk/`) | `NYXWIN_DATA_DIR` |
| **User Projects** | `%USERPROFILE%\NyxProjects` | `NYXWIN_PROJECTS_DIR` |
| **iOS SDKs** | `%LOCALAPPDATA%\NyxWin\sdk` | `NYXWIN_SDK_DIR` |

---

## 3. Backward Compatibility & Automatic Detection

NyxWin **never** automatically moves, relocates, or deletes user files.

When `nyx` or `nyx doctor` is invoked:
1. The path resolution engine inspects the current repository root and active workspace.
2. If legacy directories (`Projects/`, `Cache/`, `Output/`, `Backups/`, `sdk/`) are detected, NyxWin logs a non-intrusive notification:
   ```
   [NOTE] Legacy directories detected in repository root: Projects, Cache, Output, Backups, sdk
          Inspect with 'nyx data paths' or migrate safely with 'nyx data migrate --dry-run'
   ```
3. Existing projects remain fully functional in their current locations until the user explicitly decides to migrate.

---

## 4. The 3-Step Safe Migration Workflow

The migration service guarantees **Zero Data Loss**:
- Original source files are **never deleted**.
- Conflicting files at the destination are skipped rather than overwritten.
- File integrity is verified after copying.
- A full audit report is written to `%APPDATA%\NyxWin\migration_report.json`.

### Step 1: Inspect Active Paths
Run `nyx data paths` to view active locations and detected legacy assets:

```powershell
nyx data paths
```

Example Output:
```
--- NyxWin Active & Configured Paths ---
  Package Root:         C:\Users\<User>\Development\NyxWin
  User Config:          C:\Users\<User>\AppData\Roaming\NyxWin
  Runtime Data:         C:\Users\<User>\AppData\Local\NyxWin
  Default Projects:     C:\Users\<User>\NyxProjects

  [!] Legacy repository directories detected:
      • Projects   -> C:\Users\<User>\Development\NyxWin\Projects
      • Cache      -> C:\Users\<User>\Development\NyxWin\Cache
      • Output     -> C:\Users\<User>\Development\NyxWin\Output
      • Backups    -> C:\Users\<User>\Development\NyxWin\Backups
      • sdk        -> C:\Users\<User>\Development\NyxWin\sdk
```

---

### Step 2: Preview the Migration Plan (Dry-Run)
Run `nyx data migrate --dry-run` to calculate file counts, total size, available disk space, and check for any destination collisions:

```powershell
nyx data migrate --dry-run
```

Example Output:
```
--- NyxWin Safe Data Migration Plan ---
  Source Root:          C:\Users\<User>\Development\NyxWin
  Target Projects:      C:\Users\<User>\NyxProjects
  Target Data:          C:\Users\<User>\AppData\Local\NyxWin
  Total Files:          21769
  Total Data:           686.34 MB
  Destination Conflicts:0 (conflicts will NOT be overwritten)
  Available Space:      175500.55 MB

  [DRY-RUN] No files were copied.
  Run with --apply to perform verified file copy:
    nyx data migrate --apply
```

---

### Step 3: Execute Verified Migration (Apply)
When ready, execute the migration using `--apply`:

```powershell
nyx data migrate --apply
```

Execution Behavior:
1. Target directories are created with appropriate permissions.
2. Files are copied preserving timestamps and metadata (`shutil.copy2`).
3. Each copied file is verified against its source size.
4. Any conflicting file at destination is skipped to prevent accidental overwrites.
5. The detailed audit log is saved to `%APPDATA%\NyxWin\migration_report.json`.
6. Original directories in the repository root are left completely intact.

---

## 5. Post-Migration Verification & Rollback

After migration completes:
1. Verify projects in `%USERPROFILE%\NyxProjects` by running:
   ```powershell
   nyx -w %USERPROFILE%\NyxProjects doctor
   ```
2. Once verified, you may safely archive or remove the legacy directories from your repository root if you wish to clean your git working tree.
3. If at any time you wish to revert, your original legacy files remain untouched.
