"""
Persistent Build Transcript, Text Log, and Structured JSON Build Report Module for NyxWin.
Captures comprehensive, verifiable build execution records for every build stage:
SCAN, COMPILE, LINK, PATCH, SIGN, and PACKAGE.

Stores persistent logs and JSON reports in NyxWin's canonical external data directory:
  %LOCALAPPDATA%\\NyxWin\\Logs\\builds\\<project>\\<build_id>.log
  %LOCALAPPDATA%\\NyxWin\\Logs\\builds\\<project>\\latest.log
  %LOCALAPPDATA%\\NyxWin\\Logs\\builds\\<project>\\<build_id>.json
  %LOCALAPPDATA%\\NyxWin\\Logs\\builds\\<project>\\build_report.json
"""

import os
import re
import sys
import time
import json
import hashlib
import platform
import threading
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import nyxwin
from nyxwin.config.paths import get_logs_root

BUILD_REPORT_SCHEMA_VERSION = "1.0"

_DEFAULT_STAGE_DEFINITIONS = [
    (1, "SCAN", "Discover Source Files"),
    (2, "COMPILE", "Compile Sources"),
    (3, "LINK", "Link Mach-O Executable"),
    (4, "PATCH", "Apply Header Patch #31"),
    (5, "SIGN", "Inject Entitlements & Codesign"),
    (6, "PACKAGE", "Package Application Bundle & .ipa"),
]

# Patterns for redacting accidental secrets, tokens, or credentials in logged strings
_SECRET_PATTERNS = [
    re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),
    re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{16,})\b"),
    re.compile(r"\b(github_pat_[A-Za-z0-9_]{16,})\b"),
    re.compile(
        r"((?:--|-)?(?:token|secret|password|passwd|api[-_]?key|auth[-_]?token|access[-_]?key)\s*[=:]\s*)([^\s\"']+)",
        re.IGNORECASE,
    ),
]


def redact_sensitive_text(text: Any) -> str:
    """Redacts authentication tokens, API keys, or secrets from log/report text."""
    if text is None:
        return ""
    s = str(text)
    if not s:
        return ""
    s = _SECRET_PATTERNS[0].sub(r"\1[REDACTED]", s)
    s = _SECRET_PATTERNS[1].sub("[REDACTED_GITHUB_TOKEN]", s)
    s = _SECRET_PATTERNS[2].sub("[REDACTED_GITHUB_TOKEN]", s)
    s = _SECRET_PATTERNS[3].sub(r"\1[REDACTED]", s)
    return s


def format_command_line(cmd: List[str]) -> str:
    """Formats a command argument list safely for logs, quoting arguments with spaces."""
    if not cmd:
        return ""
    cleaned = [redact_sensitive_text(str(arg)) for arg in cmd]
    try:
        return subprocess.list2cmdline(cleaned)
    except Exception:
        return " ".join(f'"{c}"' if " " in c else c for c in cleaned)


