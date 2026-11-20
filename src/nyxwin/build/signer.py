import os
import math
import subprocess
from pathlib import Path
from typing import Optional, Any
from nyxwin.core.models import Color, log_info, log_success, log_error, log_warning

def plist_deep_equal(a: Any, b: Any) -> bool:
    """
    Recursively compares two parsed plist data structures with strict type sensitivity.

    Standard Python equality evaluates True == 1, False == 0, and 1 == 1.0 as equal.
    This function enforces:
    1. Exact Python type matching (type(a) is type(b)) for all scalar and container types.
    2. Recursive dictionary comparison across all keys and values.
    3. Recursive array/list comparison preserving strict element order.
    4. Type-checked scalar equality for bool, int, float, str, bytes, and datetime objects.
    """
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        for k in a:
            if not plist_deep_equal(a[k], b[k]):
                return False
        return True
    if isinstance(a, (list, tuple)):
        if len(a) != len(b):
            return False
        for item_a, item_b in zip(a, b):
            if not plist_deep_equal(item_a, item_b):
                return False
        return True
    if isinstance(a, float) and math.isnan(a):
        return isinstance(b, float) and math.isnan(b)
    return a == b

def sign_binary(
    ldid_bin: Path,
    binary_path: Path,
    project_dir: Path,
    build_dir: Path,
    profile: str = "auto",
    verbose: bool = False,
    operation_callback: Optional[Any] = None
) -> bool:
    """
    Injects entitlements and ad-hoc signs Mach-O executables using ldid.exe.
    Supports 'auto' (project Config/Entitlements.plist), 'trollstore' (Jailbreak / TrollStore
    root entitlements), and 'sandboxed' (standard stock iOS sideloading).
    Note: Entitlement injection embeds keys in the binary signature via ldid, but does not
    guarantee runtime privilege authorization without OS-level CoreTrust or trustcache support.
    """
    import time
    import plistlib
    if not ldid_bin or not ldid_bin.is_file():
        log_warning("tools/ldid.exe not found; binary was not signed.")
        if operation_callback:
            operation_callback(
                tool="ldid",
                mode="none",
                input_binary=str(binary_path),
                entitlements_file=None,
                entitlements_keys=[],
                cmd=[],
                exit_code=0,
                elapsed=0.0,
                stdout="",
                stderr="ldid.exe not found",
                valid_signature=False
            )
        return True

    entitlements_to_use = None
    entitlements_keys = []
    entitlements_source = "Project configuration"
    distribution_status = "No Apple signing authorization"
    provisioning_status = "None"
    signing_method = "ldid (Ad-Hoc / Pseudo-Signing)"

    if profile.lower() == "sandboxed":
        sandboxed_plist = build_dir / "SandboxedEntitlements.plist"
        sandboxed_plist.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>get-task-allow</key>
	<true/>
