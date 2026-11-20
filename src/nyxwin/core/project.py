"""
NyxWin Project Configuration and Identity Engine.

Provides centralized resolution for modern (Config/Project.plist) and legacy
(Project.plist) configuration files, entitlements resolution, native project schema
normalization, macro expansion, and persistent project identity management.
"""
import os
import re
import json
import uuid
import hashlib
import plistlib
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

CANONICAL_SCHEMA_VERSION = "2.0"

def find_project_config_file(project_dir: Path) -> Tuple[Optional[Path], str]:
    """
    Deterministically discovers the Project.plist configuration file.

    Resolution Precedence:
      1. Modern layout:   <project_dir>/Config/Project.plist
      2. Legacy layout:   <project_dir>/Project.plist

    If both exist:
      - Warns if contents differ.
      - Deterministically selects Config/Project.plist without deleting either.

    Returns:
      Tuple of (Resolved Path or None, status string: "modern" | "legacy" | "conflict" | "missing")
    """
    if not isinstance(project_dir, Path):
        project_dir = Path(project_dir)

    modern_path = project_dir / "Config" / "Project.plist"
    legacy_path = project_dir / "Project.plist"

    has_modern = modern_path.is_file()
    has_legacy = legacy_path.is_file()

    if has_modern and has_legacy:
        try:
            mod_bytes = modern_path.read_bytes()
            leg_bytes = legacy_path.read_bytes()
            if mod_bytes != leg_bytes:
                print(
                    f"[!] Warning: Conflicting configuration files found in {project_dir.name}.\n"
                    f"    Both 'Config/Project.plist' and 'Project.plist' exist with differing contents.\n"
                    f"    Using preferred 'Config/Project.plist'."
                )
        except Exception:
            pass
        return modern_path, "conflict"

    if has_modern:
        return modern_path, "modern"

    if has_legacy:
        return legacy_path, "legacy"

    return None, "missing"

def find_entitlements_file(project_dir: Path) -> Optional[Path]:
    """
    Resolves the Entitlements.plist path for codesigning.
    Checks Config/Entitlements.plist first, then root Entitlements.plist.
    """
    if not isinstance(project_dir, Path):
        project_dir = Path(project_dir)

    modern_ent = project_dir / "Config" / "Entitlements.plist"
    if modern_ent.is_file():
        return modern_ent

    legacy_ent = project_dir / "Entitlements.plist"
    if legacy_ent.is_file():
        return legacy_ent

    return None

def resolve_and_validate_project_entitlements(project_dir: Path) -> Tuple[bool, Optional[Path], List[str], str]:
    """
    Authoritative entitlement resolution and validation for NyxWin builds.

    1. Resolves Config/Entitlements.plist (or legacy root Entitlements.plist).
    2. Validates existence, read permissions, XML syntax, and dictionary structure.
    3. Returns (is_valid, resolved_path, list_of_keys, diagnostic_message).

    If missing, unreadable, or malformed, returns is_valid=False with an actionable diagnostic.
    """
    if not isinstance(project_dir, Path):
        project_dir = Path(project_dir)

    ent_file = find_entitlements_file(project_dir)
    expected_path = project_dir / "Config" / "Entitlements.plist"

    if ent_file is None:
        rel_expected = "Config/Entitlements.plist"
        return (
            False,
            expected_path,
            [],
            f"Missing entitlement configuration file. Expected '{rel_expected}' in project. To correct this, create Config/Entitlements.plist or use Project Settings > Entitlements to configure it."
        )

    if not ent_file.is_file():
        return (
            False,
            ent_file,
            [],
            f"Entitlement configuration '{ent_file}' is not a regular file."
        )

    try:
        with open(ent_file, "rb") as ef:
            raw_bytes = ef.read()
    except Exception as e:
        return (
            False,
            ent_file,
            [],
            f"Cannot read entitlement file '{ent_file}': {e} (Permission or I/O error)."
        )

    if not raw_bytes.strip():
        return (
            False,
            ent_file,
            [],
            f"Entitlement configuration file '{ent_file.name}' is empty. It must contain a valid XML plist dictionary."
        )

    try:
        data = plistlib.loads(raw_bytes)
    except Exception as e:
        return (
            False,
            ent_file,
            [],
            f"Invalid plist syntax in '{ent_file.name}': {e}. Please check the XML syntax or reconfigure via Project Settings > Entitlements."
        )

    if not isinstance(data, dict):
        return (
            False,
            ent_file,
            [],
            f"Invalid entitlement structure in '{ent_file.name}': root element must be a <dict>, but got {type(data).__name__}."
        )

    keys = list(data.keys())
    return True, ent_file, keys, ""

