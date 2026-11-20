"""
NyxWin Isolated Project Configuration Migration Adapter.

Provides one-way migration from:
  1. Historical legacy configurations ('NX*' / 'NXAvixR2' schema)
  2. Intermediate Native Schema v1.0 configurations ('Name', 'BundleIdentifier', 'ClangFlags', etc.)
into the standardized Apple/Xcode-terminology Native Schema v2.0.

All legacy 'NX*' identifiers and Schema v1.0 field mappings are strictly isolated
within this module so the active application codebase operates exclusively on
the standardized Canonical Schema v2.0.
"""
import copy
import plistlib
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Historical Nyxian-derived keys recognized for one-way import only
HISTORICAL_NX_KEYS = {
    "NXProjectFormat",
    "NXProjectScheme",
    "NXDisplayName",
    "NXExecutable",
    "NXBundleIdentifier",
    "NXBundleVersion",
    "NXBundleShortVersion",
    "NXDeploymentTarget",
    "NXOrganizationPrefix",
    "NXOutputPath",
    "NXSignMachOWithNyxianEntitlements",
    "NXLinkFrameworksAutomatically",
    "NXCompiler",
    "NXClangFlags",
    "NXSwiftFlags",
    "NXLinkerFlags",
    "NXFrameworks",
    "NXWeakFrameworks",
    "NXBundleInfo",
}

# Historical keys with no direct canonical equivalent (reported when stripped)
UNSUPPORTED_HISTORICAL_KEYS: Dict[str, str] = {
    "NXProjectFormat": "Replaced by canonical 'SchemaVersion' ('2.0').",
    "NXSignMachOWithNyxianEntitlements": "Removed; signing is governed by Config/Entitlements.plist and build profile.",
    "NXLinkFrameworksAutomatically": "Removed; linked frameworks are explicitly declared in 'Frameworks' and 'WeakFrameworks'.",
    "NXOrganizationPrefix": "Removed; organization prefix is encoded directly in 'PRODUCT_BUNDLE_IDENTIFIER'.",
    "NXOutputPath": "Removed; build output locations (TARGET_BUILD_DIR / BUILT_PRODUCTS_DIR) are derived dynamically.",
}

# Intermediate Native Schema v1.0 keys recognized for one-way upgrade to Schema v2.0
SCHEMA_V1_KEYS = {
    "Name",
    "ExecutableName",
    "BundleIdentifier",
    "Version",
    "BuildNumber",
    "DeploymentTarget",
    "ClangFlags",
    "SwiftFlags",
    "LinkerFlags",
    "BundleInfo",
}

# One-way macro substitution upgrade table (legacy & v1.0 -> canonical Apple/Xcode v2.0)
MACRO_MIGRATION_MAP: Dict[str, str] = {
    "$(NXExecutable)": "$(EXECUTABLE_NAME)",
    "$(ExecutableName)": "$(EXECUTABLE_NAME)",
    "$(NXBundleIdentifier)": "$(PRODUCT_BUNDLE_IDENTIFIER)",
    "$(BundleIdentifier)": "$(PRODUCT_BUNDLE_IDENTIFIER)",
    "$(NXDisplayName)": "$(CFBundleDisplayName)",
    "$(LDEDisplayName)": "$(PRODUCT_NAME)",
    "$(Name)": "$(PRODUCT_NAME)",
    "$(NXBundleShortVersion)": "$(MARKETING_VERSION)",
    "$(Version)": "$(MARKETING_VERSION)",
    "$(NXBundleVersion)": "$(CURRENT_PROJECT_VERSION)",
    "$(BuildNumber)": "$(CURRENT_PROJECT_VERSION)",
    "$(NXDeploymentTarget)": "$(IPHONEOS_DEPLOYMENT_TARGET)",
    "$(DeploymentTarget)": "$(IPHONEOS_DEPLOYMENT_TARGET)",
}


@dataclass
class ProjectMigrationResult:
    """Structured report returned by on-disk or in-memory project configuration migration."""
    migrated: bool
    original_format: str
    target_format: str = "schema_v2"
    backup_path: Optional[Path] = None
    unsupported_fields_removed: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)


