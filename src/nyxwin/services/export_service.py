"""
NyxWin Portable Project Export & Safe Import Service.

Provides pure CLI and headless-capable export and import workflows:
- Export: Creates clean, portable source archives with .gitignore and configuration,
  excluding .git/, build/, dist/, caches, and binaries.
- Import: Validates archives against zip-slip and absolute paths, assigns fresh
  project identities, and protects against accidental overwrites.
"""
import os
import uuid
import shutil
import zipfile
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List

from nyxwin.core.models import Color, log_info, log_success, log_error, log_warning
from nyxwin.core.project import (
    find_project_config_file,
    find_entitlements_file,
    load_project_config,
    create_project_id_file,
    get_or_create_project_id,
)
from nyxwin.config.paths import is_safe_subpath

EXCLUDED_EXPORT_DIRS = {
    ".git", ".vscode", ".idea", ".nyx",
    "build", "dist", "cache", "output", "backups", "payload",
    "__pycache__"
}

EXCLUDED_EXPORT_EXTS = {
    ".ipa", ".o", ".a", ".dylib", ".so", ".zip",
    ".pyc", ".DS_Store"
}

def export_project(
    project_dir: Path,
    out_zip: Optional[Path] = None,
    format_type: str = "standard",
    verbose: bool = False
) -> Optional[Path]:
    """
    Exports a project directory to a portable source ZIP archive.

    Includes:
      - Project configuration (Config/Project.plist or Project.plist)
      - Entitlements (Config/Entitlements.plist or Entitlements.plist)
      - .nyxproject identity metadata (if present)
      - .gitignore and README.md
      - Resources/ folder and assets
      - All source and header files

    Excludes by default:
      - .git/ internal repository metadata
      - build/ and dist/ generated artifacts
      - Cache/ and Backups/
      - Compiled binaries (*.ipa, *.o, *.a, etc.)
    """
    if not isinstance(project_dir, Path):
        project_dir = Path(project_dir)

    project_dir = project_dir.resolve()
    if not project_dir.is_dir():
        log_error(f"Project directory not found: {project_dir}")
        return None

    cfg_file, _ = find_project_config_file(project_dir)
    if not cfg_file or not cfg_file.is_file():
        log_error(f"Not a valid NyxWin project (Project.plist not found in {project_dir})")
        return None

    proj_name = project_dir.name

    if out_zip is None:
        dist_dir = project_dir / "dist"
        dist_dir.mkdir(parents=True, exist_ok=True)
        out_zip = dist_dir / f"{proj_name}_source.zip"
    else:
        out_zip = Path(out_zip).resolve()
        out_zip.parent.mkdir(parents=True, exist_ok=True)

    prefix = proj_name

    count = 0
    proj_root_res = project_dir.resolve()
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(project_dir):
            curr_res = Path(root).resolve()
            is_root = (curr_res == proj_root_res)

            # Prune excluded directories: root-level output/caches and universal hidden dirs
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".")
                and d.lower() != "__pycache__"
                and not (is_root and d.lower() in EXCLUDED_EXPORT_DIRS)
            ]

            for fname in files:
                fpath = Path(root) / fname
                if fpath.suffix.lower() in EXCLUDED_EXPORT_EXTS:
                    continue
                if fname in (".DS_Store", "Thumbs.db", ".nyxproject"):
                    continue
                if fpath == out_zip:
                    continue

                rel = fpath.relative_to(project_dir)
                archive_member = f"{prefix}/{rel.as_posix()}"
                zf.write(fpath, archive_member)
                count += 1

    size_kb = out_zip.stat().st_size / 1024
    log_success(f"Project exported to: {out_zip} ({count} files, {size_kb:.1f} KB)")
    return out_zip

def import_project(
    archive_path: Path,
    target_dir: Optional[Path] = None,
    new_name: Optional[str] = None,
    overwrite: bool = False
) -> Tuple[bool, Optional[Path], str]:
    """
    Imports a project from a ZIP archive with zip-slip validation.
    Assigns a fresh project identity to imported standalone projects to avoid
    cache collisions with original copies.
    """
    if not isinstance(archive_path, Path):
        archive_path = Path(archive_path)

    if not archive_path.is_file():
        return False, None, f"Archive not found: {archive_path}"

    temp_extract = archive_path.parent / f"__import_temp_{uuid.uuid4().hex[:8]}__"
    temp_extract.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            # Zip slip security check
            for member in zf.namelist():
                m_path = Path(member)
                if m_path.is_absolute() or ".." in m_path.parts:
                    shutil.rmtree(temp_extract, ignore_errors=True)
                    return False, None, f"Zip-slip attempt detected in member: {member}"
            zf.extractall(temp_extract)

        # Locate Project.plist (either modern Config/Project.plist or root Project.plist)
        candidates = list(temp_extract.glob("**/Config/Project.plist"))
        if not candidates:
            candidates = list(temp_extract.glob("**/Project.plist"))

        if not candidates:
            shutil.rmtree(temp_extract, ignore_errors=True)
            return False, None, "Invalid project archive: No Project.plist found in archive."

        plist_file = candidates[0]
        if plist_file.parent.name == "Config":
            src_root = plist_file.parent.parent
        else:
            src_root = plist_file.parent

        dest_name = new_name if new_name else src_root.name
        # If folder name is an anonymous identifier, derive name from Project.plist
        cfg = load_project_config(src_root)
        if cfg:
            proj_name = cfg.get("Name")
            if proj_name and (not new_name and (len(dest_name) == 36 and "-" in dest_name)):
                dest_name = proj_name

        if target_dir is None:
            dest_dir = Path.cwd() / dest_name
        else:
            dest_dir = Path(target_dir) / dest_name

        if dest_dir.exists() and not overwrite:
            shutil.rmtree(temp_extract, ignore_errors=True)
            return False, dest_dir, f"Destination directory already exists: {dest_dir}"

        if dest_dir.exists() and overwrite:
            shutil.rmtree(dest_dir)

        shutil.copytree(src_root, dest_dir)
        shutil.rmtree(temp_extract, ignore_errors=True)

        # Assign fresh identity to imported project to prevent cache collision
        create_project_id_file(dest_dir, dest_name)

        return True, dest_dir, f"Project '{dest_name}' successfully imported to: {dest_dir}"

    except Exception as e:
        shutil.rmtree(temp_extract, ignore_errors=True)
        return False, None, f"Import failed: {e}"