def is_in_studio_workspace(project_dir: Path) -> bool:
    """Checks if project is inside a multi-project studio workspace (e.g. <Studio>/Projects/<Project>)."""
    parent = project_dir.parent
    if parent.name.lower() == "projects" and parent.is_dir():
        grandparent = parent.parent
        if (grandparent / "pyproject.toml").is_file() or (grandparent / "Output").is_dir() or (grandparent / "Cache").is_dir():
            return True
    return False

def get_or_create_project_id(project_dir: Path, config_data: Optional[dict] = None) -> str:
    """
    Resolves a stable, deterministic project identity identifier.

    Order of resolution:
      1. Existing Config/.nyxproject or .nyxproject metadata file.
         - Validates whether this project directory was copied or moved.
         - If origin_path != current path:
             - If origin_path still exists on disk -> Directory was COPIED.
               Assigns a fresh UUID and updates origin_path to prevent namespace collision.
             - If origin_path does NOT exist on disk -> Directory was MOVED / RENAMED.
               Preserves existing UUID and updates origin_path.
      2. If standalone project lacks .nyxproject (e.g. freshly cloned Git repo):
         - Automatically generates a machine-local Config/.nyxproject.
      3. For studio projects in Projects/:
         - Deterministic fallback hash derived from canonical path and bundle ID
           (Prevents modifying or writing files into existing user studio projects).
    """
    if not isinstance(project_dir, Path):
        project_dir = Path(project_dir)

    curr_path = str(project_dir.resolve())

    # 1. Check for existing metadata file
    meta_candidates = [
        project_dir / "Config" / ".nyxproject",
        project_dir / ".nyxproject",
    ]
    for cand in meta_candidates:
        if cand.is_file():
            try:
                data = json.loads(cand.read_text(encoding="utf-8"))
                existing_id = data.get("id")
                if existing_id:
                    origin = data.get("origin_path")
                    if not origin:
                        # Legacy .nyxproject without origin_path: bind it now to curr_path
                        data["origin_path"] = curr_path
                        cand.write_text(json.dumps(data, indent=2), encoding="utf-8")
                        return str(existing_id)

                    if origin == curr_path:
                        # Identical path, perfect match
                        return str(existing_id)

                    # Path difference detected: determine if moved or copied
                    if Path(origin).is_dir():
                        # Origin directory still exists on disk: Project was COPIED / DUPLICATED!
                        # Regenerate a fresh identity to prevent cache/backup collisions.
                        new_id = str(uuid.uuid4()).lower()
                        data["id"] = new_id
                        data["origin_path"] = curr_path
                        cand.write_text(json.dumps(data, indent=2), encoding="utf-8")
                        return new_id
                    else:
                        # Origin does not exist on disk: Project was MOVED / RENAMED!
                        # Preserve existing ID and update origin_path.
                        data["origin_path"] = curr_path
                        cand.write_text(json.dumps(data, indent=2), encoding="utf-8")
                        return str(existing_id)
            except Exception:
                pass

    # 2. Standalone project lacking .nyxproject (e.g. Git clone) -> generate machine-local ID
    norm_cfg = normalize_project_config(config_data, project_dir) if isinstance(config_data, dict) and config_data else {}
    if not is_in_studio_workspace(project_dir) and (project_dir / "Config").is_dir():
        proj_name = (
            norm_cfg.get("CFBundleDisplayName")
            or norm_cfg.get("PRODUCT_NAME")
            or project_dir.name
        )
        return create_project_id_file(project_dir, proj_name)

    # 3. Deterministic fallback based on resolved path and bundle ID
    bundle_id = norm_cfg.get("PRODUCT_BUNDLE_IDENTIFIER", "")
    if not bundle_id:
        cfg = load_project_config(project_dir)
        if cfg:
            bundle_id = cfg.get("PRODUCT_BUNDLE_IDENTIFIER", "")

    unique_key = f"{project_dir.resolve()}:{bundle_id or project_dir.name}"
    return hashlib.sha256(unique_key.encode("utf-8")).hexdigest()[:12]