</dict>
</plist>
""", encoding="utf-8")
        entitlements_to_use = sandboxed_plist
        entitlements_keys = ["get-task-allow"]
        entitlements_source = "Legacy preset (sandboxed)"
        log_info("Using legacy Sandboxed profile (Ad-hoc signing with get-task-allow)")
    elif profile.lower() == "trollstore":
        ts_plist = build_dir / "TrollStoreEntitlements.plist"
        ts_plist.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>platform-application</key>
	<true/>
	<key>com.apple.private.security.no-sandbox</key>
	<true/>
	<key>com.apple.private.security.no-container</key>
	<true/>
	<key>task_for_pid-allow</key>
	<true/>
	<key>get-task-allow</key>
	<true/>
</dict>
</plist>
""", encoding="utf-8")
        entitlements_to_use = ts_plist
        entitlements_keys = [
            "platform-application", "com.apple.private.security.no-sandbox",
            "com.apple.private.security.no-container", "task_for_pid-allow", "get-task-allow"
        ]
        entitlements_source = "Legacy preset (trollstore)"
        log_warning("Using legacy TrollStore profile. Note: Injected private keys require OS-level CoreTrust/trustcache support; runtime authorization is not guaranteed.")
    else:
        # Default: auto (authoritative resolution from project's Config/Entitlements.plist)
        from nyxwin.core.project import resolve_and_validate_project_entitlements
        ok, ent_path, keys, diag_msg = resolve_and_validate_project_entitlements(project_dir)
        if not ok:
            log_error(f"Entitlement validation failed: {diag_msg}")
            if operation_callback:
                operation_callback(
                    tool="ldid",
                    mode="none",
                    input_binary=str(binary_path),
                    entitlements_file=str(ent_path) if ent_path else None,
                    entitlements_keys=[],
                    entitlements_source="Project configuration",
                    distribution_status=distribution_status,
                    signing_method=signing_method,
                    cmd=[],
                    exit_code=1,
                    elapsed=0.0,
                    stdout="",
                    stderr=diag_msg,
                    valid_signature=False
                )
            return False

        entitlements_to_use = ent_path
        entitlements_keys = keys
        entitlements_source = "Project configuration"

        # Check if project contains privileged keys and log notification
        privileged = {"platform-application", "com.apple.private.security.no-sandbox", "com.apple.private.security.no-container", "task_for_pid-allow"} & set(keys)
        if privileged:
            log_info(f"Project entitlements contain privileged keys ({', '.join(sorted(privileged))}). Note: Runtime authorization is not guaranteed without OS exploit/trustcache.")
        else:
            log_info(f"Using project entitlements ({ent_path.name}) with {len(keys)} key(s)")

    if entitlements_to_use and entitlements_to_use.is_file():
        cmd_sign = [str(ldid_bin), f"-S{entitlements_to_use.resolve()}", binary_path.name]
    else:
        cmd_sign = [str(ldid_bin), "-s", binary_path.name]

    if verbose:
        print("  [CMD]", " ".join(cmd_sign))

    t0 = time.monotonic()
    proc = subprocess.run(cmd_sign, cwd=str(binary_path.parent), capture_output=True, text=True)
    elapsed = time.monotonic() - t0

    has_sig_structure = False
    try:
        with open(binary_path, "rb") as bf:
            bdata = bf.read()
            # 0x1D is LC_CODE_SIGNATURE command ID
            has_sig_structure = b"\x1d\x00\x00\x00" in bdata
    except Exception:
        has_sig_structure = False

    # Extract CodeDirectory hash using ldid -h (signature metadata only; not signature verification)
    cdhash = ""
    try:
        p_h = subprocess.run([str(ldid_bin), "-h", binary_path.name], cwd=str(binary_path.parent), capture_output=True, text=True)
        for line in p_h.stdout.splitlines():
            if line.startswith("CDHash="):
                cdhash = line.split("CDHash=", 1)[1].strip()
                break
    except Exception:
        pass

    cdhash_status = "Extracted" if cdhash else "Unavailable"

    # Load expected complete entitlement dictionary for deep value & type comparison
    expected_entitlements_dict = {}
    if entitlements_to_use and entitlements_to_use.is_file():
        try:
            with open(entitlements_to_use, "rb") as ef:
                expected_entitlements_dict = plistlib.load(ef)
        except Exception:
            expected_entitlements_dict = {}

    # Extract embedded entitlement payload using ldid -e and compare complete parsed plist
    entitlements_extracted = False
    extracted_keys = []
    entitlements_status = "Failed"
    try:
        p_e = subprocess.run([str(ldid_bin), "-e", binary_path.name], cwd=str(binary_path.parent), capture_output=True, text=True)
        if p_e.returncode == 0 and p_e.stdout.strip():
            ext_data = plistlib.loads(p_e.stdout.strip().encode("utf-8"))
            if isinstance(ext_data, dict):
                entitlements_extracted = True
                extracted_keys = list(ext_data.keys())
                # Recursive, type-sensitive comparison of complete plist structures
                if plist_deep_equal(ext_data, expected_entitlements_dict):
                    entitlements_status = "Extracted and compared"
                else:
                    entitlements_status = "Failed"
    except Exception:
        entitlements_status = "Failed"

    sig_structure_status = "Present" if has_sig_structure else "Missing"
    codedirectory_integrity = "Unsupported"  # No independent CodeDirectory integrity verifier in Windows toolchain
    apple_signer_identity = "Absent"         # Ad-hoc pseudo-signature has no Apple developer certificate
    apple_trust_chain = "Not applicable"     # No Apple certificate chain in ad-hoc signatures
    provisioning_auth = "Absent"             # No mobileprovision profile in ad-hoc builds
    crypto_status = "Signature verification unavailable (Ad-hoc pseudo-signature / No Apple Trustchain)"

    is_verified_sign = (proc.returncode == 0 and has_sig_structure and entitlements_status == "Extracted and compared")
    exit_code_reported = proc.returncode if is_verified_sign else (proc.returncode or 1)
    stderr_reported = proc.stderr
    if not is_verified_sign and entitlements_status != "Extracted and compared":
        err_msg = "Entitlement verification failed: extracted binary payload does not match source configuration."
        stderr_reported = f"{proc.stderr}\n{err_msg}".strip() if proc.stderr else err_msg
    elif not is_verified_sign and not has_sig_structure:
        err_msg = "Signature verification failed: LC_CODE_SIGNATURE command not found in binary."
        stderr_reported = f"{proc.stderr}\n{err_msg}".strip() if proc.stderr else err_msg

    if operation_callback:
        operation_callback(
            tool="ldid",
            mode=signing_method,
            input_binary=str(binary_path),
            entitlements_file=str(entitlements_to_use) if entitlements_to_use else None,
            entitlements_keys=entitlements_keys,
            entitlements_source=entitlements_source,
            provisioning_status=provisioning_status,
            distribution_status=distribution_status,
            signing_method=signing_method,
            cmd=cmd_sign,
            exit_code=exit_code_reported,
            elapsed=elapsed,
            stdout=proc.stdout,
            stderr=stderr_reported,
            signature_structure_present=has_sig_structure,
            signature_structure=sig_structure_status,
            cdhash=cdhash,
            cdhash_status=cdhash_status,
            entitlements_extracted=entitlements_extracted,
            extracted_keys=extracted_keys,
            entitlements_status=entitlements_status,
            codedirectory_integrity=codedirectory_integrity,
            apple_signer_identity=apple_signer_identity,
            apple_trust_chain=apple_trust_chain,
            provisioning_authorization=provisioning_auth,
            cryptographic_verification=crypto_status,
            valid_signature=is_verified_sign
        )

    if not is_verified_sign:
        if proc.returncode != 0:
            log_error(f"ldid signing failed: {proc.stderr}")
        elif not has_sig_structure:
            log_error("Signature verification failed: LC_CODE_SIGNATURE command not found in binary.")
        else:
            log_error("Entitlement verification failed: extracted binary payload does not match source configuration.")
        return False

    ent_desc = f"{entitlements_to_use.name} ({len(entitlements_keys)} keys)" if entitlements_to_use else "ad-hoc (empty)"
    log_success(f"Binary pseudo-signed with entitlements: {ent_desc}")
    return True

def sign_embedded_framework(ldid_bin: Path, framework_dir: Path) -> bool:
    """Signs inner dynamic binary of an embedded framework."""
    if not ldid_bin or not ldid_bin.is_file():
        return False
    inner_bin = framework_dir / framework_dir.stem
    if inner_bin.is_file():
        proc = subprocess.run([str(ldid_bin), "-s", inner_bin.name], cwd=str(framework_dir), capture_output=True)
        return proc.returncode == 0
    return False