def detect_project_schema_format(raw: Dict[str, Any]) -> str:
    """
    Detects the schema format of a raw project configuration dictionary.

    Returns:
      - 'legacy_nx': Contains historical 'NX*' keys or 'NXProjectFormat'.
      - 'schema_v1': Contains intermediate Schema v1.0 keys ('Name', 'BundleIdentifier', 'ClangFlags', etc.)
                     or SchemaVersion == '1.0'.
      - 'schema_v2': Pure standardized Apple-terminology Schema v2.0.
    """
    if not isinstance(raw, dict):
        return "schema_v2"

    if "NXProjectFormat" in raw or any(k in HISTORICAL_NX_KEYS or k.startswith("NX") for k in raw.keys()):
        return "legacy_nx"

    if any(k in SCHEMA_V1_KEYS for k in raw.keys()):
        return "schema_v1"

    if str(raw.get("SchemaVersion", "")) == "1.0":
        return "schema_v1"

    return "schema_v2"


def is_legacy_or_v1_config(raw: Dict[str, Any]) -> bool:
    """Returns True if the dictionary requires migration from legacy_nx or schema_v1."""
    return detect_project_schema_format(raw) in ("legacy_nx", "schema_v1")


def upgrade_legacy_macros(val: Any) -> Any:
    """Recursively upgrades legacy $(NX*) and Schema v1.0 $(Name)/etc. macros to Canonical Schema v2.0 macros."""
    if isinstance(val, str):
        res = val
        for old_macro, new_macro in MACRO_MIGRATION_MAP.items():
            if old_macro in res:
                res = res.replace(old_macro, new_macro)
        return res
    elif isinstance(val, list):
        return [upgrade_legacy_macros(item) for item in val]
    elif isinstance(val, dict):
        return {k: upgrade_legacy_macros(v) for k, v in val.items()}
    return copy.deepcopy(val)


def _extract_embedded_frameworks_and_clean_flags(
    flags: List[str],
    frameworks: List[str],
    weak_frameworks: List[str],
    strip_default_uikit_from_cflags: bool = False,
) -> List[str]:
    """
    Extracts any '-framework <Name>' or '-weak_framework <Name>' pairs embedded inside
    compiler or linker flag lists into the canonical Frameworks / WeakFrameworks lists
    to prevent duplicate dependency storage.
    """
    cleaned: List[str] = []
    idx = 0
    while idx < len(flags):
        flg = str(flags[idx])
        if flg == "-framework" and idx + 1 < len(flags):
            fw = str(flags[idx + 1])
            if fw and "$" not in fw and fw not in frameworks:
                frameworks.append(fw)
            idx += 2
        elif flg == "-weak_framework" and idx + 1 < len(flags):
            wfw = str(flags[idx + 1])
            if wfw and "$" not in wfw and wfw not in weak_frameworks:
                weak_frameworks.append(wfw)
            idx += 2
        else:
            cleaned.append(flg)
            idx += 1
    return cleaned


