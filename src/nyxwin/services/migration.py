"""
NyxWin Safe Data Migration Service.

Provides path inspection and explicit, reversible migration from legacy
repository-local directories (Projects, Backups, Output, Cache, sdk) to standard
user and local app-data locations without deleting source assets.
"""
import os
import sys
import shutil
import hashlib
import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple, Any

from nyxwin.config.paths import (
    USER_CONFIG_DIR,
    RUNTIME_DATA_DIR,
    get_nyxwin_data_root,
    DEFAULT_PROJECTS_DIR,
    get_package_root,
    detect_legacy_paths,
    is_safe_subpath,
)

@dataclass
class FileMigrationItem:
    source_path: str
    dest_path: str
    size_bytes: int
    category: str
    conflicts: bool = False

@dataclass
class MigrationPlan:
    source_root: str
    target_projects_dir: str
    target_data_dir: str
    items: List[FileMigrationItem] = field(default_factory=list)
    total_files: int = 0
    total_bytes: int = 0
    conflict_count: int = 0
    available_space_bytes: int = 0
    can_migrate_safely: bool = True
    warnings: List[str] = field(default_factory=list)

@dataclass
class MigrationResult:
    success: bool
    dry_run: bool
    migrated_files: int = 0
    migrated_bytes: int = 0
    failed_files: List[Tuple[str, str]] = field(default_factory=list)
    report_file: Optional[str] = None
    message: str = ""

def get_active_paths_summary() -> Dict[str, Any]:
    """Returns a structured summary of all active paths and detected legacy locations."""
    pkg_root = get_package_root()
    legacy = detect_legacy_paths(pkg_root)
    return {
        "package_root": str(pkg_root),
        "user_config_dir": str(USER_CONFIG_DIR),
        "runtime_data_dir": str(get_nyxwin_data_root()),
        "default_projects_dir": str(DEFAULT_PROJECTS_DIR),
        "legacy_detected": {k: str(v) for k, v in legacy.items()},
        "has_legacy_data": len(legacy) > 0,
    }

def plan_data_migration(
    source_root: Optional[Path] = None,
    dest_projects: Optional[Path] = None,
    dest_data: Optional[Path] = None,
) -> MigrationPlan:
    """
    Analyzes legacy folders and creates a detailed migration plan.
    Checks conflicts, counts files, and verifies available disk space.
    """
    root = (source_root or get_package_root()).resolve()
    target_proj = (dest_projects or DEFAULT_PROJECTS_DIR).resolve()
    target_data = (dest_data or get_nyxwin_data_root()).resolve()

    plan = MigrationPlan(
        source_root=str(root),
        target_projects_dir=str(target_proj),
        target_data_dir=str(target_data),
    )

    # Categories to migrate:
    # Projects -> target_proj
    # Backups, Cache -> target_data / category
    # sdk -> target_data / "SDKs" (canonical managed SDK directory)
    # Note: Output/ is NOT migrated to a centralized directory because final app deliverables
    # belong in individual project dist/ folders. Legacy Output IPAs are preserved in place.
    category_dest_map = {
        "Projects": target_proj,
        "Backups": target_data / "Backups",
        "Cache": target_data / "Cache",
        "sdk": target_data / "SDKs",
    }

    legacy_dirs = detect_legacy_paths(root)
    if not legacy_dirs:
        plan.warnings.append("No legacy data directories detected in source root.")
        return plan

    if "Output" in legacy_dirs:
        plan.warnings.append(
            "Legacy 'Output' deliverables directory detected in source root: "
            "Output IPAs are valuable deliverables and are preserved in-place at the source location. "
            "They are not migrated to a centralized data root."
        )

    total_bytes = 0
    items = []
    conflict_count = 0

    for cat_name, src_dir in legacy_dirs.items():
        dst_base = category_dest_map.get(cat_name)
        if not dst_base:
            continue

        for dirpath, _, filenames in os.walk(src_dir):
            rel = Path(dirpath).relative_to(src_dir)
            for fname in filenames:
                src_file = Path(dirpath) / fname
                try:
                    size = src_file.stat().st_size
                except OSError:
                    size = 0

                if cat_name == "Projects":
                    dst_file = dst_base / rel / fname
                else:
                    dst_file = dst_base / rel / fname

                conflicts = dst_file.is_file()
                if conflicts:
                    conflict_count += 1

                items.append(
                    FileMigrationItem(
                        source_path=str(src_file),
                        dest_path=str(dst_file),
                        size_bytes=size,
                        category=cat_name,
                        conflicts=conflicts,
                    )
                )
                total_bytes += size

    plan.items = items
    plan.total_files = len(items)
    plan.total_bytes = total_bytes
    plan.conflict_count = conflict_count

    # Check available disk space on target volume
    try:
        drive_target = target_data.anchor or str(target_data)
        usage = shutil.disk_usage(drive_target)
        plan.available_space_bytes = usage.free
        if usage.free < total_bytes:
            plan.can_migrate_safely = False
            plan.warnings.append(
                f"Insufficient disk space on target drive ({usage.free / (1024*1024):.1f} MB free, "
                f"need {total_bytes / (1024*1024):.1f} MB)"
            )
    except Exception as e:
        plan.warnings.append(f"Could not verify available disk space: {e}")

    if conflict_count > 0:
        plan.warnings.append(
            f"{conflict_count} file(s) already exist at the destination and will be skipped to prevent overwriting."
        )

    return plan