def create_project_id_file(project_dir: Path, name: str, force_id: Optional[str] = None) -> str:
    """
    Creates an explicit, persistent Config/.nyxproject metadata file for newly created projects.
    Returns the newly generated UUID string.
    """
    proj_id = force_id if force_id else str(uuid.uuid4()).lower()
    config_dir = project_dir / "Config"
    config_dir.mkdir(parents=True, exist_ok=True)
    meta_path = config_dir / ".nyxproject"

    data = {
        "id": proj_id,
        "name": name,
        "origin_path": str(project_dir.resolve()),
        "schema_version": "2.0"
    }
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
    return proj_id

def get_safe_project_dirname(project_name: str, project_id: str) -> str:
    """Returns a sanitized Windows directory name combining project name and id."""
    safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', project_name)
    return f"{safe_name}-{project_id}"

def normalize_project_config(raw: dict, project_dir: Optional[Path] = None) -> dict:
    """
    Normalizes project configuration dictionaries to the authoritative Canonical Schema v2.0
    using official Apple/Xcode build setting and Info.plist terminology.
    Delegates any historical or v1.0 dictionaries to the isolated project_migration module.
    """
    if not isinstance(raw, dict):
        return {}

    from nyxwin.core.project_migration import is_legacy_or_v1_config, migrate_project_config_dict
    if is_legacy_or_v1_config(raw):
        migrated, _ = migrate_project_config_dict(raw, project_dir)
        return migrated

    cfg = dict(raw)
    fallback_name = project_dir.name if (project_dir and hasattr(project_dir, "name") and project_dir.name) else "App"

    product_name = str(cfg.get("PRODUCT_NAME") or cfg.get("CFBundleDisplayName") or fallback_name)
    display_name = str(cfg.get("CFBundleDisplayName") or product_name)
    exec_name = str(cfg.get("EXECUTABLE_NAME") or product_name)
    bundle_id = str(cfg.get("PRODUCT_BUNDLE_IDENTIFIER") or f"com.example.{product_name.lower()}")
    marketing_version = str(cfg.get("MARKETING_VERSION") or "1.0.0")
    current_project_version = str(cfg.get("CURRENT_PROJECT_VERSION") or "1")
    target_type = str(cfg.get("TargetType") or "Application")
    deployment_target = str(cfg.get("IPHONEOS_DEPLOYMENT_TARGET") or "17.0")
    compiler = str(cfg.get("Compiler") or "swiftc")
    swift_version = str(cfg.get("SWIFT_VERSION") or "5.0")

    other_cflags = cfg.get("OTHER_CFLAGS", [])
    other_cxxflags = cfg.get("OTHER_CPLUSPLUSFLAGS", [])
    other_swift_flags = cfg.get("OTHER_SWIFT_FLAGS", [])
    other_ldflags = cfg.get("OTHER_LDFLAGS", [])
    frameworks = cfg.get("Frameworks", [])
    weak_frameworks = cfg.get("WeakFrameworks", [])
    libraries = cfg.get("Libraries", [])
    info_plist = cfg.get("InfoPlist", {})

    cfg["SchemaVersion"] = "2.0"
    cfg["TargetType"] = target_type
    cfg["PRODUCT_NAME"] = product_name
    cfg["CFBundleDisplayName"] = display_name
    cfg["EXECUTABLE_NAME"] = exec_name
    cfg["PRODUCT_BUNDLE_IDENTIFIER"] = bundle_id
    cfg["MARKETING_VERSION"] = marketing_version
    cfg["CURRENT_PROJECT_VERSION"] = current_project_version
    cfg["IPHONEOS_DEPLOYMENT_TARGET"] = deployment_target
    cfg["Compiler"] = compiler
    cfg["SWIFT_VERSION"] = swift_version
    cfg["OTHER_CFLAGS"] = list(other_cflags)
    cfg["OTHER_CPLUSPLUSFLAGS"] = list(other_cxxflags)
    cfg["OTHER_SWIFT_FLAGS"] = list(other_swift_flags)
    cfg["OTHER_LDFLAGS"] = list(other_ldflags)
    cfg["Frameworks"] = list(frameworks)
    cfg["WeakFrameworks"] = list(weak_frameworks)
    cfg["Libraries"] = list(libraries)
    cfg["InfoPlist"] = dict(info_plist) if isinstance(info_plist, dict) else {}

    return cfg

