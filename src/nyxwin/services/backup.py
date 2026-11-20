import os
import re
import shutil
import zipfile
import datetime
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from nyxwin.core.models import Color, log_info, log_success, log_error, log_warning
from nyxwin.core.toolchain import Toolchain
from nyxwin.config.paths import RUNTIME_DATA_DIR, get_project_backups_dir, is_safe_subpath
from nyxwin.core.project import get_or_create_project_id, get_safe_project_dirname

NYXWIN_BACKUP_MARKER = b"NYXWIN_BACKUP_V1"

# Protected VCS directories that must NEVER be archived, modified, or deleted during backup/restore
PROTECTED_VCS_DIRS = {
    ".git",
    ".hg",
    ".svn",
}

# Protected user/IDE directories that must survive project restoration even when absent from backup
PROTECTED_USER_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".vscode",
    ".idea",
}

# Universal internal directories to exclude from backup archives
EXCLUDED_INTERNAL_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".git",
    ".hg",
    ".svn",
    ".cache",
    ".mypy_cache",
    ".tox",
}

# System files to exclude from backup archives
EXCLUDED_SYSTEM_FILES = {
    ".ds_store",
    "thumbs.db",
    "desktop.ini",
}

# System bytecode file extensions to exclude
EXCLUDED_SYSTEM_EXTS = {
    ".pyc",
    ".pyo",
}

def resolve_backups_dir(toolchain: Toolchain, proj_dir: Path) -> Path:
    r"""
    Resolves the authoritative external backup storage directory.
    All backups are stored in %LOCALAPPDATA%\NyxWin\Backups\<safe_name>-<project_id>\.
    """
    proj_id = get_or_create_project_id(proj_dir)
    b_dir = get_project_backups_dir(proj_dir.name, proj_id)
    os.makedirs(b_dir, exist_ok=True)
    return b_dir

def is_nyxwin_backup_archive(zip_path: Path, project_name: Optional[str] = None) -> bool:
    """
    Determines whether a ZIP file is a genuine NyxWin-generated project backup archive
    by verifying the authoritative unique ZIP comment marker (NYXWIN_BACKUP_V1).

    For older unmarked archives, ambiguous user ZIP files are preserved rather than excluded
    to prioritize data safety and prevent accidental deletion of user backups or project snapshots.
    """
    if not zip_path.is_file() or zip_path.suffix.lower() != ".zip":
        return False

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            return zf.comment == NYXWIN_BACKUP_MARKER
    except Exception:
        return False

def should_exclude_from_backup(
    file_path: Path,
    proj_dir: Path,
    backup_file: Path,
    actual_name: str
) -> bool:
    """
    Content-aware, metadata-verified exclusion decider for project backups.

    Exclusion Policy:
      - Never excludes arbitrary directories solely by name (preserves Build, objects, payload, Cache, Output, dist, Backups).
      - Preserves all developer configuration directories (.github/, .vscode/, .devcontainer/, .nyxproject).
      - Preserves user libraries (*.a, *.dylib), user source files, scripts, documents, and user archives.
      - Preserves unmarked legacy archives and user-created timestamped archives to prioritize safety.
      - Excludes the current backup archive being written.
      - Excludes verified NyxWin backup archives containing the NYXWIN_BACKUP_V1 unique marker.
      - Excludes final compiled IPA release packages (*.ipa) in dist/ or project root.
      - Excludes established generated build intermediates (e.g. *.o, *.obj, *.d, build_manifest.json, staged .app bundles).
      - Excludes established compiler module/object caches (*.pcm, *.swiftmodule in root cache directories).
    """
    # 1. Skip the current backup archive being written
    try:
        if file_path.resolve() == backup_file.resolve():
            return True
    except Exception:
        pass

    try:
        rel = file_path.relative_to(proj_dir)
    except Exception:
        return False

    rel_parts_lower = [p.lower() for p in rel.parts]

    # 2. Universal internal system directory and file exclusions (.git, __pycache__, etc.)
    # Developer config directories (.github/, .vscode/, .devcontainer/, .nyxproject) are explicitly preserved.
    if any(p in EXCLUDED_INTERNAL_DIRS for p in rel_parts_lower[:-1]):
        return True
    if file_path.name.lower() in EXCLUDED_SYSTEM_FILES or file_path.suffix.lower() in EXCLUDED_SYSTEM_EXTS:
        return True

    # 3. Final compiled IPA release packages (*.ipa): Excluded from source backups (canonical location is dist/)
    if file_path.suffix.lower() == ".ipa":
        return True

    # 4. Verified NyxWin backup archives (identified by authoritative NYXWIN_BACKUP_V1 marker)
    if file_path.suffix.lower() == ".zip":
        if is_nyxwin_backup_archive(file_path, actual_name):
            return True

    # 5. Established generated build intermediates (only within root build/ directory)
    if len(rel.parts) >= 2 and rel_parts_lower[0] == "build":
        # Compiled object and dependency files
        if file_path.suffix.lower() in (".o", ".obj", ".d"):
            return True
        # Exact build manifest generated by the compiler pipeline
        if len(rel.parts) == 2 and rel_parts_lower[1] == "build_manifest.json":
            return True
        # Staged application bundle inside payload directory (e.g. build/Payload/<AppName>.app/...)
        if len(rel_parts_lower) >= 3 and rel_parts_lower[1] == "payload" and any(p.endswith(".app") for p in rel_parts_lower[2:]):
            return True
        # Generated intermediate binary matching project name with Mach-O magic
        if len(rel.parts) == 2 and rel_parts_lower[1] == actual_name.lower():
            try:
                with open(file_path, "rb") as bf:
                    hdr = bf.read(4)
                    if hdr in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"):  # Mach-O magic
                        return True
            except Exception:
                pass

    # 6. Established compiler cache artifacts (only within root cache/ directory)
    if len(rel.parts) >= 2 and rel_parts_lower[0] == "cache":
        if file_path.suffix.lower() in (".pcm", ".swiftmodule", ".swiftdoc", ".swiftsourceinfo", ".timestamp"):
            return True

    # 7. Staged application bundle inside legacy root output/payload (e.g. output/Payload/<AppName>.app/...)
    if len(rel.parts) >= 3 and rel_parts_lower[0] == "output" and rel_parts_lower[1] == "payload":
        if any(p.endswith(".app") for p in rel_parts_lower[2:]):
            return True

    # All other user files, scripts, sources, data, and configs are preserved!
    return False

