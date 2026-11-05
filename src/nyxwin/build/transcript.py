"""
Persistent Build Transcript and Observability Module for NyxWin.
Captures comprehensive, verifiable build execution records for every build stage:
SCAN, COMPILE, LINK, PATCH, SIGN, and PACKAGE.
Stores transcripts in NyxWin's canonical external data directory:
%LOCALAPPDATA%\\NyxWin\\Logs\\builds\\<project>\\<build_id>.log
"""

import os
import sys
import time
import json
import platform
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

import nyxwin
from nyxwin.config.paths import get_logs_root

class BuildTranscript:
    """Records real subprocess executions, arguments, exit statuses, outputs, and validation."""

    def __init__(
        self,
        project_name: str,
        project_dir: Path,
        target_triple: str,
        deployment_target: str,
        profile: str,
        toolchain: Any
    ):
        self.project_name = project_name
        self.project_dir = Path(project_dir).resolve()
        self.target_triple = target_triple
        self.deployment_target = deployment_target
        self.profile = profile

        self.start_wall_time = datetime.now()
        self.start_mono_time = time.monotonic()
        timestamp_str = self.start_wall_time.strftime("%Y%m%d_%H%M%S")
        short_id = f"{int(self.start_mono_time * 1000) % 1000000:06d}"
        self.build_id = f"build_{timestamp_str}_{short_id}"

        # Host and Toolchain metadata
        self.nyxwin_version = getattr(nyxwin, "__version__", "1.0.0")
        self.python_version = sys.version.replace("\n", " ")
        self.host_platform = f"{platform.system()} {platform.release()} ({platform.machine()})"

        self.sdk_dir = str(toolchain.sdk_dir) if toolchain and toolchain.sdk_dir else "None"
        self.clang_bin = str(toolchain.clang) if toolchain and toolchain.clang else "None"
        self.swiftc_bin = str(toolchain.swiftc) if toolchain and toolchain.swiftc else "None"
        self.ld64_bin = str(toolchain.ld64 if toolchain.ld64 else toolchain.lld) if toolchain else "None"
        self.ldid_bin = str(toolchain.ldid) if toolchain and toolchain.ldid else "None"

        # Stage execution records
        self.scan_record: Dict[str, Any] = {}
        self.compile_records: List[Dict[str, Any]] = []
        self.link_record: Dict[str, Any] = {}
        self.patch_record: Dict[str, Any] = {}
        self.sign_record: Dict[str, Any] = {}
        self.package_record: Dict[str, Any] = {}

        self.warnings: List[str] = []
        self.errors: List[str] = []
        self.is_success = False
        self.failure_stage = 0
        self.failure_reason = ""
        self.total_duration = 0.0
        self.log_path: Optional[Path] = None

    def record_scan(self, c_sources: List[Path], swift_sources: List[Path], excluded_dirs: List[str]):
        """Records source discovery details."""
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
            "excluded_dirs": list(excluded_dirs)
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
        output_size: int = 0
    ):
        """Records an individual compilation step."""
        rec = {
            "tool": tool,
            "input_file": input_file,
            "output_file": output_file,
            "cmd": list(cmd),
            "exit_code": exit_code,
            "elapsed": round(elapsed, 3),
            "cached": cached,
            "stdout": stdout.strip(),
            "stderr": stderr.strip(),
            "output_valid": output_valid,
            "output_size": output_size
        }
        self.compile_records.append(rec)
        if stderr and exit_code == 0:
            self.warnings.append(f"[{tool}] {input_file}: {stderr.strip()}")
        elif exit_code != 0:
            self.errors.append(f"[{tool}] {input_file} failed with exit code {exit_code}: {stderr.strip()}")

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
        macho_header: Optional[Dict[str, Any]] = None
    ):
        """Records Darwin Mach-O linking operation."""
        self.link_record = {
            "tool": tool,
            "object_files": list(object_files),
            "frameworks": list(frameworks),
            "libraries": list(libraries),
            "output_binary": output_binary,
            "cmd": list(cmd),
            "exit_code": exit_code,
            "elapsed": round(elapsed, 3),
            "stdout": stdout.strip(),
            "stderr": stderr.strip(),
            "output_valid": output_valid,
            "output_size": output_size,
            "macho_header": macho_header or {}
        }
        if stderr and exit_code == 0:
            self.warnings.append(f"[linker] {stderr.strip()}")
        elif exit_code != 0:
            self.errors.append(f"[linker] failed with exit code {exit_code}: {stderr.strip()}")

    def record_patch(self, operation: str, target: str, applied: bool, details: str):
        """Records Mach-O Patch #31 operation."""
        self.patch_record = {
            "operation": operation,
            "target": target,
            "applied": applied,
            "details": details
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
        **kwargs
    ):
        """Records code signing and entitlement injection operation."""
        sig_struct_pres = kwargs.get("signature_structure_present", valid_signature)
        cdh = kwargs.get("cdhash", "")
        ext_ok = kwargs.get("entitlements_extracted", False)
        ext_keys = kwargs.get("extracted_keys", [])
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
            "cryptographic_verification": kwargs.get("cryptographic_verification", "Signature verification unavailable (Ad-hoc pseudo-signature / No Apple Trustchain)"),
            "cmd": list(cmd),
            "exit_code": exit_code,
            "elapsed": round(elapsed, 3),
            "stdout": stdout.strip(),
            "stderr": stderr.strip(),
            "valid_signature": valid_signature
        }
        if exit_code != 0:
            self.errors.append(f"[signer] {tool} failed with exit code {exit_code}: {stderr.strip()}")

    def record_package(
        self,
        operation: str,
        app_bundle_dir: str,
        files_included: List[str],
        ipa_path: str,
        ipa_size: int,
        is_valid_zip: bool,
        info_plist_summary: Dict[str, Any],
        elapsed: float
    ):
        """Records application bundle and IPA package creation."""
        self.package_record = {
            "operation": operation,
            "app_bundle_dir": app_bundle_dir,
            "files_included": list(files_included),
            "ipa_path": ipa_path,
            "ipa_size": ipa_size,
            "is_valid_zip": is_valid_zip,
            "info_plist_summary": info_plist_summary,
            "elapsed": round(elapsed, 3)
        }

    def finalize(self, is_success: bool, failure_stage: int = 0, failure_reason: str = "") -> Path:
        """
        Finalizes the build record, formats the persistent build transcript,
        and saves it to NyxWin's external Logs directory.
        """
        self.total_duration = round(time.monotonic() - self.start_mono_time, 2)
        self.is_success = is_success
        self.failure_stage = failure_stage
        self.failure_reason = failure_reason

        logs_root = get_logs_root() / "builds" / self._sanitize_filename(self.project_name)
        logs_root.mkdir(parents=True, exist_ok=True)

        log_file = logs_root / f"{self.build_id}.log"
        latest_file = logs_root / "latest.log"
        self.log_path = log_file

        transcript_text = self._generate_transcript_text()
        log_file.write_text(transcript_text, encoding="utf-8")

        try:
            latest_file.write_text(transcript_text, encoding="utf-8")
        except Exception:
            pass

        return log_file

    def _sanitize_filename(self, name: str) -> str:
        return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name)

    def format_transcript(self) -> str:
        """Public method returning the formatted build transcript text."""
        return self._generate_transcript_text()

    def _generate_transcript_text(self) -> str:
        """Generates structured, verifiable plain-text transcript."""
        status_str = "BUILD SUCCEEDED" if self.is_success else f"BUILD FAILED (Stage {self.failure_stage}: {self.failure_reason})"
        lines = [
            "=" * 80,
            "NYXWIN NATIVE IOS BUILD TRANSCRIPT",
            "=" * 80,
            f"Build ID:          {self.build_id}",
            f"Project Name:      {self.project_name}",
            f"Project Directory: {self.project_dir}",
            f"Timestamp:         {self.start_wall_time.strftime('%Y-%m-%d %H:%M:%S')}",
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
            ""
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
                lines.append(f"       Command:   {' '.join(cr['cmd'])}")
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
            lines.append(f"  Command:       {' '.join(lr.get('cmd', []))}")
            lines.append(f"  Object Inputs: {len(lr.get('object_files', []))} object(s)")
            for obj in lr.get("object_files", []):
                lines.append(f"    • {Path(obj).name}")
            lines.append(f"  Frameworks:    {', '.join(lr.get('frameworks', [])) or 'None'}")
            lines.append(f"  Libraries:     {', '.join(lr.get('libraries', [])) or 'None'}")
            lines.append(f"  Output Binary: {lr.get('output_binary')}")
            lines.append(f"  Exit Code:     {lr.get('exit_code')} (Duration: {lr.get('elapsed')}s)")
            hdr = lr.get("macho_header", {})
            hdr_str = f"Magic={hdr.get('magic_hex', '0xFEEDFACF')} ({hdr.get('arch', 'ARM64')}), Type={hdr.get('filetype', 'MH_EXECUTE')}" if hdr else "Valid Mach-O"
            valid_str = f"VALID ({lr.get('output_size', 0):,} bytes, {hdr_str})" if lr.get("output_valid") else "INVALID/MISSING"
            lines.append(f"  Validation:    {valid_str}")
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
            lines.append(f"  Command:                     {' '.join(sr.get('cmd', []))}")
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

        # SUMMARY
        lines.append("=" * 80)
        lines.append("BUILD SUMMARY")
        lines.append("=" * 80)
        lines.append(f"Final Outcome:   {status_str}")
        lines.append(f"Total Time:      {self.total_duration:.2f}s")
        lines.append(f"Total Warnings:  {len(self.warnings)}")
        lines.append(f"Total Errors:    {len(self.errors)}")
        if self.errors:
            lines.append("")
            lines.append("Errors Recorded:")
            for e in self.errors:
                lines.append(f"  [ERROR] {e}")
        lines.append("=" * 80)
        lines.append(f"Transcript Log:  {self.log_path or 'Pending write'}")
        lines.append("=" * 80)
        return "\n".join(lines) + "\n"