def load_project_config(project_dir: Path) -> Optional[dict]:
    """Loads, parses, and normalizes the Project.plist configuration."""
    if not isinstance(project_dir, Path):
        project_dir = Path(project_dir)

    # Defensively support being passed the direct Project.plist file path or the project directory
    if project_dir.is_file() and project_dir.suffix.lower() == ".plist":
        config_path = project_dir
        base_dir = project_dir.parent.parent if project_dir.parent.name == "Config" else project_dir.parent
    else:
        config_path, _ = find_project_config_file(project_dir)
        base_dir = project_dir

    if not config_path or not config_path.is_file():
        return None
    try:
        with open(config_path, "rb") as f:
            raw = plistlib.load(f)
        return normalize_project_config(raw, base_dir)
    except Exception:
        return None

def save_project_config(project_dir: Path, config_data: dict) -> bool:
    """
    Saves updated dictionary data back to the resolved Project.plist in XML format.
    Ensures the saved configuration is normalized to Canonical Schema v2.0 with zero legacy keys.
    """
    if not isinstance(project_dir, Path):
        project_dir = Path(project_dir)

    if project_dir.is_file() and project_dir.suffix.lower() == ".plist":
        config_path = project_dir
        base_dir = project_dir.parent.parent if project_dir.parent.name == "Config" else project_dir.parent
    else:
        config_path, _ = find_project_config_file(project_dir)
        base_dir = project_dir
        if not config_path:
            config_path = project_dir / "Config" / "Project.plist"
            config_path.parent.mkdir(parents=True, exist_ok=True)

    clean_data = normalize_project_config(config_data, base_dir)

    try:
        with open(config_path, "wb") as f:
            plistlib.dump(clean_data, f, sort_keys=True)
        return True
    except Exception:
        return False

def expand_macro_variables(val: Any, context: Dict[str, str]) -> Any:
    """
    Recursively expands configuration macros in strings, lists, and dicts.
    Supports canonical Apple/Xcode macros:
      $(PRODUCT_NAME), $(CFBundleDisplayName), $(EXECUTABLE_NAME),
      $(PRODUCT_BUNDLE_IDENTIFIER), $(MARKETING_VERSION), $(CURRENT_PROJECT_VERSION),
      $(IPHONEOS_DEPLOYMENT_TARGET), $(TARGET_BUILD_DIR), $(BUILT_PRODUCTS_DIR),
      $(SDKROOT), and $(CACHEROOT).
    """
    if isinstance(val, str):
        res = val
        for k, v in context.items():
            macro = f"$({k})"
            if macro in res:
                res = res.replace(macro, str(v))
        return res
    elif isinstance(val, list):
        return [expand_macro_variables(item, context) for item in val]
    elif isinstance(val, dict):
        return {k: expand_macro_variables(v, context) for k, v in val.items()}
    return val


def expand_project_macros(
    config: Dict[str, Any],
    sdk_root: Optional[Path] = None,
    cache_root: Optional[Path] = None,
    project_dir: Optional[Path] = None,
    target_build_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Expands all canonical Apple/Xcode macros inside a Canonical Schema v2.0 dictionary.
    """
    product_name = str(config.get("PRODUCT_NAME") or config.get("CFBundleDisplayName") or "App")
    display_name = str(config.get("CFBundleDisplayName") or product_name)
    exec_name = str(config.get("EXECUTABLE_NAME") or product_name)
    bundle_id = str(config.get("PRODUCT_BUNDLE_IDENTIFIER") or f"com.example.{product_name.lower()}")
    marketing_version = str(config.get("MARKETING_VERSION") or "1.0.0")
    current_project_version = str(config.get("CURRENT_PROJECT_VERSION") or "1")
    deployment_target = str(config.get("IPHONEOS_DEPLOYMENT_TARGET") or "17.0")
    swift_version = str(config.get("SWIFT_VERSION") or "5.0")

    context: Dict[str, str] = {
        "PRODUCT_NAME": product_name,
        "CFBundleDisplayName": display_name,
        "EXECUTABLE_NAME": exec_name,
        "PRODUCT_BUNDLE_IDENTIFIER": bundle_id,
        "MARKETING_VERSION": marketing_version,
        "CURRENT_PROJECT_VERSION": current_project_version,
        "IPHONEOS_DEPLOYMENT_TARGET": deployment_target,
        "SWIFT_VERSION": swift_version,
    }
    if sdk_root:
        context["SDKROOT"] = str(sdk_root)
    if cache_root:
        context["CACHEROOT"] = str(cache_root)
    if project_dir:
        context["PROJECT_DIR"] = str(project_dir)
    if target_build_dir:
        context["TARGET_BUILD_DIR"] = str(target_build_dir)
        context["BUILT_PRODUCTS_DIR"] = str(target_build_dir)

    return expand_macro_variables(config, context)