def execute_data_migration(
    plan: MigrationPlan,
    dry_run: bool = True,
    progress_callback=None,
) -> MigrationResult:
    """
    Executes or simulates migration based on the plan.
    Never deletes original source files.
    """
    if dry_run:
        return MigrationResult(
            success=plan.can_migrate_safely,
            dry_run=True,
            migrated_files=plan.total_files,
            migrated_bytes=plan.total_bytes,
            message="Dry run complete. No files were copied.",
        )

    if not plan.can_migrate_safely:
        return MigrationResult(
            success=False,
            dry_run=False,
            message="Migration aborted: Safety checks failed.",
        )

    migrated_files = 0
    migrated_bytes = 0
    failed_files = []
    log_records = []

    for item in plan.items:
        src = Path(item.source_path)
        dst = Path(item.dest_path)

        if item.conflicts:
            # Skip conflicting files to protect destination
            log_records.append({"source": str(src), "dest": str(dst), "status": "skipped_conflict"})
            continue

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            # Copy with metadata preservation
            shutil.copy2(src, dst)

            # Verification: Check file size match
            if dst.stat().st_size == src.stat().st_size:
                migrated_files += 1
                migrated_bytes += item.size_bytes
                log_records.append({"source": str(src), "dest": str(dst), "status": "verified_copied"})
            else:
                failed_files.append((str(src), "Size mismatch after copy"))
                log_records.append({"source": str(src), "dest": str(dst), "status": "failed_size_mismatch"})

        except Exception as e:
            failed_files.append((str(src), str(e)))
            log_records.append({"source": str(src), "dest": str(dst), "status": f"failed: {e}"})

        if progress_callback:
            progress_callback(migrated_files, plan.total_files)

    # Save detailed migration report
    report_file = None
    try:
        USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        report_path = USER_CONFIG_DIR / "migration_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "source_root": plan.source_root,
                    "target_projects": plan.target_projects_dir,
                    "target_data": plan.target_data_dir,
                    "migrated_files": migrated_files,
                    "migrated_bytes": migrated_bytes,
                    "failed_count": len(failed_files),
                    "records": log_records,
                },
                f,
                indent=2,
            )
        report_file = str(report_path)
    except Exception:
        pass

    success = len(failed_files) == 0
    msg = (
        f"Successfully migrated {migrated_files} file(s) ({migrated_bytes / (1024*1024):.2f} MB)."
        if success
        else f"Completed with {len(failed_files)} failure(s)."
    )

    return MigrationResult(
        success=success,
        dry_run=False,
        migrated_files=migrated_files,
        migrated_bytes=migrated_bytes,
        failed_files=failed_files,
        report_file=report_file,
        message=msg,
    )