def migrate_project_config_dict(
    raw: Dict[str, Any],
    project_dir: Optional[Path] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """
    One-way migration from historical 'legacy_nx' or 'schema_v1' dictionary into
    the standardized Apple-terminology Canonical Schema v2.0.

    Returns:
      Tuple of (migrated_canonical_dict, list_of_unsupported_or_migration_notes)
    """
    if not isinstance(raw, dict):
        return {}, ["Input configuration was not a dictionary."]

    notes: List[str] = []
    fallback_name = project_dir.name if (project_dir and hasattr(project_dir, "name") and project_dir.name) else "App"

    # Record unsupported historical keys that are being stripped
    for k in list(raw.keys()):
        if k in UNSUPPORTED_HISTORICAL_KEYS:
            notes.append(f"{k}: {UNSUPPORTED_HISTORICAL_KEYS[k]}")
        elif k.startswith("NX") and k not in HISTORICAL_NX_KEYS:
            notes.append(f"{k}: Unrecognized legacy NX* key stripped during migration.")

    # 1. Resolve Product Name, Display Name, and Executable Name
    product_name = (
        raw.get("PRODUCT_NAME")
        or raw.get("Name")
        or raw.get("NXDisplayName")
        or raw.get("CFBundleDisplayName")
        or fallback_name
    )
    display_name = (
        raw.get("CFBundleDisplayName")
        or raw.get("NXDisplayName")
        or raw.get("Name")
        or raw.get("PRODUCT_NAME")
        or product_name
    )
    exec_name = (
        raw.get("EXECUTABLE_NAME")
        or raw.get("ExecutableName")
        or raw.get("NXExecutable")
        or product_name
    )

    # 2. Resolve Bundle Identifier (deriving from NXOrganizationPrefix only if bundle ID is absent)
    bundle_id = (
        raw.get("PRODUCT_BUNDLE_IDENTIFIER")
        or raw.get("BundleIdentifier")
        or raw.get("NXBundleIdentifier")
    )
    if not bundle_id:
        org_prefix = raw.get("NXOrganizationPrefix")
        if org_prefix and isinstance(org_prefix, str) and org_prefix.strip():
            bundle_id = f"{org_prefix.strip().rstrip('.')}.{str(product_name).lower()}"
        else:
            bundle_id = f"com.example.{str(product_name).lower()}"

    # 3. Resolve Marketing Version (CFBundleShortVersionString) and Current Project Version (CFBundleVersion)
    marketing_version = str(
        raw.get("MARKETING_VERSION")
        or raw.get("Version")
        or raw.get("NXBundleShortVersion")
        or raw.get("NXBundleVersion")
        or "1.0"
    )
    current_project_version = str(
        raw.get("CURRENT_PROJECT_VERSION")
        or raw.get("BuildNumber")
        or raw.get("NXBundleVersion")
        or "1"
    )

    # 4. Resolve Deployment Target, TargetType, Compiler, and SWIFT_VERSION
    deployment_target = str(
        raw.get("IPHONEOS_DEPLOYMENT_TARGET")
        or raw.get("DeploymentTarget")
        or raw.get("NXDeploymentTarget")
        or "17.0"
    )
    target_type = str(raw.get("TargetType") or raw.get("NXProjectScheme") or "Application")
    compiler = str(raw.get("Compiler") or raw.get("NXCompiler") or "swiftc")
    swift_version = str(raw.get("SWIFT_VERSION") or "5.0")

    # 5. Resolve Frameworks, WeakFrameworks, and Libraries
    frameworks: List[str] = []
    for fw in (raw.get("Frameworks") if "Frameworks" in raw else raw.get("NXFrameworks", [])) or []:
        if fw not in frameworks:
            frameworks.append(str(fw))

    weak_frameworks: List[str] = []
    for wfw in (raw.get("WeakFrameworks") if "WeakFrameworks" in raw else raw.get("NXWeakFrameworks", [])) or []:
        if wfw not in weak_frameworks:
            weak_frameworks.append(str(wfw))

    libraries: List[str] = []
    for lib in raw.get("Libraries", []) or []:
        if lib not in libraries:
            libraries.append(str(lib))

    # 6. Resolve Compiler & Linker Flags and upgrade embedded macros
    raw_cflags = (
        raw.get("OTHER_CFLAGS")
        if "OTHER_CFLAGS" in raw
        else (raw.get("ClangFlags") if "ClangFlags" in raw else raw.get("NXClangFlags", []))
    ) or []
    raw_cxxflags = raw.get("OTHER_CPLUSPLUSFLAGS", []) or []
    raw_swift_flags = (
        raw.get("OTHER_SWIFT_FLAGS")
        if "OTHER_SWIFT_FLAGS" in raw
        else (raw.get("SwiftFlags") if "SwiftFlags" in raw else raw.get("NXSwiftFlags", []))
    ) or []
    raw_ldflags = (
        raw.get("OTHER_LDFLAGS")
        if "OTHER_LDFLAGS" in raw
        else (raw.get("LinkerFlags") if "LinkerFlags" in raw else raw.get("NXLinkerFlags", []))
    ) or []

    upgraded_cflags = [upgrade_legacy_macros(str(f)) for f in raw_cflags]
    upgraded_cxxflags = [upgrade_legacy_macros(str(f)) for f in raw_cxxflags]
    upgraded_swift_flags = [upgrade_legacy_macros(str(f)) for f in raw_swift_flags]
    upgraded_ldflags = [upgrade_legacy_macros(str(f)) for f in raw_ldflags]

    other_cflags = _extract_embedded_frameworks_and_clean_flags(
        upgraded_cflags, frameworks, weak_frameworks
    )
    other_ldflags = _extract_embedded_frameworks_and_clean_flags(
        upgraded_ldflags, frameworks, weak_frameworks
    )

    # 7. Resolve InfoPlist dictionary and upgrade embedded macros
    raw_info_plist = (
        raw.get("InfoPlist")
        if "InfoPlist" in raw
        else (raw.get("BundleInfo") if "BundleInfo" in raw else raw.get("NXBundleInfo", {}))
    )
    info_plist: Dict[str, Any] = {}
    if isinstance(raw_info_plist, dict):
        info_plist = upgrade_legacy_macros(raw_info_plist)

    # 8. Assemble Canonical Schema v2.0 dictionary while preserving unknown custom user keys
    migrated: Dict[str, Any] = {}
    for k, v in raw.items():
        if k not in HISTORICAL_NX_KEYS and not k.startswith("NX") and k not in SCHEMA_V1_KEYS:
            migrated[k] = upgrade_legacy_macros(v)

    migrated["SchemaVersion"] = "2.0"
    migrated["TargetType"] = target_type
    migrated["PRODUCT_NAME"] = str(product_name)
    migrated["CFBundleDisplayName"] = str(display_name)
    migrated["EXECUTABLE_NAME"] = str(exec_name)
    migrated["PRODUCT_BUNDLE_IDENTIFIER"] = str(bundle_id)
    migrated["MARKETING_VERSION"] = marketing_version
    migrated["CURRENT_PROJECT_VERSION"] = current_project_version
    migrated["IPHONEOS_DEPLOYMENT_TARGET"] = deployment_target
    migrated["Compiler"] = compiler
    migrated["SWIFT_VERSION"] = swift_version
    migrated["OTHER_CFLAGS"] = list(other_cflags)
    migrated["OTHER_CPLUSPLUSFLAGS"] = list(upgraded_cxxflags)
    migrated["OTHER_SWIFT_FLAGS"] = list(upgraded_swift_flags)
    migrated["OTHER_LDFLAGS"] = list(other_ldflags)
    migrated["Frameworks"] = list(frameworks)
    migrated["WeakFrameworks"] = list(weak_frameworks)
    migrated["Libraries"] = list(libraries)
    migrated["InfoPlist"] = info_plist

    return migrated, notes


def migrate_project_on_disk(
    project_dir: Path,
    create_backup: bool = True,
) -> ProjectMigrationResult:
    """
    Performs a controlled, atomic on-disk migration of a project's Project.plist
    to Canonical Schema v2.0 with backup creation and failure recovery.
    """
    from nyxwin.core.project import find_project_config_file

    p_in = Path(project_dir).resolve()
    if p_in.is_file() and p_in.suffix.lower() == ".plist":
        cfg_path = p_in
        p_dir = p_in.parent.parent if p_in.parent.name == "Config" else p_in.parent
    else:
        p_dir = p_in
        cfg_path, status = find_project_config_file(p_dir)
    if not cfg_path or not cfg_path.is_file():
        return ProjectMigrationResult(
            migrated=False,
            original_format="missing",
            warnings=[f"No Project.plist found in {p_dir}"],
        )

    orig_bytes = cfg_path.read_bytes()
    try:
        raw = plistlib.loads(orig_bytes)
    except Exception as exc:
        return ProjectMigrationResult(
            migrated=False,
            original_format="invalid",
            warnings=[f"Failed to parse Project.plist: {exc}"],
        )

    orig_fmt = detect_project_schema_format(raw)
    if orig_fmt == "schema_v2":
        from nyxwin.core.project import normalize_project_config
        norm = normalize_project_config(raw, p_dir)
        return ProjectMigrationResult(
            migrated=False,
            original_format="schema_v2",
            config=norm,
        )

    backup_path: Optional[Path] = None
    if create_backup:
        backup_path = cfg_path.with_suffix(".plist.bak")
        shutil.copy2(cfg_path, backup_path)

    migrated_dict, notes = migrate_project_config_dict(raw, p_dir)
    temp_path = cfg_path.with_suffix(".plist.tmp")

    try:
        serialized = plistlib.dumps(migrated_dict, sort_keys=True)
        # Verify round-trip parse before replacing original file
        verified = plistlib.loads(serialized)
        if not isinstance(verified, dict) or verified.get("SchemaVersion") != "2.0":
            raise ValueError("Migrated configuration failed post-serialization verification.")
        temp_path.write_bytes(serialized)
        temp_path.replace(cfg_path)
    except Exception as exc:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        # Restore from backup if original was touched
        if backup_path and backup_path.is_file():
            shutil.copy2(backup_path, cfg_path)
        else:
            cfg_path.write_bytes(orig_bytes)
        return ProjectMigrationResult(
            migrated=False,
            original_format=orig_fmt,
            backup_path=backup_path,
            unsupported_fields_removed=notes,
            warnings=[f"Migration failed and original file was restored: {exc}"],
        )

    return ProjectMigrationResult(
        migrated=True,
        original_format=orig_fmt,
        backup_path=backup_path,
        unsupported_fields_removed=notes,
        config=migrated_dict,
    )