def _atomic_write_text(dest_path: Path, content: str) -> None:
    """
    Atomically writes UTF-8 text to `dest_path` using a temporary sibling file,
    explicit flush/fsync, and `os.replace()`. Ensures partial or interrupted writes
    never leave a truncated or malformed log/report at `dest_path`.
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = f".{dest_path.name}.tmp.{os.getpid()}.{threading.get_ident()}"
    tmp_path = dest_path.parent / tmp_name
    try:
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp_path, dest_path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


def _compute_sha256_safe(file_path: Optional[Path]) -> Optional[str]:
    """Computes SHA-256 hex digest of a file if it exists, or returns None."""
    if not file_path:
        return None
    p = Path(file_path)
    if not p.is_file():
        return None
    try:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


class BuildTranscript:
    """Records real subprocess executions, arguments, exit statuses, outputs, and validation."""

    def __init__(
        self,
        project_name: str,
        project_dir: Path,
        target_triple: str,
        deployment_target: str,
        profile: str,
        toolchain: Any,
        product_name: Optional[str] = None,
        display_name: Optional[str] = None,
        executable_name: Optional[str] = None,
        bundle_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ):
        self._lock = threading.RLock()
        self.project_name = str(project_name)
        self.product_name = str(product_name or project_name)
        self.display_name = str(display_name or project_name)
        self.executable_name = str(executable_name or self.product_name)
        self.bundle_id = str(bundle_id) if bundle_id else None
        self.project_id = str(project_id) if project_id else None
        self.project_dir = Path(project_dir).resolve()
        self.target_triple = str(target_triple)
        self.deployment_target = str(deployment_target)
        self.profile = str(profile)

        self.start_wall_time = datetime.now()
        self.start_utc_time = datetime.now(timezone.utc)
        self.end_wall_time: Optional[datetime] = None
        self.end_utc_time: Optional[datetime] = None
        self.start_mono_time = time.monotonic()
        timestamp_str = self.start_wall_time.strftime("%Y%m%d_%H%M%S")
        short_id = f"{int(self.start_mono_time * 1000) % 1000000:06d}"
        self.build_id = f"build_{timestamp_str}_{short_id}"

        # Host and Toolchain metadata
        self.nyxwin_version = getattr(nyxwin, "__version__", "1.1.0")
        self.python_version = sys.version.replace("\n", " ")
        self.host_platform = f"{platform.system()} {platform.release()} ({platform.machine()})"

        raw_sdk = getattr(toolchain, "sdk_dir", None) if toolchain else None
        raw_clang = getattr(toolchain, "clang", None) if toolchain else None
        raw_swiftc = getattr(toolchain, "swiftc", None) if toolchain else None
        raw_ld64 = (getattr(toolchain, "ld64", None) or getattr(toolchain, "lld", None)) if toolchain else None
        raw_ldid = getattr(toolchain, "ldid", None) if toolchain else None

        self.sdk_dir = str(raw_sdk) if raw_sdk else "None"
        self.clang_bin = str(raw_clang) if raw_clang else "None"
        self.swiftc_bin = str(raw_swiftc) if raw_swiftc else "None"
        self.ld64_bin = str(raw_ld64) if raw_ld64 else "None"
        self.ldid_bin = str(raw_ldid) if raw_ldid else "None"

        # Parse SDK identity and version when available
        self.sdk_name: Optional[str] = None
        self.sdk_version: Optional[str] = None
        if raw_sdk and str(raw_sdk) != "None":
            sdk_p = Path(str(raw_sdk))
            self.sdk_name = sdk_p.name
            m_ver = re.search(r"iPhoneOS([0-9]+(?:\.[0-9]+)*)\.sdk", sdk_p.name, re.IGNORECASE)
            if m_ver:
                self.sdk_version = m_ver.group(1)

        # Stage execution records
        self.scan_record: Dict[str, Any] = {}
        self.compile_records: List[Dict[str, Any]] = []
        self.link_record: Dict[str, Any] = {}
        self.patch_record: Dict[str, Any] = {}
        self.sign_record: Dict[str, Any] = {}
        self.package_record: Dict[str, Any] = {}
        self.stage_summaries: List[Dict[str, Any]] = [
            {
                "index": idx,
                "id": stg_id,
                "name": stg_name,
                "status": "pending",
                "duration_seconds": 0.0,
                "detail": "",
            }
            for idx, stg_id, stg_name in _DEFAULT_STAGE_DEFINITIONS
        ]

        self.warnings: List[str] = []
        self.errors: List[str] = []
        self.status: str = "in_progress"  # "succeeded", "failed", "cancelled"
        self.is_success = False
        self.is_cancelled = False
        self.failure_stage = 0
        self.failure_reason = ""
        self.cancellation_info: Optional[Dict[str, Any]] = None
        self.cleanup_record: Optional[Dict[str, Any]] = None
        self.persistence_errors: List[str] = []
        self.persistence_warnings: List[str] = []
        self.persisted_files: Dict[str, bool] = {
            "build_log": False,
            "latest_log": False,
            "build_report": False,
            "latest_report": False,
        }
        self._in_persistence: bool = False
        self.total_duration = 0.0
        self.log_path: Optional[Path] = None
        self.report_path: Optional[Path] = None
        self._finalized: bool = False

    def sync_from_tracker(self, tracker: Any) -> None:
        """Synchronizes stage statuses, durations, warnings, and errors from BuildProgressTracker."""
        if tracker is None:
            return
        with self._lock:
            tracker_stages = getattr(tracker, "stages", None)
            if tracker_stages:
                synced_stages: List[Dict[str, Any]] = []
                now_mono = time.monotonic()
                for s in tracker_stages:
                    started = float(getattr(s, "started_at", 0.0) or 0.0)
                    completed = float(getattr(s, "completed_at", 0.0) or 0.0)
                    st_status = str(getattr(s, "status", "pending"))
                    if started > 0.0 and completed >= started:
                        dur = round(completed - started, 3)
                    elif started > 0.0 and st_status in ("in_progress", "failed", "cancelled"):
                        dur = round(max(0.0, now_mono - started), 3)
                    else:
                        dur = 0.0
                    synced_stages.append({
                        "index": int(getattr(s, "index", 0)),
                        "id": str(getattr(s, "label", "")),
                        "name": str(getattr(s, "name", "")),
                        "status": st_status,
                        "duration_seconds": dur,
                        "detail": redact_sensitive_text(getattr(s, "detail", "")),
                    })
                self.stage_summaries = synced_stages

            for w in getattr(tracker, "warnings", []) or []:
                w_str = redact_sensitive_text(getattr(w, "raw_text", str(w))).strip()
                if w_str and w_str not in self.warnings:
                    self.warnings.append(w_str)

            for e in getattr(tracker, "errors", []) or []:
                e_str = redact_sensitive_text(str(e)).strip()
                if e_str and e_str not in self.errors:
                    self.errors.append(e_str)

    def record_scan(self, c_sources: List[Path], swift_sources: List[Path], excluded_dirs: List[str]):
        """Records source discovery details."""
        with self._lock:
            c_items = []
            for s in c_sources:
                sz = s.stat().st_size if s.is_file() else 0
                rel = str(s.relative_to(self.project_dir)) if s.is_relative_to(self.project_dir) else s.name
                c_items.append({"file": rel, "size": sz, "kind": "C/ObjC/C++"})

            swift_items = []
            for s in swift_sources:
                sz = s.stat().st_size if s.is_file() else 0
                rel = str(s.relative_to(self.project_dir)) if s.is_relative_to(self.project_dir) else s.name
                swift_items.append({"file": rel, "size": sz, "kind": "Swift"})

            self.scan_record = {
                "c_sources": c_items,
                "swift_sources": swift_items,
                "total_count": len(c_items) + len(swift_items),
                "excluded_dirs": list(excluded_dirs),
            }

    def record_compile(
        self,
        tool: str,
        input_file: str,
        output_file: str,
        cmd: List[str],
        exit_code: int,
        elapsed: float,
        cached: bool = False,
        stdout: str = "",
        stderr: str = "",
        output_valid: bool = True,
        output_size: int = 0,
        cwd: Optional[str] = None,
        **kwargs,
    ):
        """Records an individual compilation step (thread-safe across parallel workers)."""
        with self._lock:
            clean_cmd = [redact_sensitive_text(str(c)) for c in cmd]
            clean_stdout = redact_sensitive_text(stdout).strip()
            clean_stderr = redact_sensitive_text(stderr).strip()
            rec = {
                "tool": tool,
                "input_file": input_file,
                "output_file": output_file,
                "cmd": clean_cmd,
                "cwd": str(cwd or self.project_dir),
                "exit_code": exit_code,
                "elapsed": round(elapsed, 3),
                "cached": cached,
                "stdout": clean_stdout,
                "stderr": clean_stderr,
                "output_valid": output_valid,
                "output_size": output_size,
            }
            self.compile_records.append(rec)
            if clean_stderr and exit_code == 0:
                msg = f"[{tool}] {input_file}: {clean_stderr}"
                if msg not in self.warnings:
                    self.warnings.append(msg)
            elif exit_code != 0:
                msg = f"[{tool}] {input_file} failed with exit code {exit_code}: {clean_stderr}"
                if msg not in self.errors:
                    self.errors.append(msg)

    def record_link(
        self,
        tool: str,
        object_files: List[str],
        frameworks: List[str],
        libraries: List[str],
        output_binary: str,
        cmd: List[str],
        exit_code: int,
        elapsed: float,
        stdout: str = "",
        stderr: str = "",
        output_valid: bool = True,
        output_size: int = 0,
        macho_header: Optional[Dict[str, Any]] = None,
        cwd: Optional[str] = None,
        **kwargs,
    ):
        """Records Darwin Mach-O linking operation."""
        with self._lock:
            clean_cmd = [redact_sensitive_text(str(c)) for c in cmd]
            clean_stdout = redact_sensitive_text(stdout).strip()
            clean_stderr = redact_sensitive_text(stderr).strip()
            self.link_record = {
                "tool": tool,
                "object_files": list(object_files),
                "frameworks": list(frameworks),
                "libraries": list(libraries),
                "output_binary": output_binary,
                "cmd": clean_cmd,
                "cwd": str(cwd or self.project_dir),
                "exit_code": exit_code,
                "elapsed": round(elapsed, 3),
                "stdout": clean_stdout,
                "stderr": clean_stderr,
                "output_valid": output_valid,
                "output_size": output_size,
                "macho_header": macho_header or {},
            }
            if clean_stderr and exit_code == 0:
                msg = f"[linker] {clean_stderr}"
                if msg not in self.warnings:
                    self.warnings.append(msg)
            elif exit_code != 0:
                msg = f"[linker] failed with exit code {exit_code}: {clean_stderr}"
                if msg not in self.errors:
                    self.errors.append(msg)

    def record_patch(self, operation: str, target: str, applied: bool, details: str):
        """Records Mach-O Patch #31 operation."""
        with self._lock:
            self.patch_record = {
                "operation": operation,
                "target": target,
                "applied": applied,
                "details": details,
            }

    def record_sign(
        self,
        tool: str,
        mode: str,
        input_binary: str,
        entitlements_file: Optional[str],
        entitlements_keys: List[str],
        cmd: List[str],
        exit_code: int,
        elapsed: float,
        stdout: str = "",
        stderr: str = "",
        valid_signature: bool = True,
        **kwargs,
    ):
        """Records code signing and entitlement injection operation."""
        with self._lock:
            sig_struct_pres = kwargs.get("signature_structure_present", valid_signature)
            cdh = kwargs.get("cdhash", "")
            ext_ok = kwargs.get("entitlements_extracted", False)
            ext_keys = kwargs.get("extracted_keys", [])
            clean_cmd = [redact_sensitive_text(str(c)) for c in cmd]
            clean_stdout = redact_sensitive_text(stdout).strip()
            clean_stderr = redact_sensitive_text(stderr).strip()
            in_bin_parent = str(Path(input_binary).parent) if input_binary else str(self.project_dir)
            self.sign_record = {
                "tool": tool,
                "mode": mode,
                "input_binary": input_binary,
                "entitlements_file": entitlements_file,
                "entitlements_keys": list(entitlements_keys),
                "entitlements_source": kwargs.get("entitlements_source", "Project configuration"),
                "provisioning_status": kwargs.get("provisioning_status", "None"),
                "distribution_status": kwargs.get("distribution_status", "No Apple signing authorization"),
                "signing_method": kwargs.get("signing_method", mode),
                "signature_structure_present": sig_struct_pres,
                "signature_structure": kwargs.get("signature_structure", "Present" if sig_struct_pres else "Missing"),
                "cdhash": cdh,
                "cdhash_status": kwargs.get("cdhash_status", "Extracted" if cdh else "Unavailable"),
                "entitlements_extracted": ext_ok,
                "extracted_keys": ext_keys,
                "entitlements_status": kwargs.get("entitlements_status", "Extracted and compared" if ext_ok else "Failed"),
                "codedirectory_integrity": kwargs.get("codedirectory_integrity", "Unsupported"),
                "apple_signer_identity": kwargs.get("apple_signer_identity", "Absent"),
                "apple_trust_chain": kwargs.get("apple_trust_chain", "Not applicable"),
                "provisioning_authorization": kwargs.get("provisioning_authorization", "Absent"),
                "cryptographic_verification": kwargs.get(
                    "cryptographic_verification",
                    "Signature verification unavailable (Ad-hoc pseudo-signature / No Apple Trustchain)",
                ),
                "cmd": clean_cmd,
                "cwd": kwargs.get("cwd", in_bin_parent),
                "exit_code": exit_code,
                "elapsed": round(elapsed, 3),
                "stdout": clean_stdout,
                "stderr": clean_stderr,
                "valid_signature": valid_signature,
            }
            if exit_code != 0:
                msg = f"[signer] {tool} failed with exit code {exit_code}: {clean_stderr}"
                if msg not in self.errors:
                    self.errors.append(msg)

    def record_package(
        self,
        operation: str,
        app_bundle_dir: str,
        files_included: List[str],
        ipa_path: str,
        ipa_size: int,
        is_valid_zip: bool,
        info_plist_summary: Dict[str, Any],
        elapsed: float,
        ipa_sha256: Optional[str] = None,
        **kwargs,
    ):
        """Records application bundle and IPA package creation."""
        with self._lock:
            computed_sha = ipa_sha256 or _compute_sha256_safe(Path(ipa_path) if ipa_path else None)
            self.package_record = {
                "operation": operation,
                "app_bundle_dir": app_bundle_dir,
                "files_included": list(files_included),
                "ipa_path": ipa_path,
                "ipa_size": ipa_size,
                "ipa_sha256": computed_sha,
                "is_valid_zip": is_valid_zip,
                "info_plist_summary": info_plist_summary,
                "elapsed": round(elapsed, 3),
            }

    def record_cleanup(
        self,
        attempted: bool,
        completed: bool,
        status: str,
        active_processes_remaining: int,
        unreaped_pids: Optional[List[int]] = None,
        error: Optional[str] = None,
        telemetry: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Records process-tree cleanup outcome, diagnostics, and reaping telemetry."""
        with self._lock:
            clean_error = redact_sensitive_text(str(error)).strip() if error else None
            self.cleanup_record = {
                "attempted": bool(attempted),
                "completed": bool(completed),
                "status": str(status),
                "active_processes_remaining": int(active_processes_remaining),
                "unreaped_pids": list(unreaped_pids or []),
                "error": clean_error,
                "telemetry": dict(telemetry or {}),
            }
            if status == "warning" and clean_error:
                warn_msg = f"[cleanup] {clean_error}"
                if warn_msg not in self.warnings:
                    self.warnings.append(warn_msg)
            elif status == "failed":
                fail_msg = clean_error or f"{active_processes_remaining} build-owned process(es) remained active after cleanup"
                err_msg = f"[cleanup] {fail_msg}"
                if err_msg not in self.errors:
                    self.errors.append(err_msg)

            # If already finalized, refresh persisted files atomically
            if self._finalized and self.log_path and self.report_path:
                if status == "failed":
                    self.is_success = False
                    self.status = "failed"
                try:
                    write_results = self._write_persisted_files()
                    if not all(write_results.values()):
                        unwritten = [k for k, v in write_results.items() if not v]
                        warn_msg = f"Persistent report refresh incomplete (unwritten: {', '.join(unwritten)})"
                        if warn_msg not in self.persistence_warnings:
                            self.persistence_warnings.append(warn_msg)
                        if warn_msg not in self.warnings:
                            self.warnings.append(warn_msg)
                except Exception as ex:
                    err_msg = f"Persistence refresh error: {ex}"
                    if err_msg not in self.persistence_errors:
                        self.persistence_errors.append(err_msg)
                    if err_msg not in self.warnings:
                        self.warnings.append(err_msg)
                    sys.stderr.write(f"[NyxWin Warning] {err_msg}\n")

    def finalize(
        self,
        is_success: bool,
        failure_stage: int = 0,
        failure_reason: str = "",
        cancelled: bool = False,
        cancellation_info: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """
        Finalizes the build record, formats the persistent plain-text build log and
        structured JSON report (`<build_id>.json` and `build_report.json`), and writes
        them atomically to NyxWin's external Logs directory.
        Subsequent calls are idempotent and return the existing log path without
        overwriting finalized records or recomputing timestamps.
        """
        with self._lock:
            if self._finalized:
                return self.log_path or (get_logs_root() / "builds" / self._sanitize_filename(self.project_name) / f"{self.build_id}.log")

            self.total_duration = round(max(0.0, time.monotonic() - self.start_mono_time), 2)
            self.end_wall_time = datetime.now()
            self.end_utc_time = datetime.now(timezone.utc)
            self.is_cancelled = bool(cancelled)
            self.is_success = bool(is_success and not cancelled)
            self.status = "cancelled" if self.is_cancelled else ("succeeded" if self.is_success else "failed")
            self.failure_stage = int(failure_stage or 0)
            self.failure_reason = redact_sensitive_text(failure_reason)
            if cancellation_info is not None:
                self.cancellation_info = dict(cancellation_info)
            elif self.is_cancelled and self.cancellation_info is None:
                self.cancellation_info = {
                    "cancelled": True,
                    "reason": self.failure_reason or "Build cancelled by user",
                    "stage_index": self.failure_stage,
                }

            if not self.is_success and self.failure_reason:
                if self.failure_reason not in self.errors and not self.is_cancelled:
                    self.errors.append(self.failure_reason)

            # Update stage summaries if not already populated from tracker
            self._reconcile_stage_summaries()

            logs_root = get_logs_root() / "builds" / self._sanitize_filename(self.project_name)
            logs_root.mkdir(parents=True, exist_ok=True)

            log_file = logs_root / f"{self.build_id}.log"
            latest_log_file = logs_root / "latest.log"
            report_id_file = logs_root / f"{self.build_id}.json"
            canonical_report_file = logs_root / "build_report.json"

            self.log_path = log_file
            self.report_path = canonical_report_file

            self._write_persisted_files()
            self._finalized = True
            return log_file

    def _write_persisted_files(self) -> Dict[str, bool]:
        """
        Atomically formats and writes the build log and JSON report files.
        Differentiates primary unique files (<build_id>.log, <build_id>.json)
        from convenience aliases (latest.log, build_report.json).
        Captures and exposes persistence errors and warnings; guards against recursion.
        """
        if not self.log_path or not self.report_path:
            return dict(self.persisted_files)
        if self._in_persistence:
            return dict(self.persisted_files)

        self._in_persistence = True
        try:
            logs_root = self.log_path.parent
            latest_log_file = logs_root / "latest.log"
            report_id_file = logs_root / f"{self.build_id}.json"
            canonical_report_file = self.report_path

            # 1. Primary Unique Build Log (<build_id>.log)
            transcript_text = self._generate_transcript_text()
            try:
                _atomic_write_text(self.log_path, transcript_text)
                self.persisted_files["build_log"] = True
            except Exception as ex:
                self.persisted_files["build_log"] = False
                err_msg = f"Failed to write primary build log ({self.log_path.name}): {ex}"
                if err_msg not in self.persistence_errors:
                    self.persistence_errors.append(err_msg)
                sys.stderr.write(f"[NyxWin Error] {err_msg}\n")

            # 2. Convenience Alias (latest.log)
            try:
                _atomic_write_text(latest_log_file, transcript_text)
                self.persisted_files["latest_log"] = True
            except Exception as ex:
                self.persisted_files["latest_log"] = False
                warn_msg = f"Failed to update latest.log alias: {ex}"
                if warn_msg not in self.persistence_warnings:
                    self.persistence_warnings.append(warn_msg)
                sys.stderr.write(f"[NyxWin Warning] {warn_msg}\n")

            # 3. Primary Unique Build Report (<build_id>.json)
            report_dict = self.to_report_dict()
            report_json = ""
            try:
                report_json = json.dumps(report_dict, indent=2, ensure_ascii=False) + "\n"
                _atomic_write_text(report_id_file, report_json)
                self.persisted_files["build_report"] = True
            except Exception as ex:
                self.persisted_files["build_report"] = False
                err_msg = f"Failed to write primary build report ({report_id_file.name}): {ex}"
                if err_msg not in self.persistence_errors:
                    self.persistence_errors.append(err_msg)
                sys.stderr.write(f"[NyxWin Error] {err_msg}\n")

            # 4. Convenience Alias (build_report.json)
            if report_json:
                try:
                    _atomic_write_text(canonical_report_file, report_json)
                    self.persisted_files["latest_report"] = True
                except Exception as ex:
                    self.persisted_files["latest_report"] = False
                    warn_msg = f"Failed to update canonical build_report.json alias: {ex}"
                    if warn_msg not in self.persistence_warnings:
                        self.persistence_warnings.append(warn_msg)
                    sys.stderr.write(f"[NyxWin Warning] {warn_msg}\n")

            return dict(self.persisted_files)
        finally:
            self._in_persistence = False

    def _reconcile_stage_summaries(self) -> None:
        """Ensures stage_summaries accurately reflect recorded stage results when finalized."""
        has_tracker_status = any(s.get("status") != "pending" for s in self.stage_summaries)
        if not has_tracker_status:
            stage_presence = {
                1: bool(self.scan_record),
                2: bool(self.compile_records),
                3: bool(self.link_record),
                4: bool(self.patch_record),
                5: bool(self.sign_record),
                6: bool(self.package_record),
            }
            for s in self.stage_summaries:
                idx = s["index"]
                if self.is_success:
                    s["status"] = "completed" if stage_presence.get(idx) else "skipped"
                elif self.failure_stage and idx == self.failure_stage:
                    s["status"] = "cancelled" if self.is_cancelled else "failed"
                    if not s.get("detail") and self.failure_reason:
                        s["detail"] = self.failure_reason
                elif self.failure_stage and idx < self.failure_stage:
                    s["status"] = "completed"
                elif stage_presence.get(idx):
                    s["status"] = "completed"
                else:
                    s["status"] = "pending"
        else:
            if self.is_cancelled and self.failure_stage:
                for s in self.stage_summaries:
                    if s["index"] == self.failure_stage and s["status"] in ("in_progress", "failed", "pending"):
                        s["status"] = "cancelled"
                        if self.failure_reason:
                            s["detail"] = self.failure_reason

        # Backfill stage durations from recorded operations when stage timer was 0.0
        for s in self.stage_summaries:
            if s.get("duration_seconds", 0.0) <= 0.0:
                idx = s["index"]
                if idx == 2 and self.compile_records:
                    s["duration_seconds"] = round(sum(float(r.get("elapsed", 0.0)) for r in self.compile_records), 3)
                elif idx == 3 and self.link_record:
                    s["duration_seconds"] = round(float(self.link_record.get("elapsed", 0.0)), 3)
                elif idx == 5 and self.sign_record:
                    s["duration_seconds"] = round(float(self.sign_record.get("elapsed", 0.0)), 3)
                elif idx == 6 and self.package_record:
                    s["duration_seconds"] = round(float(self.package_record.get("elapsed", 0.0)), 3)

    def to_report_dict(self) -> Dict[str, Any]:
        """Constructs the versioned, structured JSON build report dictionary."""
        with self._lock:
            arch = self.target_triple.split("-")[0] if "-" in self.target_triple else "arm64"
            started_iso = self.start_utc_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            finished_iso = (
                self.end_utc_time.strftime("%Y-%m-%dT%H:%M:%SZ")
                if self.end_utc_time
                else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            )

            ipa_path_str = self.package_record.get("ipa_path") if self.package_record else None
            ipa_path_obj = Path(ipa_path_str) if ipa_path_str else None
            ipa_exists = bool(ipa_path_obj and ipa_path_obj.is_file())
            ipa_size = (
                int(self.package_record.get("ipa_size", 0))
                if (self.package_record and ipa_exists)
                else (ipa_path_obj.stat().st_size if ipa_exists and ipa_path_obj else None)
            )
            ipa_sha256 = (
                self.package_record.get("ipa_sha256")
                if (self.package_record and self.package_record.get("ipa_sha256"))
                else (_compute_sha256_safe(ipa_path_obj) if ipa_exists else None)
            )

            def _tool_entry(path_str: str) -> Dict[str, Optional[str]]:
                if not path_str or path_str == "None":
                    return {"executable": None, "path": None}
                p = Path(path_str)
                return {"executable": p.name, "path": str(p)}

            # Collect process exit codes summary
            process_exit_codes: List[Dict[str, Any]] = []
            for cr in self.compile_records:
                if not cr.get("cached"):
                    process_exit_codes.append({
                        "stage": "COMPILE",
                        "tool": cr.get("tool"),
                        "target": cr.get("input_file"),
                        "exit_code": int(cr.get("exit_code", 0)),
                    })
            if self.link_record:
                process_exit_codes.append({
                    "stage": "LINK",
                    "tool": self.link_record.get("tool"),
                    "target": Path(str(self.link_record.get("output_binary", ""))).name,
                    "exit_code": int(self.link_record.get("exit_code", 0)),
                })
            if self.sign_record and self.sign_record.get("cmd"):
                process_exit_codes.append({
                    "stage": "SIGN",
                    "tool": self.sign_record.get("tool"),
                    "target": Path(str(self.sign_record.get("input_binary", ""))).name,
                    "exit_code": int(self.sign_record.get("exit_code", 0)),
                })

            return {
                "schema_version": BUILD_REPORT_SCHEMA_VERSION,
                "build_id": self.build_id,
                "status": self.status,
                "is_success": self.is_success,
                "is_cancelled": self.is_cancelled,
                "project": {
                    "project_id": self.project_id,
                    "project_name": self.project_name,
                    "product_name": self.product_name,
                    "display_name": self.display_name,
                    "executable_name": self.executable_name,
                    "bundle_identifier": self.bundle_id,
                    "project_dir": str(self.project_dir),
                    "profile": self.profile,
                },
                "target": {
                    "architecture": arch,
                    "platform": "iphoneos",
                    "target_triple": self.target_triple,
                    "deployment_target": self.deployment_target,
                },
                "sdk": {
                    "name": self.sdk_name,
                    "version": self.sdk_version,
                    "path": self.sdk_dir if self.sdk_dir != "None" else None,
                },
                "timestamps": {
                    "started_at": started_iso,
                    "finished_at": finished_iso,
                    "duration_seconds": float(self.total_duration),
                },
                "toolchain": {
                    "nyxwin_version": self.nyxwin_version,
                    "tools": {
                        "clang": _tool_entry(self.clang_bin),
                        "swiftc": _tool_entry(self.swiftc_bin),
                        "linker": _tool_entry(self.ld64_bin),
                        "ldid": _tool_entry(self.ldid_bin),
                    },
                },
                "stages": list(self.stage_summaries),
                "stage_records": {
                    "scan": dict(self.scan_record) if self.scan_record else None,
                    "compile": list(self.compile_records),
                    "link": dict(self.link_record) if self.link_record else None,
                    "patch": dict(self.patch_record) if self.patch_record else None,
                    "sign": dict(self.sign_record) if self.sign_record else None,
                    "package": dict(self.package_record) if self.package_record else None,
                },
                "process_exit_codes": process_exit_codes,
                "diagnostics": {
                    "warning_count": len(self.warnings),
                    "error_count": len(self.errors),
                    "warnings": list(self.warnings),
                    "errors": list(self.errors),
                    "failure_stage": self.failure_stage if not self.is_success else None,
                    "failure_reason": self.failure_reason if not self.is_success else None,
                },
                "artifacts": {
                    "binary_path": self.link_record.get("output_binary") if self.link_record else None,
                    "app_bundle_path": self.package_record.get("app_bundle_dir") if self.package_record else None,
                    "ipa_path": ipa_path_str if ipa_exists else None,
                    "ipa_exists": ipa_exists,
                    "ipa_size_bytes": ipa_size,
                    "ipa_sha256": ipa_sha256,
                    "log_path": str(self.log_path) if self.log_path else None,
                    "report_path": str(self.report_path) if self.report_path else None,
                },
                "cancellation": dict(self.cancellation_info) if self.cancellation_info else None,
                "cleanup": dict(self.cleanup_record) if self.cleanup_record else {
                    "attempted": False,
                    "completed": False,
                    "status": "not_attempted",
                    "active_processes_remaining": 0,
                    "unreaped_pids": [],
                    "error": None,
                    "telemetry": {},
                },
                "persistence": {
                    "synchronized": all(self.persisted_files.values()) if any(self.persisted_files.values()) else False,
                    "files": dict(self.persisted_files),
                    "warnings": list(self.persistence_warnings),
                    "errors": list(self.persistence_errors),
                },
            }

    def _sanitize_filename(self, name: str) -> str:
        return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name)

    def format_transcript(self) -> str:
        """Public method returning the formatted build transcript text."""
        with self._lock:
            return self._generate_transcript_text()

    def _generate_transcript_text(self) -> str:
        """Generates structured, verifiable plain-text transcript."""
        if self.is_cancelled:
            status_str = f"BUILD CANCELLED (Stage {self.failure_stage}: {self.failure_reason})"
        elif self.is_success:
            status_str = "BUILD SUCCEEDED"
        else:
            status_str = f"BUILD FAILED (Stage {self.failure_stage}: {self.failure_reason})"

        finish_ts_str = (
            self.end_wall_time.strftime("%Y-%m-%d %H:%M:%S")
            if self.end_wall_time
            else "In progress"
        )

        lines = [
            "=" * 80,
            "NYXWIN NATIVE IOS BUILD TRANSCRIPT",
            "=" * 80,
            f"Build ID:          {self.build_id}",
            f"Project Name:      {self.project_name}",
            f"Product Name:      {self.product_name}",
            f"Display Name:      {self.display_name}",
            f"Project Directory: {self.project_dir}",
            f"Timestamp:         {self.start_wall_time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Finished At:       {finish_ts_str}",
            f"Final Status:      {status_str}",
            f"Total Duration:    {self.total_duration:.2f}s",
            f"NyxWin Version:    {self.nyxwin_version}",
            f"Python Runtime:    {self.python_version}",
            f"Host Platform:     {self.host_platform}",
            "",
            "--- TOOLCHAIN & CONFIGURATION ---",
            f"Target Triple:     {self.target_triple}",
            f"Deployment Target: iOS {self.deployment_target}",
            f"Entitlement Mode:  {self.profile.capitalize()} ({'Jailbreak/TrollStore Entitlements' if self.profile.lower() == 'trollstore' else 'Standard Sandbox' if self.profile.lower() == 'sandboxed' else 'Project Config'})",
            f"Active iOS SDK:    {self.sdk_dir}",
            f"Clang Executable:  {self.clang_bin}",
            f"Swiftc Executable: {self.swiftc_bin}",
            f"Linker Executable: {self.ld64_bin}",
            f"ldid Executable:   {self.ldid_bin}",
            "=" * 80,
            "",
        ]

        # STAGE 1: SCAN
        lines.append("[STAGE 1: SCAN — SOURCE DISCOVERY]")
        if self.scan_record:
            total_srcs = self.scan_record.get("total_count", 0)
            c_srcs = self.scan_record.get("c_sources", [])
            s_srcs = self.scan_record.get("swift_sources", [])
            lines.append(f"  Discovered Sources: {total_srcs} ({len(c_srcs)} C/ObjC/C++, {len(s_srcs)} Swift)")
            for item in c_srcs:
                lines.append(f"    • {item['file']} ({item['size']:,} bytes) [{item['kind']}]")
            for item in s_srcs:
                lines.append(f"    • {item['file']} ({item['size']:,} bytes) [{item['kind']}]")
            excl = self.scan_record.get("excluded_dirs", [])
            if excl:
                lines.append(f"  Excluded Directories: {', '.join(excl)}")
        else:
            lines.append("  No scan records captured.")
        lines.append("")

        # STAGE 2: COMPILE
        lines.append("[STAGE 2: COMPILE — MULTI-THREADED COMPILATION]")
        if self.compile_records:
            lines.append(f"  Executed/Cached Compilations: {len(self.compile_records)}")
            for idx, cr in enumerate(self.compile_records, 1):
                cached_tag = " [CACHED]" if cr.get("cached") else ""
                lines.append(f"  [{idx:2d}] {cr['tool']} {cr['input_file']} -> {cr['output_file']}{cached_tag}")
                lines.append(f"       Working Dir: {cr.get('cwd', self.project_dir)}")
                lines.append(f"       Command:   {format_command_line(cr['cmd'])}")
                lines.append(f"       Exit Code: {cr['exit_code']} (Duration: {cr['elapsed']}s)")
                valid_str = f"VALID ({cr['output_size']:,} bytes)" if cr.get("output_valid") else "INVALID/MISSING"
                lines.append(f"       Output:    {cr['output_file']} -> {valid_str}")
                if cr.get("stdout"):
                    lines.append(f"       Stdout:\n         {cr['stdout']}")
                if cr.get("stderr"):
                    lines.append(f"       Stderr / Diagnostics:\n         {cr['stderr']}")
        else:
            lines.append("  No compilation commands were executed.")
        lines.append("")

        # STAGE 3: LINK
        lines.append("[STAGE 3: LINK — DARWIN MACH-O LINKING]")
        if self.link_record:
            lr = self.link_record
            lines.append(f"  Tool:          {lr.get('tool', 'ld64.lld')}")
            lines.append(f"  Working Dir:   {lr.get('cwd', self.project_dir)}")
            lines.append(f"  Command:       {format_command_line(lr.get('cmd', []))}")
            lines.append(f"  Object Inputs: {len(lr.get('object_files', []))} object(s)")
            for obj in lr.get("object_files", []):
                lines.append(f"    • {Path(obj).name}")
            lines.append(f"  Frameworks:    {', '.join(lr.get('frameworks', [])) or 'None'}")
            lines.append(f"  Libraries:     {', '.join(lr.get('libraries', [])) or 'None'}")
            lines.append(f"  Output Binary: {lr.get('output_binary')}")
            lines.append(f"  Exit Code:     {lr.get('exit_code')} (Duration: {lr.get('elapsed')}s)")
            hdr = lr.get("macho_header", {})
            hdr_str = (
                f"Magic={hdr.get('magic_hex', '0xFEEDFACF')} ({hdr.get('arch', 'ARM64')}), Type={hdr.get('filetype', 'MH_EXECUTE')}"
                if hdr
                else "Valid Mach-O"
            )
            valid_str = f"VALID ({lr.get('output_size', 0):,} bytes, {hdr_str})" if lr.get("output_valid") else "INVALID/MISSING"
            lines.append(f"  Validation:    {valid_str}")
            if lr.get("stdout"):
                lines.append(f"  Stdout:        {lr.get('stdout')}")
            if lr.get("stderr"):
                lines.append(f"  Diagnostics:   {lr.get('stderr')}")
        else:
            lines.append("  Linker stage was not executed.")
        lines.append("")

        # STAGE 4: PATCH
        lines.append("[STAGE 4: PATCH — MACH-O PATCH #31]")
        if self.patch_record:
            pr = self.patch_record
            lines.append(f"  Operation:     {pr.get('operation')}")
            lines.append(f"  Target:        {pr.get('target')}")
            lines.append(f"  Applied:       {pr.get('applied')}")
            lines.append(f"  Details:       {pr.get('details')}")
        else:
            lines.append("  Patch stage was not executed.")
        lines.append("")

        # STAGE 5: SIGN
        lines.append("[STAGE 5: SIGN — AD-HOC CODESIGNING & ENTITLEMENTS]")
        if self.sign_record:
            sr = self.sign_record
            lines.append(f"  Signing Tool:                {sr.get('tool')}")
            lines.append(f"  Signing Method:              {sr.get('signing_method') or sr.get('mode')}")
            lines.append(f"  Provisioning:                {sr.get('provisioning_status', 'None')}")
            lines.append(f"  Distribution Status:         {sr.get('distribution_status', 'No Apple signing authorization')}")
            lines.append(f"  Entitlement Source:          {sr.get('entitlements_source') or 'Project configuration'}")
            lines.append(f"  Entitlement File:            {sr.get('entitlements_file') or 'ad-hoc'}")
            keys = sr.get("entitlements_keys", [])
            if keys:
                lines.append(f"  Injected Keys ({len(keys)}):         {', '.join(keys)}")
            else:
                lines.append("  Injected Keys (0):           None (Clean empty dictionary: <dict/>)")
            lines.append("  Note: Entitlement keys are embedded in the signature via ldid.")
            lines.append("        Runtime authorization depends on the OS installation engine.")
            lines.append("  ------------------------------------------------------------")
            lines.append("  SIGNATURE & VERIFICATION STATUS AUDIT:")
            lines.append(f"  • Signature structure:        {sr.get('signature_structure', 'Present' if sr.get('signature_structure_present') else 'Missing')}")
            cdh = sr.get("cdhash")
            cdh_suffix = f" ({cdh})" if cdh else ""
            lines.append(f"  • CDHash:                     {sr.get('cdhash_status', 'Extracted' if cdh else 'Unavailable')}{cdh_suffix}")
            lines.append(f"  • Entitlements:               {sr.get('entitlements_status', 'Extracted and compared')}")
            lines.append(f"  • CodeDirectory integrity:    {sr.get('codedirectory_integrity', 'Unsupported')}")
            lines.append(f"  • Apple signer identity:      {sr.get('apple_signer_identity', 'Absent')}")
            lines.append(f"  • Apple trust chain:          {sr.get('apple_trust_chain', 'Not applicable')}")
            lines.append(f"  • Provisioning authorization: {sr.get('provisioning_authorization', 'Absent')}")
            lines.append("  ------------------------------------------------------------")
            lines.append(f"  Target Binary:               {sr.get('input_binary')}")
            lines.append(f"  Working Dir:                 {sr.get('cwd', self.project_dir)}")
            lines.append(f"  Command:                     {format_command_line(sr.get('cmd', []))}")
            lines.append(f"  Exit Code:                   {sr.get('exit_code')} (Duration: {sr.get('elapsed')}s)")
            lines.append(f"  Overall Stage Result:        {'PASSED' if sr.get('valid_signature') else 'FAILED'}")
            if sr.get("stderr"):
                lines.append(f"  Output / Diagnostics:        {sr.get('stderr')}")
        else:
            lines.append("  Signing stage was not executed.")
        lines.append("")

        # STAGE 6: PACKAGE
        lines.append("[STAGE 6: PACKAGE — APPLICATION BUNDLE & IPA ARCHIVE]")
        if self.package_record:
            pkr = self.package_record
            lines.append(f"  Operation:     {pkr.get('operation')}")
            lines.append(f"  Bundle Dir:    {pkr.get('app_bundle_dir')}")
            lines.append(f"  Output IPA:    {pkr.get('ipa_path')}")
            lines.append(f"  IPA Size:      {pkr.get('ipa_size', 0):,} bytes")
            if pkr.get("ipa_sha256"):
                lines.append(f"  IPA SHA-256:   {pkr.get('ipa_sha256')}")
            lines.append(f"  Archive Check: {'VALID ZIP ARCHIVE' if pkr.get('is_valid_zip') else 'CORRUPT/MISSING'}")
            plist_sum = pkr.get("info_plist_summary", {})
            if plist_sum:
                lines.append("  Info.plist Verification:")
                for k, v in plist_sum.items():
                    lines.append(f"    • {k}: {v}")
            lines.append(f"  Packaged Files ({len(pkr.get('files_included', []))} items):")
            for f in pkr.get("files_included", [])[:15]:
                lines.append(f"    • {f}")
            if len(pkr.get("files_included", [])) > 15:
                lines.append(f"    ... and {len(pkr.get('files_included', [])) - 15} more files")
        else:
            lines.append("  Packaging stage was not executed.")
        lines.append("")

        # CANCELLATION SECTION (if cancelled)
        if self.is_cancelled and self.cancellation_info:
            lines.append("[CANCELLATION & SUBPROCESS CLEANUP]")
            ci = self.cancellation_info
            lines.append(f"  Reason:                     {ci.get('reason') or self.failure_reason}")
            lines.append(f"  Interrupted Stage:          {ci.get('stage_index') or self.failure_stage}")
            lines.append(f"  Unstarted Tasks Cancelled:  {ci.get('unstarted_tasks_cancelled', 0)}")
            lines.append(f"  Processes Signalled:        {ci.get('processes_signalled', 0)}")
            lines.append(f"  Gracefully Terminated:      {ci.get('processes_terminated_gracefully', 0)}")
            lines.append(f"  Force-Killed:               {ci.get('processes_force_killed', 0)}")
            lines.append(f"  Processes Reaped:           {ci.get('processes_reaped', 0)}")
            lines.append("")

        # CLEANUP SECTION
        if self.cleanup_record:
            cr = self.cleanup_record
            lines.append("[SUBPROCESS CLEANUP & PROCESS REAPING]")
            lines.append(f"  Cleanup Status:             {cr.get('status', 'unknown').upper()}")
            lines.append(f"  Attempted:                  {'Yes' if cr.get('attempted') else 'No'}")
            lines.append(f"  Completed:                  {'Yes' if cr.get('completed') else 'No'}")
            lines.append(f"  Active Processes Remaining: {cr.get('active_processes_remaining', 0)}")
            if cr.get("unreaped_pids"):
                lines.append(f"  Unreaped PIDs:              {cr.get('unreaped_pids')}")
            telem = cr.get("telemetry", {})
            if telem:
                lines.append(f"  Processes Signalled:        {telem.get('processes_signalled', 0)}")
                lines.append(f"  Gracefully Terminated:      {telem.get('processes_terminated_gracefully', 0)}")
                lines.append(f"  Force-Killed:               {telem.get('processes_force_killed', 0)}")
                lines.append(f"  Processes Reaped:           {telem.get('processes_reaped', 0)}")
                if telem.get("descendant_pids_killed"):
                    lines.append(f"  Descendant PIDs Killed:     {telem.get('descendant_pids_killed')}")
            if cr.get("error"):
                lines.append(f"  Cleanup Diagnostic:         {cr.get('error')}")
            lines.append("")

        # SUMMARY
        lines.append("=" * 80)
        lines.append("BUILD SUMMARY")
        lines.append("=" * 80)
        lines.append(f"Final Outcome:   {status_str}")
        lines.append(f"Total Time:      {self.total_duration:.2f}s")
        lines.append(f"Total Warnings:  {len(self.warnings)}")
        lines.append(f"Total Errors:    {len(self.errors)}")
        if self.warnings:
            lines.append("")
            lines.append("Warnings Recorded:")
            for w in self.warnings:
                lines.append(f"  [WARNING] {w}")
        if self.errors:
            lines.append("")
            lines.append("Errors Recorded:")
            for e in self.errors:
                lines.append(f"  [ERROR] {e}")
        lines.append("=" * 80)
        lines.append(f"Transcript Log:  {self.log_path or 'Pending write'}")
        if self.report_path:
            lines.append(f"JSON Report:     {self.report_path}")
        lines.append("=" * 80)
        return "\n".join(lines) + "\n"
