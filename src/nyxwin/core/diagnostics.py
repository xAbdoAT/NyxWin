import sys
from pathlib import Path
from typing import Any, Optional, Dict, List, Tuple
from nyxwin.core.models import Color

def format_compiler_diagnostics(stderr_text: str):
    """
    Parses compiler error output (clang / swiftc) and formats it into clean,
    readable diagnostic callouts with colored highlights and squiggles.
    """
    if not stderr_text:
        return

    lines = stderr_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        parts = line.split(":", 4)
        if len(parts) >= 5 and any(severity in parts[3] for severity in ["error", "warning", "note"]):
            file_path = parts[0].strip()
            line_no = parts[1].strip()
            col_no = parts[2].strip()
            severity_str = parts[3].strip()
            msg = parts[4].strip()

            if "error" in severity_str:
                sev_color = Color.RED
                sev_label = "ERROR"
            elif "warning" in severity_str:
                sev_color = Color.YELLOW
                sev_label = "WARNING"
            else:
                sev_color = Color.CYAN
                sev_label = "NOTE"

            print(f"  {Color.WHITE}{file_path}:{line_no}:{col_no}:{Color.RESET} {sev_color}{Color.BOLD}{sev_label}:{Color.RESET} {msg}")

            # Print source code context and caret squiggles if present
            if i + 1 < len(lines) and not (":" in lines[i+1] and any(s in lines[i+1] for s in ["error:", "warning:", "note:"])):
                i += 1
                print(f"      {lines[i]}")
                if i + 1 < len(lines) and ("^" in lines[i+1] or "~" in lines[i+1]):
                    i += 1
                    print(f"      {sev_color}{lines[i]}{Color.RESET}")
        else:
            if line.strip():
                print(f"  {line}")
        i += 1

def parse_diagnostic_details(stderr_text: str, default_tool: str = "Compiler") -> dict:
    """
    Extracts structured diagnostic fields from compiler/linker/tool stderr without inventing data.
    Returns a dictionary suitable for rendering in the inline failure card.
    """
    result = {
        "category": "COMPILER DIAGNOSTIC",
        "tool": default_tool,
        "message": "Operation failed",
        "file": None,
        "line": None,
        "col": None,
        "snippet": None,
        "caret": None,
        "raw_lines": []
    }
    if not stderr_text:
        return result

    lines = [l.rstrip() for l in stderr_text.splitlines() if l.strip()]
    result["raw_lines"] = lines[:12]

    # 1. Detect Linker failures (ld64.lld, lld)
    if any("Undefined symbols" in l or "undefined symbol:" in l or "ld64.lld:" in l or "lld-link:" in l for l in lines):
        result["category"] = "LINKER DIAGNOSTIC"
        result["tool"] = "ld64.lld"
        for l in lines:
            if "Undefined symbols" in l:
                result["message"] = l.strip()
                break
            elif "undefined symbol:" in l:
                result["message"] = l.strip()
                break
            elif "error:" in l:
                result["message"] = l.split("error:", 1)[1].strip()
                break
        else:
            result["message"] = lines[0].strip()
        return result

    # 2. Detect Codesign failures (ldid)
    if any("ldid" in l.lower() or "_assert" in l.lower() for l in lines):
        result["category"] = "CODESIGN DIAGNOSTIC"
        result["tool"] = "ldid"
        result["message"] = "Ad-hoc codesigning with ldid failed"
        for l in lines:
            if "_assert" in l or "error" in l.lower():
                result["message"] = l.strip()
                break
        return result

    # 3. Detect Compiler errors: file:line:col: error: msg
    # Handles Windows drive letters (e.g. C:\path\file.swift:15:10: error: msg)
    import re
    import os
    for i, line in enumerate(lines):
        m = re.match(r"^((?:[a-zA-Z]:)?[^:]+):(\d+):(\d+):\s*(?:fatal\s+)?error:\s*(.*)$", line.strip(), re.IGNORECASE)
        if m:
            file_raw = m.group(1).strip()
            file_name = os.path.basename(file_raw) or file_raw
            result["file"] = file_name
            try:
                result["line"] = int(m.group(2).strip())
                result["col"] = int(m.group(3).strip())
            except ValueError:
                pass
            result["message"] = m.group(4).strip()
            result["category"] = "COMPILER DIAGNOSTIC"
            if file_name.endswith(".swift") or "swift" in default_tool.lower():
                result["tool"] = "swiftc"
            else:
                result["tool"] = "clang"

            # Check next lines for snippet and caret
            if i + 1 < len(lines) and not re.match(r"^((?:[a-zA-Z]:)?[^:]+):(\d+):", lines[i + 1].strip()):
                result["snippet"] = lines[i + 1].strip()
                if i + 2 < len(lines) and ("^" in lines[i + 2] or "~" in lines[i + 2]):
                    result["caret"] = lines[i + 2]
            return result

    # 4. Fallback search for any line with error:
    for l in lines:
        if "error:" in l.lower():
            result["message"] = l.split("error:", 1)[-1].strip() or l.strip()
            prefix = l[:l.lower().index("error:")].strip().rstrip(":")
            if "clang++" in prefix.lower():
                result["tool"] = "clang++"
            elif "clang" in prefix.lower():
                result["tool"] = "clang"
            elif "swift" in prefix.lower():
                result["tool"] = "swiftc"
            elif "ld64" in prefix.lower() or "lld" in prefix.lower():
                result["tool"] = "ld64.lld"
            break
    else:
        if lines:
            result["message"] = lines[0].strip()

    if result.get("tool") in (None, "", "none"):
        result["tool"] = default_tool if default_tool not in (None, "", "none") else "Compiler"

    return result