def create_project_backup(toolchain: Toolchain, project_name: str) -> Optional[Path]:
    """
    Creates a timestamped .zip backup snapshot of a project with safety verification.

    Exclusion policy:
      - Preserves all legitimate user source files, scripts, assets, documents, and archives,
        even if located inside root or nested directories named 'Cache', 'Output', 'Build', 'Backups', or 'dist'.
      - Excludes only verified generated data: final compiled IPA deliverables (*.ipa),
        known build intermediates (build/objects/**, build_manifest.json), compiler cache artifacts,
        and verified NyxWin backup archives to prevent recursive archiving.
    """
    proj_dir = toolchain.get_project_dir(project_name)
    if not proj_dir or not proj_dir.is_dir():
        log_error(f"Project directory not found: {project_name}")
        return None

    actual_name = proj_dir.name
    backups_dir = resolve_backups_dir(toolchain, proj_dir)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backups_dir / f"{actual_name}_{timestamp}.zip"

    proj_root_res = proj_dir.resolve()
    count = 0
    with zipfile.ZipFile(backup_file, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.comment = NYXWIN_BACKUP_MARKER
        for root, dirs, files in os.walk(proj_dir):
            curr_res = Path(root).resolve()
            is_root = (curr_res == proj_root_res)

            # Prune only explicitly excluded internal system directories (.git, __pycache__, etc.)
            dirs[:] = [
                d for d in dirs
                if d.lower() not in EXCLUDED_INTERNAL_DIRS
            ]

            for f in files:
                p = Path(root) / f
                if should_exclude_from_backup(p, proj_dir, backup_file, actual_name):
                    continue

                rel = p.relative_to(proj_dir)
                zf.write(p, rel)
                count += 1

    if not backup_file.is_file() or backup_file.stat().st_size == 0:
        log_error(f"Failed to create backup archive: {backup_file}")
        return None

    size_kb = backup_file.stat().st_size / 1024
    log_success(f"Backup created: {backup_file.name} ({count} files, {size_kb:.1f} KB)")
    return backup_file

def list_project_backups(toolchain: Toolchain, project_name: str) -> List[Dict[str, Any]]:
    """Lists all backup archives available for a project across modern and legacy locations."""
    proj_dir = toolchain.get_project_dir(project_name)
    actual_name = proj_dir.name if proj_dir else project_name

    dirs_to_check = []
    if proj_dir:
        dirs_to_check.append(resolve_backups_dir(toolchain, proj_dir))
    if toolchain.backups_dir:
        legacy_dir = toolchain.backups_dir / actual_name
        if legacy_dir not in dirs_to_check:
            dirs_to_check.append(legacy_dir)

    backups = []
    seen_files = set()
    for b_dir in dirs_to_check:
        if not b_dir.is_dir():
            continue
        for f in sorted(b_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
            if f.name in seen_files:
                continue
            seen_files.add(f.name)
            mtime = datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            size_kb = f.stat().st_size / 1024
            backups.append({
                "path": f,
                "filename": f.name,
                "size_kb": size_kb,
                "mtime": mtime
            })
    return backups

def validate_backup_archive(backup_path: Path, staging_dir: Path) -> Tuple[bool, str]:
    """
    Validates a backup ZIP archive before extraction or project modification.
    Checks:
    - Archive existence and valid ZIP structure
    - CRC / integrity via testzip()
    - Path traversal (zip-slip), absolute paths, Windows drive/UNC paths
    - Protected VCS directory injection (.git, .hg, .svn)
    - Protected IPA artifact overwrite attempts (*.ipa)
    - Case-insensitive duplicate paths and file/directory conflicts under Windows semantics
    - Unsafe symlink entries escaping the project root
    """
    if not backup_path.is_file():
        return False, f"Backup file not found: {backup_path}"

    if not zipfile.is_zipfile(backup_path):
        return False, f"Invalid or corrupted ZIP archive: {backup_path}"

    staging_resolved = staging_dir.resolve()
    seen_files: Dict[Tuple[str, ...], str] = {}
    seen_dirs: Dict[Tuple[str, ...], str] = {}

    try:
        with zipfile.ZipFile(backup_path, "r") as zf:
            bad_member = zf.testzip()
            if bad_member is not None:
                return False, f"Corrupted member in backup archive: {bad_member}"

            infos = zf.infolist()
            if not infos:
                return False, "Backup archive is empty."

            for info in infos:
                raw_name = info.filename
                if not raw_name or raw_name.startswith(("/", "\\")) or ":" in raw_name:
                    return False, f"Malicious or absolute path in backup archive: {raw_name}"

                norm_name = raw_name.replace("\\", "/")
                is_dir_entry = info.is_dir() or norm_name.endswith("/")
                raw_parts = [p for p in norm_name.split("/") if p]
                if ".." in raw_parts:
                    return False, f"Malicious path in backup archive: {raw_name}"

                parts = [p for p in raw_parts if p != "."]
                if not parts:
                    continue

                if parts[0].casefold() in PROTECTED_VCS_DIRS:
                    return False, f"Backup archive cannot overwrite protected VCS directory: {raw_name}"

                if any(p.casefold().endswith(".ipa") for p in parts):
                    return False, f"Backup archive cannot overwrite protected IPA artifact: {raw_name}"

                norm_key = tuple(p.casefold() for p in parts)
                for depth in range(1, len(norm_key)):
                    prefix = norm_key[:depth]
                    if prefix in seen_files:
                        return (
                            False,
                            f"File/directory path conflict in backup archive: '{raw_name}' "
                            f"conflicts with file '{seen_files[prefix]}'",
                        )
                    seen_dirs.setdefault(prefix, raw_name)

                if is_dir_entry:
                    if norm_key in seen_files:
                        return (
                            False,
                            f"File/directory path conflict in backup archive: directory '{raw_name}' "
                            f"conflicts with file '{seen_files[norm_key]}'",
                        )
                    seen_dirs.setdefault(norm_key, raw_name)
                else:
                    if norm_key in seen_files:
                        return (
                            False,
                            f"Duplicate or case-colliding path in backup archive: '{raw_name}' "
                            f"conflicts with '{seen_files[norm_key]}'",
                        )
                    if norm_key in seen_dirs:
                        return (
                            False,
                            f"File/directory path conflict in backup archive: file '{raw_name}' "
                            f"conflicts with directory '{seen_dirs[norm_key]}'",
                        )
                    seen_files[norm_key] = raw_name

                target_path = (staging_resolved / Path(*parts)).resolve()
                if not is_safe_subpath(target_path, staging_resolved) or target_path == staging_resolved:
                    return False, f"Archive member escapes staging root: {raw_name}"

                # Check Unix symlink attribute in ZipInfo
                unix_mode = (info.external_attr >> 16) & 0xFFFF
                is_symlink = (unix_mode & 0o170000) == 0o120000
                if is_symlink:
                    raw_link = zf.read(info).decode("utf-8", errors="replace").strip()
                    if (
                        not raw_link
                        or raw_link.startswith(("/", "\\"))
                        or ":" in raw_link
                        or ".." in raw_link.replace("\\", "/").split("/")
                    ):
                        return False, f"Unsafe symlink target in backup archive: {raw_name} -> {raw_link}"
                    link_target = (target_path.parent / raw_link).resolve()
                    if not is_safe_subpath(link_target, staging_resolved):
                        return False, f"Symlink escapes project root: {raw_name} -> {raw_link}"
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        return False, f"Archive validation failed: {exc}"

    return True, "OK"


def _snapshot_for_rollback(proj_dir: Path, rollback_dir: Path) -> None:
    """
    Copies all current non-VCS items from `proj_dir` into `rollback_dir`
    so that if replacement fails partway through, `proj_dir` can be rolled back
    to its exact pre-restore state without touching `.git/`.
    """
    if not proj_dir.is_dir():
        return
    for item in proj_dir.iterdir():
        if item.name.lower() in PROTECTED_VCS_DIRS:
            continue
        dest = rollback_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest, symlinks=True)
        else:
            shutil.copy2(item, dest)


def _rollback_project_dir(proj_dir: Path, rollback_dir: Path) -> None:
    """
    Restores `proj_dir` from `rollback_dir` if an error occurred during replacement.
    Never modifies or deletes `.git/`, `.hg/`, or `.svn/`.
    """
    if not proj_dir.is_dir():
        proj_dir.mkdir(parents=True, exist_ok=True)
    else:
        for item in list(proj_dir.iterdir()):
            if item.name.lower() in PROTECTED_VCS_DIRS:
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

    if rollback_dir.is_dir():
        for item in rollback_dir.iterdir():
            if item.name.lower() in PROTECTED_VCS_DIRS:
                continue
            dest = proj_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dest, symlinks=True, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)


def _clean_dist_preserving_ipas(dist_dir: Path) -> bool:
    """
    Cleans backup-managed files inside `dist/` while strictly preserving `.ipa` files.
    Returns True if `dist_dir` still contains preserved `.ipa` files.
    """
    has_preserved = False
    for item in list(dist_dir.iterdir()):
        if item.is_dir():
            if _clean_dist_preserving_ipas(item):
                has_preserved = True
            else:
                shutil.rmtree(item)
        else:
            if item.suffix.lower() == ".ipa":
                has_preserved = True
            else:
                item.unlink()
    return has_preserved


def _copy_staged_tree_preserving_ipas(src_dir: Path, dst_dir: Path) -> None:
    """
    Recursively copies extracted staging directory contents into `dst_dir`
    while refusing to overwrite or copy any `.ipa` artifact.
    """
    dst_dir.mkdir(parents=True, exist_ok=True)
    for child in src_dir.iterdir():
        if child.suffix.lower() == ".ipa":
            continue
        target = dst_dir / child.name
        if child.is_dir():
            _copy_staged_tree_preserving_ipas(child, target)
        else:
            if target.exists() and target.suffix.lower() == ".ipa":
                continue
            shutil.copy2(child, target)


def _apply_staged_restore(proj_dir: Path, temp_restore: Path, actual_name: str) -> None:
    """
    Applies the validated, extracted backup staging tree (`temp_restore`) to `proj_dir`:
    - Strictly preserves `.git/`, `.hg/`, `.svn/` (never touched).
    - Strictly preserves `.vscode/` and `.idea/` directories and their existing files,
      overlaying any backed-up settings on top.
    - Strictly preserves `dist/*.ipa` (and root `*.ipa` / marked backup archives),
      while restoring backup-managed files inside `dist/`.
    - Removes stale backup-managed files created after the backup snapshot.
    """
    if proj_dir.exists():
        for item in list(proj_dir.iterdir()):
            name_lower = item.name.lower()
            # 1. Never touch VCS directories (.git, .hg, .svn) or IDE config directories (.vscode, .idea)
            if name_lower in PROTECTED_USER_DIRS:
                continue

            # 2. Preserve dist/*.ipa deliverables while cleaning non-IPA files in dist/
            if name_lower == "dist" and item.is_dir():
                has_ipas = _clean_dist_preserving_ipas(item)
                if not has_ipas and not (temp_restore / item.name).exists():
                    shutil.rmtree(item)
                continue

            # 3. Preserve root .ipa deliverables or marked NyxWin backup archives
            if item.is_file():
                if item.suffix.lower() == ".ipa":
                    continue
                if item.suffix.lower() == ".zip" and is_nyxwin_backup_archive(item, actual_name):
                    continue

            # 4. Remove backup-managed directory or file
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    else:
        proj_dir.mkdir(parents=True, exist_ok=True)

    # Copy extracted backup contents into proj_dir without overwriting protected .ipa artifacts
    for item in temp_restore.iterdir():
        if item.name.lower() in PROTECTED_VCS_DIRS:
            continue
        if item.suffix.lower() == ".ipa":
            continue
        dest = proj_dir / item.name
        if item.is_dir():
            _copy_staged_tree_preserving_ipas(item, dest)
        else:
            if dest.exists() and dest.suffix.lower() == ".ipa":
                continue
            shutil.copy2(item, dest)