def generate_diagnostics_report_text(
    tracker: Any,
    project_dir: Optional[Path] = None,
    is_success: bool = True
) -> str:
    """
    Constructs a complete, detailed, human-readable build diagnostics report
    preserving all compiler warnings, errors, notes, and raw output.
    """
    from datetime import datetime, timezone

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    proj_name = getattr(tracker, "project_name", "Unknown Project")
    target_triple = getattr(tracker, "target_triple", "arm64-apple-ios")
    profile = getattr(tracker, "profile", "Auto").capitalize()
    elapsed = getattr(tracker, "format_build_elapsed", lambda: "00:00")()
    warnings = getattr(tracker, "warnings", [])
    errors = getattr(tracker, "errors", [])
    fail_diag = getattr(tracker, "failure_diagnostic", None)

    if is_success:
        result_str = "BUILD SUCCEEDED WITH WARNINGS" if warnings else "BUILD SUCCEEDED"
    else:
        result_str = "BUILD FAILED"

    compiler_warnings = [w for w in warnings if getattr(w, "tool", "").lower() in ("clang", "clang++", "swiftc", "compiler")]
    linker_warnings = [w for w in warnings if getattr(w, "tool", "").lower() in ("ld64.lld", "lld", "ld64", "linker")]

    # Count distinct error occurrences accurately across all error outputs
    seen_error_keys = set()
    compiler_errors_count = 0
    linker_errors_count = 0
    import re
    err_re = re.compile(r"^((?:[a-zA-Z]:)?[^:]+:\d+:\d+:\s*(?:fatal\s+)?error:|(?:[a-zA-Z0-9_\.\-]+:\s*)?(?:fatal\s+)?error:|\b(?:fatal\s+)?error:)", re.IGNORECASE)

    all_err_sources = list(errors)
    if fail_diag and fail_diag.get("raw_lines"):
        all_err_sources.extend(fail_diag["raw_lines"])

    for err_src in all_err_sources:
        for line in str(err_src).splitlines():
            l_str = line.strip()
            if not l_str:
                continue
            # Skip compiler summary lines such as "1 error and 2 warnings generated."
            if re.search(r"^\d+\s+errors?\s+generated", l_str, re.IGNORECASE) or re.search(r"^\d+\s+error.*generated", l_str, re.IGNORECASE):
                continue
            if "ld64.lld:" in l_str or "lld-link:" in l_str or "undefined symbol" in l_str.lower():
                if "error:" in l_str.lower() or "undefined symbol" in l_str.lower():
                    if l_str not in seen_error_keys:
                        seen_error_keys.add(l_str)
                        linker_errors_count += 1
            elif err_re.search(l_str) or "error:" in l_str.lower():
                if l_str not in seen_error_keys:
                    seen_error_keys.add(l_str)
                    compiler_errors_count += 1

    if not is_success and compiler_errors_count == 0 and linker_errors_count == 0:
        if fail_diag and fail_diag.get("tool") == "ld64.lld":
            linker_errors_count = 1
        else:
            compiler_errors_count = 1

    total_errors_count = compiler_errors_count + linker_errors_count if not is_success else 0

    lines = [
        "=" * 80,
        "NYXWIN BUILD DIAGNOSTICS REPORT",
        "=" * 80,
        f"Project:             {proj_name}",
        f"Timestamp:           {now_str}",
        f"Build Result:        {result_str}",
        f"Target Architecture: {target_triple}",
        f"Entitlement Profile: {profile}",
        f"Build Elapsed:       {elapsed}",
        "",
        f"Compiler Warnings:   {len(compiler_warnings)}",
        f"Linker Warnings:     {len(linker_warnings)}",
        f"Total Warnings:      {len(warnings)}",
        "",
        f"Compiler Errors:     {compiler_errors_count}",
        f"Linker Errors:       {linker_errors_count}",
        f"Total Errors:        {total_errors_count}",
    ]
    if project_dir:
        lines.append(f"Project Directory:   {project_dir}")
    ipa_path = getattr(tracker, "ipa_path", None)
    if ipa_path:
        lines.append(f"Output Artifact:     {ipa_path}")
    lines.append("=" * 80)
    lines.append("")

    # If failure diagnostic exists
    if not is_success and fail_diag:
        lines.append("--- FATAL FAILURE DIAGNOSTIC ---")
        lines.append(f"Primary Failure: {fail_diag.get('message', 'Build terminated with error')}")
        lines.append(f"Tool:            {fail_diag.get('tool', 'toolchain')}")
        lines.append(f"Exit Code:       {fail_diag.get('exit_code', 1)}")
        lines.append(f"Category:        {fail_diag.get('category', 'BUILD FAILURE')}")
        if fail_diag.get("file"):
            lines.append(f"Location:        {fail_diag.get('file')}:{fail_diag.get('line', '')}:{fail_diag.get('col', '')}")
        if fail_diag.get("snippet"):
            lines.append("Source Context:")
            lines.append(f"    {fail_diag['snippet']}")
            if fail_diag.get("caret"):
                lines.append(f"    {fail_diag['caret']}")
        if fail_diag.get("raw_lines"):
            lines.append("Raw Diagnostic Lines:")
            for rl in fail_diag["raw_lines"]:
                lines.append(f"    {rl}")
        lines.append("-" * 80)
        lines.append("")

    # If raw errors exist
    if errors and not fail_diag:
        lines.append("--- ERROR STREAM ---")
        for err in errors:
            lines.append(str(err))
        lines.append("-" * 80)
        lines.append("")

    # Warnings section
    if warnings:
        if linker_warnings and not compiler_warnings:
            lines.append(f"--- LINKER WARNINGS ({len(warnings)}) ---")
        elif linker_warnings and compiler_warnings:
            lines.append(f"--- COMPILER & LINKER WARNINGS ({len(warnings)}) ---")
        else:
            lines.append(f"--- COMPILER WARNINGS ({len(warnings)}) ---")
        for idx, w in enumerate(warnings, 1):
            tool = getattr(w, "tool", "compiler")
            file_loc = getattr(w, "file_loc", "")
            msg = getattr(w, "message", str(w))
            snippet = getattr(w, "snippet", "")
            caret = getattr(w, "caret", "")
            notes = getattr(w, "notes", [])
            fixits = getattr(w, "fixits", [])
            raw = getattr(w, "raw_text", str(w))

            lines.append(f"[Warning {idx} of {len(warnings)}]")
            if tool:
                lines.append(f"Tool:       {tool}")
            if file_loc:
                lines.append(f"Location:   {file_loc}")
            lines.append(f"Message:    {msg}")
            if snippet:
                lines.append("Source Context:")
                lines.append(f"    {snippet}")
                if caret:
                    lines.append(f"    {caret}")
            if notes:
                lines.append("Associated Notes:")
                for n in notes:
                    loc = f"{n['file_loc']}: " if n.get('file_loc') else ""
                    lines.append(f"    • {loc}{n.get('message', '')}")
            if fixits:
                lines.append("Fix-it Suggestions:")
                for f in fixits:
                    lines.append(f"    • {f}")
            lines.append("Raw Diagnostic:")
            for rl in raw.splitlines():
                lines.append(f"    {rl}")
            lines.append("-" * 80)
    else:
        lines.append("No compiler warnings recorded.")

    lines.append("")
    lines.append("=" * 80)
    lines.append("END OF DIAGNOSTICS REPORT")
    lines.append("=" * 80)
    return "\n".join(lines) + "\n"

def save_diagnostics_report(
    tracker: Any,
    project_dir: Optional[Path] = None,
    is_success: bool = True,
    custom_dest: Optional[Path] = None
) -> Path:
    """
    Saves the full diagnostics report into NyxWin's canonical machine-local Logs directory.
    Never pollutes or modifies the project source tree.
    """
    from nyxwin.config.paths import get_logs_root
    from datetime import datetime

    logs_dir = get_logs_root() / "diagnostics"
    logs_dir.mkdir(parents=True, exist_ok=True)

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    proj_name = getattr(tracker, "project_name", "Project") or "Project"
    dest_path = custom_dest or (logs_dir / f"build_diagnostics_{proj_name}_{timestamp_str}.txt")

    content = generate_diagnostics_report_text(tracker, project_dir, is_success)
    dest_path.write_text(content, encoding="utf-8")
    return dest_path