def restore_project_backup(toolchain: Toolchain, project_name: str, backup_path: Path) -> bool:
    """
    Restores a project from a backup snapshot with archive validation,
    a verified pre-restore safety snapshot, protected user/VCS preservation,
    and automatic rollback on mid-restore failure or interruption.
    """
    if isinstance(backup_path, str):
        backup_path = Path(backup_path)

    if not backup_path.is_file():
        log_error(f"Backup file not found: {backup_path}")
        return False

    proj_dir = toolchain.get_project_dir(project_name)
    if not proj_dir:
        cand = toolchain.projects_dir / project_name if toolchain.projects_dir else Path(project_name)
        proj_dir = cand

    actual_name = proj_dir.name
    backups_dir = resolve_backups_dir(toolchain, proj_dir) if proj_dir.exists() else toolchain.backups_dir / actual_name

    temp_dir_obj = tempfile.TemporaryDirectory(prefix="nyx_restore_")
    rollback_dir_obj = tempfile.TemporaryDirectory(prefix="nyx_rollback_")
    temp_restore = Path(temp_dir_obj.name)
    temp_rollback = Path(rollback_dir_obj.name)
    safety_zip: Optional[Path] = None
    rollback_cleanup_safe = True

    try:
        # 1. Validate archive integrity, paths, collisions, IPA protection, and symlinks BEFORE touching the project
        is_valid, err_msg = validate_backup_archive(backup_path, temp_restore)
        if not is_valid:
            log_error(err_msg)
            return False

        # 2. Extract backup into isolated staging directory
        with zipfile.ZipFile(backup_path, "r") as zf:
            zf.extractall(temp_restore)

        # 3. Create and VERIFY pre-restore safety snapshot if project exists
        if proj_dir.is_dir():
            log_info("Creating safety snapshot of current project state before restore...")
            os.makedirs(backups_dir, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            safety_zip = backups_dir / f"{actual_name}_pre_restore_{ts}.zip"
            with zipfile.ZipFile(safety_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.comment = NYXWIN_BACKUP_MARKER
                for root, dirs, files in os.walk(proj_dir):
                    dirs[:] = [
                        d for d in dirs
                        if d.lower() not in EXCLUDED_INTERNAL_DIRS
                    ]
                    for f in files:
                        p = Path(root) / f
                        if should_exclude_from_backup(p, proj_dir, safety_zip, actual_name):
                            continue
                        zf.write(p, p.relative_to(proj_dir))

            if not safety_zip.is_file() or safety_zip.stat().st_size == 0:
                log_error("Safety snapshot verification failed. Aborting restore to prevent data loss.")
                return False
            log_success(f"Pre-restore safety snapshot verified: {safety_zip.name}")

            # 4. Snapshot current non-VCS project state into temp_rollback for atomic rollback
            _snapshot_for_rollback(proj_dir, temp_rollback)

        # 5. Apply staged restore with automatic rollback on any exception OR interruption (KeyboardInterrupt/SystemExit)
        try:
            _apply_staged_restore(proj_dir, temp_restore, actual_name)
        except BaseException as apply_err:
            is_interruption = isinstance(apply_err, (KeyboardInterrupt, SystemExit))
            log_error(
                f"Restore interrupted during replacement ({type(apply_err).__name__}: {apply_err}); "
                f"rolling back project state..."
            )
            try:
                _rollback_project_dir(proj_dir, temp_rollback)
                log_info("Project state rolled back to pre-restore snapshot.")
            except BaseException as rb_err:
                rollback_cleanup_safe = False
                safety_hint = (
                    f" Pre-restore safety archive preserved at: {safety_zip}."
                    if safety_zip and safety_zip.is_file()
                    else ""
                )
                log_error(
                    f"CRITICAL: Rollback failed ({type(rb_err).__name__}: {rb_err}) after restore interruption "
                    f"({type(apply_err).__name__}: {apply_err}).{safety_hint} "
                    f"Emergency rollback snapshot retained at: {temp_rollback}"
                )
            if is_interruption:
                raise
            return False

        log_success(f"Project '{actual_name}' successfully restored from: {backup_path.name}")
        return True
    except Exception as e:
        log_error(f"Restore failed: {e}")
        return False
    finally:
        temp_dir_obj.cleanup()
        if rollback_cleanup_safe:
            rollback_dir_obj.cleanup()
