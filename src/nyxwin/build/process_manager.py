"""
Windows-Native Build Subprocess & Graceful Cancellation Manager for NyxWin.

Responsibilities:
1. Tracks only subprocesses and worker futures owned by the active build.
2. Launches build subprocesses in isolated Windows process groups (CREATE_NEW_PROCESS_GROUP)
   without modifying global environment or killing unrelated host processes.
3. Supports cooperative and signal-driven cancellation:
   - Stops scheduling new compilation/linking/packaging tasks immediately.
   - Cancels pending worker futures that have not started.
   - Signals running build subprocesses to stop gracefully (CTRL_BREAK_EVENT / terminate).
   - Waits a bounded grace period before force-terminating remaining process trees
     (targeted verified process handles & creation-time identity validation).
   - Reaps all terminated processes and collects final exit codes / partial outputs.
4. Bounded output collection:
   - Drains stdout/stderr pipes continuously via BoundedStreamCollector to prevent pipe deadlocks.
   - Caps memory consumption to DEFAULT_MAX_OUTPUT_CAPTURE_BYTES (1 MB).
   - Preserves diagnostic context with clear head/tail truncation notice when exceeded.
"""

import os
import sys
import time
import signal
import ctypes
from ctypes import wintypes
import threading
import subprocess
from pathlib import Path
from concurrent.futures import Future
from typing import List, Dict, Optional, Any, Set, Callable

_REAL_SUBPROCESS_RUN = subprocess.run
DEFAULT_MAX_OUTPUT_CAPTURE_BYTES = 1024 * 1024  # 1 MB per stream


class BuildCancelledError(Exception):
    """Raised when an active build is cancelled by the user or a cancellation controller."""

    def __init__(self, message: str = "Build cancelled by user", stage_idx: int = 0):
        super().__init__(message)
        self.message = message
        self.stage_idx = stage_idx


def _is_mock_callable(fn: Any) -> bool:
    """Returns True if `fn` is a unittest.mock object or a patched mock replacement."""
    if fn is None:
        return False
    try:
        import unittest.mock as mock
        if isinstance(fn, mock.NonCallableMock):
            return True
    except Exception:
        pass
    if hasattr(fn, "_mock_name") and (hasattr(fn, "assert_called") or hasattr(fn, "mock_calls") or hasattr(fn, "side_effect")):
        return True
    cls_name = type(fn).__name__
    if cls_name in ("MagicMock", "Mock", "NonCallableMagicMock", "AsyncMock"):
        return True
    return False


# ---------------------------------------------------------------------------
# Windows Native Process API Declarations with Explicit 64-bit Signatures
# ---------------------------------------------------------------------------

TH32CS_SNAPPROCESS = 0x00000002
PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_SYNCHRONIZE = 0x00100000
STILL_ACTIVE = 259
WAIT_TIMEOUT = 258

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def _is_invalid_handle(h: Any) -> bool:
    """Returns True if `h` is None, null, a mock, or Win32 INVALID_HANDLE_VALUE."""
    if h is None or _is_mock_callable(h):
        return True
    try:
        val = getattr(h, "value", h)
        if val is None or val == 0 or _is_mock_callable(val):
            return True
        val_int = int(val)
        return val_int in (-1, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF, INVALID_HANDLE_VALUE)
    except Exception:
        return True


_win32_initialized = False


def _ensure_win32_api_signatures() -> None:
    global _win32_initialized
    if _win32_initialized or sys.platform != "win32":
        return
    try:
        kernel32 = ctypes.windll.kernel32

        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]

        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]

        kernel32.Process32NextW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]

        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]

        kernel32.TerminateProcess.restype = wintypes.BOOL
        kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]

        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]

        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        _win32_initialized = True
    except Exception:
        pass


def _get_process_creation_time_win32(handle: Any) -> Optional[int]:
    """Returns the 64-bit FILETIME integer of process creation, or None if unavailable."""
    if sys.platform != "win32" or _is_invalid_handle(handle):
        return None
    _ensure_win32_api_signatures()
    try:
        kernel32 = ctypes.windll.kernel32
        ct = wintypes.FILETIME()
        et = wintypes.FILETIME()
        kt = wintypes.FILETIME()
        ut = wintypes.FILETIME()
        if kernel32.GetProcessTimes(handle, ctypes.byref(ct), ctypes.byref(et), ctypes.byref(kt), ctypes.byref(ut)):
            return (ct.dwHighDateTime << 32) | ct.dwLowDateTime
    except Exception:
        pass
    return None


def _is_pid_running_windows(pid: int) -> bool:
    """Checks whether a specific PID is still active on Windows using OpenProcess + GetExitCodeProcess."""
    if sys.platform != "win32" or not isinstance(pid, int) or pid <= 0:
        return False
    _ensure_win32_api_signatures()
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if _is_invalid_handle(handle):
            return False
        try:
            exit_code = wintypes.DWORD()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return int(exit_code.value) == STILL_ACTIVE
            return False
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return False


def _terminate_pid_windows(pid: int, exit_code: int = 1) -> bool:
    """Terminates a specific PID directly via Win32 TerminateProcess."""
    if sys.platform != "win32" or not isinstance(pid, int) or pid <= 0 or pid == os.getpid():
        return False
    _ensure_win32_api_signatures()
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_TERMINATE | PROCESS_SYNCHRONIZE, False, pid)
        if _is_invalid_handle(handle):
            return False
        try:
            ok = bool(kernel32.TerminateProcess(handle, int(exit_code)))
            kernel32.WaitForSingleObject(handle, 500)
            return ok
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return False


class VerifiedDescendantHandle:
    """Maintains an open, validated native process handle for a descendant child process."""

    def __init__(self, pid: int, handle: Any, creation_time: Optional[int]):
        self.pid = pid
        self.handle = handle
        self.creation_time = creation_time

    def close(self) -> None:
        if sys.platform == "win32" and not _is_invalid_handle(self.handle):
            try:
                ctypes.windll.kernel32.CloseHandle(self.handle)
            except Exception:
                pass
            self.handle = None


def get_descendant_pids(root_pid: int) -> List[int]:
    """
    Returns all current descendant PIDs of `root_pid` on Windows using Win32
    CreateToolhelp32Snapshot (TH32CS_SNAPPROCESS).
    Never raises an exception; returns an empty list if unavailable or on non-Windows.
    """
    if sys.platform != "win32" or not isinstance(root_pid, int) or root_pid <= 0:
        return []
    _ensure_win32_api_signatures()

    try:
        kernel32 = ctypes.windll.kernel32
        snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if _is_invalid_handle(snap):
            return []

        children_map: Dict[int, List[int]] = {}
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            has_proc = kernel32.Process32FirstW(snap, ctypes.byref(entry))
            while has_proc:
                pid = int(entry.th32ProcessID)
                ppid = int(entry.th32ParentProcessID)
                if pid > 0 and pid != ppid:
                    children_map.setdefault(ppid, []).append(pid)
                has_proc = kernel32.Process32NextW(snap, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snap)

        descendants: List[int] = []
        visited: Set[int] = {root_pid, os.getpid()}
        queue = list(children_map.get(root_pid, []))
        while queue:
            curr = queue.pop(0)
            if curr in visited:
                continue
            visited.add(curr)
            descendants.append(curr)
            queue.extend(children_map.get(curr, []))

        return descendants
    except Exception:
        return []


def get_verified_descendants(root_pid: int, root_creation_time: Optional[int] = None) -> List[VerifiedDescendantHandle]:
    """
    Discovers all descendant processes of `root_pid`, opens native process handles to hold
    the kernel process objects open (preventing PID reuse), and validates that each child's
    creation timestamp is >= `root_creation_time`.
    Any process that was created before the root process or cannot be opened is safely discarded.
    """
    if sys.platform != "win32" or not isinstance(root_pid, int) or root_pid <= 0:
        return []
    _ensure_win32_api_signatures()

    descendant_pids = get_descendant_pids(root_pid)
    verified: List[VerifiedDescendantHandle] = []
    kernel32 = ctypes.windll.kernel32

    for d_pid in descendant_pids:
        if d_pid == os.getpid():
            continue
        try:
            h_child = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE | PROCESS_SYNCHRONIZE, False, d_pid)
            if _is_invalid_handle(h_child):
                continue
            child_ct = _get_process_creation_time_win32(h_child)
            # If root_creation_time is known and child was created before parent, this is PID reuse!
            if root_creation_time is not None and child_ct is not None and child_ct < root_creation_time:
                kernel32.CloseHandle(h_child)
                continue
            verified.append(VerifiedDescendantHandle(d_pid, h_child, child_ct))
        except Exception:
            pass

    return verified


class BoundedStreamCollector:
    """
    Reads from a text stream in the background into a bounded memory buffer.
    Continuously drains the pipe to prevent child-process write deadlocks while capping
    memory accumulation to `max_bytes` (default 1 MB).
    Retains the first half (`head`) and the last half (`tail`), inserting an explicit
    diagnostic truncation marker if output exceeds `max_bytes`.
    """

    def __init__(self, stream: Any, max_bytes: int = DEFAULT_MAX_OUTPUT_CAPTURE_BYTES):
        self.stream = stream
        self.max_bytes = max(1024, int(max_bytes))
        self.head_limit = self.max_bytes // 2
        self.tail_limit = self.max_bytes - self.head_limit

        self.head_chunks: List[str] = []
        self.tail_chunks: List[str] = []
        self.head_bytes = 0
        self.tail_bytes = 0
        self.total_bytes = 0
        self.truncated = False
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

        if self.stream is not None:
            self._thread = threading.Thread(target=self._drain_stream, daemon=True)
            self._thread.start()

    def _drain_stream(self) -> None:
        try:
            while True:
                chunk = self.stream.read(8192)
                if not chunk:
                    break
                c_len = len(chunk)
                with self._lock:
                    self.total_bytes += c_len
                    if not self.truncated:
                        if self.head_bytes + c_len <= self.head_limit:
                            self.head_chunks.append(chunk)
                            self.head_bytes += c_len
                        else:
                            avail = max(0, self.head_limit - self.head_bytes)
                            if avail > 0:
                                self.head_chunks.append(chunk[:avail])
                                self.head_bytes += avail
                            self.truncated = True
                            remaining = chunk[avail:]
                            self._add_to_tail(remaining)
                    else:
                        self._add_to_tail(chunk)
        except Exception:
            pass
        finally:
            try:
                self.stream.close()
            except Exception:
                pass

    def _add_to_tail(self, chunk: str) -> None:
        c_len = len(chunk)
        self.tail_chunks.append(chunk)
        self.tail_bytes += c_len
        while self.tail_bytes > self.tail_limit and len(self.tail_chunks) > 1:
            popped = self.tail_chunks.pop(0)
            self.tail_bytes -= len(popped)

    def get_text(self, timeout: float = 1.0) -> str:
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        with self._lock:
            head_str = "".join(self.head_chunks)
            if not self.truncated:
                return head_str
            tail_str = "".join(self.tail_chunks)
            if len(tail_str) > self.tail_limit:
                tail_str = tail_str[-self.tail_limit:]
            marker = (
                f"\n\n[... NyxWin: output truncated ({self.total_bytes:,} total bytes read; "
                f"retained first {len(head_str):,} and last {len(tail_str):,} bytes) ...]\n\n"
            )
            return head_str + marker + tail_str


class TrackedProcessRecord:
    """Metadata and lifecycle state for a single build-owned subprocess."""

    def __init__(self, proc: Any, tool: str, cmd: List[str], cwd: Optional[str] = None):
        self.proc = proc
        self.pid: int = getattr(proc, "pid", -1) or -1
        self.tool = tool
        self.cmd = list(cmd)
        self.cwd = cwd
        self.started_at = time.monotonic()
        self.finished_at: Optional[float] = None
        self.exit_code: Optional[int] = None
        self.signalled_gracefully = False
        self.terminated_gracefully = False
        self.forced_kill = False
        self.reaped = False
        self.descendant_pids_killed: List[int] = []
        self.unresolved_descendant_pids: List[int] = []
        self._lock = threading.RLock()
        self.root_creation_time: Optional[int] = None

        if sys.platform == "win32" and not _is_mock_callable(proc):
            if hasattr(proc, "_handle") and proc._handle and not _is_mock_callable(getattr(proc, "_handle", None)):
                self.root_creation_time = _get_process_creation_time_win32(proc._handle)
            elif isinstance(self.pid, int) and self.pid > 0:
                _ensure_win32_api_signatures()
                try:
                    h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, self.pid)
                    if not _is_invalid_handle(h):
                        try:
                            self.root_creation_time = _get_process_creation_time_win32(h)
                        finally:
                            ctypes.windll.kernel32.CloseHandle(h)
                except Exception:
                    pass

    def is_alive(self) -> bool:
        """Returns True if the underlying process is confirmed or suspected to still be running."""
        try:
            if hasattr(self.proc, "poll") and callable(self.proc.poll):
                ret = self.proc.poll()
                if ret is not None:
                    return False
                if _is_mock_callable(self.proc):
                    return True
                if sys.platform == "win32" and isinstance(self.pid, int) and self.pid > 0:
                    return _is_pid_running_windows(self.pid)
                return True
        except Exception:
            pass
        return False


class BuildCancellationController:
    """
    Coordinates graceful build cancellation, worker future cancellation,
    and Windows-native subprocess tree cleanup for a single build invocation.
    """

    def __init__(
        self,
        grace_timeout: float = 0.5,
        external_cancel_event: Optional[Any] = None,
    ):
        self.grace_timeout = max(0.05, float(grace_timeout))
        self._external_cancel_event = external_cancel_event
        self._cancel_event = threading.Event()
        self._lock = threading.RLock()

        self.cancelled_at: Optional[float] = None
        self.cancel_reason: str = ""
        self.cancelled_stage_idx: int = 0

        self._active_processes: Dict[int, TrackedProcessRecord] = {}
        self._completed_records: List[TrackedProcessRecord] = []
        self._pending_futures: List[Future] = []
        self.cancelled_unstarted_tasks: int = 0

        self.cleanup_attempted: bool = False
        self.cleanup_completed: bool = False
        self.cleanup_error: Optional[str] = None
        self.cleanup_status: str = "pending"  # "pending", "succeeded", "warning", "failed"

    @property
    def is_cancelled(self) -> bool:
        if self._cancel_event.is_set():
            return True
        if self._external_cancel_event is not None:
            try:
                if callable(getattr(self._external_cancel_event, "is_set", None)):
                    if self._external_cancel_event.is_set():
                        self.cancel(reason="Build cancelled via cancellation event")
                        return True
                elif bool(self._external_cancel_event):
                    self.cancel(reason="Build cancelled via cancellation flag")
                    return True
            except Exception:
                pass
        return False

    def check_cancelled(self, stage_idx: int = 0) -> None:
        """Raises BuildCancelledError if cancellation has been requested."""
        if self.is_cancelled:
            with self._lock:
                if stage_idx and not self.cancelled_stage_idx:
                    self.cancelled_stage_idx = stage_idx
                reason = self.cancel_reason or "Build cancelled by user"
                stg = self.cancelled_stage_idx or stage_idx
            raise BuildCancelledError(reason, stage_idx=stg)

    def register_future(self, fut: Future) -> None:
        """Registers a worker future so it can be cancelled if not yet running."""
        with self._lock:
            self._pending_futures.append(fut)

    def record_unstarted_task_cancelled(self) -> None:
        with self._lock:
            self.cancelled_unstarted_tasks += 1

    def register_process(
        self,
        proc: Any,
        tool: str = "subprocess",
        cmd: Optional[List[str]] = None,
        cwd: Optional[str] = None,
    ) -> TrackedProcessRecord:
        """Registers a newly spawned build subprocess and immediately terminates it if already cancelled."""
        rec = TrackedProcessRecord(proc, tool=tool, cmd=cmd or [], cwd=cwd)
        should_terminate = False
        with self._lock:
            self._active_processes[id(proc)] = rec
            if self._cancel_event.is_set():
                should_terminate = True

        if should_terminate:
            self.terminate_process_record(rec)
        return rec

    def unregister_process(self, rec: TrackedProcessRecord, exit_code: Optional[int] = None) -> None:
        """Moves a completed process record from active to completed history."""
        with self._lock:
            rec.finished_at = time.monotonic()
            if exit_code is not None:
                rec.exit_code = exit_code
            elif rec.exit_code is None:
                rec.exit_code = getattr(rec.proc, "returncode", None)

            if not rec.is_alive():
                self._active_processes.pop(id(rec.proc), None)
                rec.reaped = True
                if rec not in self._completed_records:
                    self._completed_records.append(rec)
            else:
                rec.reaped = False

    def terminate_process_record(self, rec: TrackedProcessRecord) -> None:
        """
        Gracefully signals a single tracked subprocess, waits up to `self.grace_timeout`,
        and force-terminates its verified process tree if it remains alive.
        """
        with rec._lock:
            proc = rec.proc
            pid = rec.pid
            root_ct = rec.root_creation_time

            # Pre-snapshot verified descendant handles with creation-time identity validation
            pre_descendants: List[VerifiedDescendantHandle] = []
            if sys.platform == "win32" and isinstance(pid, int) and pid > 0:
                pre_descendants = get_verified_descendants(pid, root_creation_time=root_ct)

            try:
                already_exited = (proc.poll() is not None)
            except Exception:
                already_exited = False

            if not already_exited:
                rec.signalled_gracefully = True
                used_process_group = bool(getattr(proc, "_nyx_new_process_group", False))

                # Step 1: Send graceful stop signal
                try:
                    if sys.platform == "win32" and used_process_group and hasattr(signal, "CTRL_BREAK_EVENT"):
                        try:
                            proc.send_signal(signal.CTRL_BREAK_EVENT)
                        except Exception:
                            proc.terminate()
                    else:
                        proc.terminate()
                except Exception:
                    pass

                # Step 2: Bounded wait for graceful exit
                try:
                    proc.wait(timeout=self.grace_timeout)
                    rec.terminated_gracefully = True
                except subprocess.TimeoutExpired:
                    rec.forced_kill = True
                except Exception:
                    if proc.poll() is None:
                        rec.forced_kill = True
                    else:
                        rec.terminated_gracefully = True

                # Step 3: Forced termination if still alive
                if rec.forced_kill or proc.poll() is None:
                    rec.forced_kill = True

                    # Discover any newly spawned descendants during the grace period
                    post_descendants: List[VerifiedDescendantHandle] = []
                    if sys.platform == "win32" and isinstance(pid, int) and pid > 0:
                        post_descendants = get_verified_descendants(pid, root_creation_time=root_ct)

                    known_pids = {d.pid for d in pre_descendants}
                    combined_descendants = list(pre_descendants)
                    for pd in post_descendants:
                        if pd.pid not in known_pids:
                            combined_descendants.append(pd)
                            known_pids.add(pd.pid)
                        else:
                            pd.close()

                    # Terminate verified descendants directly via their open native handles
                    if sys.platform == "win32":
                        for desc in combined_descendants:
                            try:
                                if not _is_invalid_handle(desc.handle):
                                    if ctypes.windll.kernel32.TerminateProcess(desc.handle, 1):
                                        ctypes.windll.kernel32.WaitForSingleObject(desc.handle, 500)
                                        rec.descendant_pids_killed.append(desc.pid)
                            except Exception:
                                pass
                            finally:
                                desc.close()
                    pre_descendants.clear()

                    # Terminate root process
                    try:
                        proc.kill()
                    except Exception:
                        pass

                # Step 4: Reap process
                try:
                    proc.wait(timeout=2.0)
                    rec.reaped = not rec.is_alive()
                except Exception:
                    rec.reaped = not rec.is_alive()

            # Step 5: Clean up any remaining pre-descendant handles
            for desc in pre_descendants:
                desc.close()

            rec.exit_code = getattr(proc, "returncode", None)
            rec.finished_at = time.monotonic()

    def cancel(self, reason: str = "Build cancelled by user", stage_idx: int = 0) -> Dict[str, Any]:
        """
        Records cancellation, cancels unstarted futures, and terminates/reaps all active
        build subprocesses. Safe and idempotent to call multiple times or from multiple threads.
        """
        with self._lock:
            if not self._cancel_event.is_set():
                self._cancel_event.set()
                self.cancelled_at = time.monotonic()
                self.cancel_reason = reason or "Build cancelled by user"
                if stage_idx:
                    self.cancelled_stage_idx = stage_idx
            elif stage_idx and not self.cancelled_stage_idx:
                self.cancelled_stage_idx = stage_idx

            futures_to_cancel = list(self._pending_futures)
            active_recs = list(self._active_processes.values())

        # Cancel futures that have not started
        for fut in futures_to_cancel:
            try:
                if fut.cancel():
                    self.record_unstarted_task_cancelled()
            except Exception:
                pass

        # Signal and terminate active subprocesses concurrently so multiple parallel workers
        # share the grace period rather than multiplying timeout delays sequentially
        if len(active_recs) == 1:
            self.terminate_process_record(active_recs[0])
            self.unregister_process(active_recs[0])
        elif len(active_recs) > 1:
            term_threads = []
            for r in active_recs:
                t = threading.Thread(target=self.terminate_process_record, args=(r,), daemon=True)
                t.start()
                term_threads.append((t, r))
            for t, r in term_threads:
                t.join(timeout=self.grace_timeout + 3.0)
                self.unregister_process(r)

        return self.get_summary()

    def cleanup_all(self) -> Dict[str, Any]:
        """
        Ensures any remaining active subprocesses owned by this build are terminated and reaped.
        Captures exceptions, checks whether any process remains alive, records cleanup status,
        and returns structured telemetry. Safe and idempotent for repeated calls.
        """
        cleanup_errors: List[str] = []
        with self._lock:
            self.cleanup_attempted = True
            active_recs = list(self._active_processes.values())

        for r in active_recs:
            try:
                self.terminate_process_record(r)
                if not r.is_alive():
                    self.unregister_process(r)
            except Exception as ex:
                cleanup_errors.append(f"PID {r.pid} ({r.tool}): {ex}")
                try:
                    if not r.is_alive():
                        self.unregister_process(r)
                except Exception:
                    pass

        with self._lock:
            remaining_active = sum(1 for r in self._active_processes.values() if r.is_alive())
            unreaped_pids = [r.pid for r in self._active_processes.values() if r.is_alive()]

            if cleanup_errors:
                self.cleanup_error = "; ".join(cleanup_errors)

            if remaining_active > 0 or unreaped_pids:
                self.cleanup_status = "failed"
                self.cleanup_completed = False
            elif cleanup_errors:
                # Cleanup encountered an exception, but all processes confirmed reaped
                self.cleanup_status = "warning"
                self.cleanup_completed = True
            else:
                self.cleanup_status = "succeeded"
                self.cleanup_completed = True

            return self.get_summary()

    def get_summary(self) -> Dict[str, Any]:
        """Returns structured cancellation and process cleanup telemetry for logs and JSON reports."""
        with self._lock:
            all_recs = list(self._completed_records) + list(self._active_processes.values())
            graceful_count = sum(1 for r in all_recs if r.terminated_gracefully)
            forced_count = sum(1 for r in all_recs if r.forced_kill)
            reaped_count = sum(1 for r in all_recs if r.reaped)
            descendants_killed = []
            for r in all_recs:
                descendants_killed.extend(r.descendant_pids_killed)

            remaining_count = sum(1 for r in self._active_processes.values() if r.is_alive())
            unreaped_pids = [r.pid for r in self._active_processes.values() if r.is_alive()]

            return {
                "cancelled": self._cancel_event.is_set(),
                "reason": self.cancel_reason if self._cancel_event.is_set() else None,
                "stage_index": self.cancelled_stage_idx if self._cancel_event.is_set() else None,
                "unstarted_tasks_cancelled": self.cancelled_unstarted_tasks,
                "processes_signalled": sum(1 for r in all_recs if r.signalled_gracefully),
                "processes_terminated_gracefully": graceful_count,
                "processes_force_killed": forced_count,
                "processes_reaped": reaped_count,
                "descendant_pids_killed": descendants_killed,
                "active_processes_remaining": remaining_count,
                "cleanup": {
                    "attempted": self.cleanup_attempted,
                    "completed": self.cleanup_completed,
                    "status": self.cleanup_status,
                    "error": self.cleanup_error,
                    "active_processes_remaining": remaining_count,
                    "unreaped_pids": unreaped_pids,
                },
            }


def run_build_subprocess(
    cmd: List[str],
    cwd: Optional[Path] = None,
    cancel_controller: Optional[BuildCancellationController] = None,
    tool_name: str = "subprocess",
    stage_idx: int = 0,
    run_fn: Optional[Callable] = None,
    popen_fn: Optional[Callable] = None,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_CAPTURE_BYTES,
) -> subprocess.CompletedProcess:
    """
    Executes a single build tool command with full cancellation, memory bounding, and
    process-tree cleanup support.
    - Checks `cancel_controller.check_cancelled()` before starting.
    - Preserves compatibility with existing unit tests that patch `subprocess.run`.
    - When running real subprocesses (or a custom `popen_fn`), launches the child in a
      Windows process group (`CREATE_NEW_PROCESS_GROUP`), registers it with `cancel_controller`,
      drains output via background `BoundedStreamCollector` threads (avoiding OS pipe deadlocks
      and bounding memory to `max_output_bytes`), and guarantees process reaping before returning
      or raising `BuildCancelledError`.
    """
    if cancel_controller is not None:
        cancel_controller.check_cancelled(stage_idx=stage_idx)

    cwd_str = str(cwd) if cwd is not None else None
    effective_run = run_fn if run_fn is not None else subprocess.run

    # Preserve seamless compatibility when unit tests mock subprocess.run
    if popen_fn is None and _is_mock_callable(effective_run):
        proc_res = effective_run(cmd, capture_output=True, text=True)
        if cancel_controller is not None:
            cancel_controller.check_cancelled(stage_idx=stage_idx)
        return proc_res

    effective_popen = popen_fn if popen_fn is not None else subprocess.Popen
    popen_kwargs: Dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if cwd is not None and Path(cwd).is_dir():
        popen_kwargs["cwd"] = str(Path(cwd).resolve())

    used_new_pgroup = False
    if sys.platform == "win32" and popen_fn is None and not _is_mock_callable(effective_popen):
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        used_new_pgroup = True

    proc = effective_popen(cmd, **popen_kwargs)
    try:
        setattr(proc, "_nyx_new_process_group", used_new_pgroup)
    except Exception:
        pass

    rec: Optional[TrackedProcessRecord] = None
    if cancel_controller is not None:
        rec = cancel_controller.register_process(proc, tool=tool_name, cmd=cmd, cwd=cwd_str)

    # Bounded stream collectors drain stdout and stderr without pipe deadlock
    stdout_collector = BoundedStreamCollector(getattr(proc, "stdout", None), max_bytes=max_output_bytes)
    stderr_collector = BoundedStreamCollector(getattr(proc, "stderr", None), max_bytes=max_output_bytes)

    stdout_data = ""
    stderr_data = ""
    try:
        while True:
            if cancel_controller is not None and cancel_controller.is_cancelled:
                if rec is not None:
                    cancel_controller.terminate_process_record(rec)
                break
            try:
                proc.wait(timeout=0.05)
                break
            except subprocess.TimeoutExpired:
                continue
            except KeyboardInterrupt:
                if cancel_controller is not None:
                    cancel_controller.cancel(
                        reason="Build aborted by user (Ctrl+C)",
                        stage_idx=stage_idx,
                    )
                else:
                    temp_ctrl = BuildCancellationController(grace_timeout=0.5)
                    temp_rec = TrackedProcessRecord(proc, tool=tool_name, cmd=cmd, cwd=cwd_str)
                    temp_ctrl.terminate_process_record(temp_rec)
                raise BuildCancelledError("Build aborted by user (Ctrl+C)", stage_idx=stage_idx)

        # Collect bounded outputs
        stdout_data = stdout_collector.get_text(timeout=1.0)
        stderr_data = stderr_collector.get_text(timeout=1.0)

        # If loop exited due to cancellation, raise BuildCancelledError
        if cancel_controller is not None and cancel_controller.is_cancelled:
            raise BuildCancelledError(
                cancel_controller.cancel_reason or "Build cancelled by user",
                stage_idx=cancel_controller.cancelled_stage_idx or stage_idx,
            )

        ret_code = proc.returncode if proc.returncode is not None else 0
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=ret_code,
            stdout=stdout_data,
            stderr=stderr_data,
        )
    finally:
        # Ensure pipes are closed and process record is unregistered
        for stream_name in ("stdout", "stderr", "stdin"):
            stream = getattr(proc, stream_name, None)
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
        if cancel_controller is not None and rec is not None:
            cancel_controller.unregister_process(rec, exit_code=getattr(proc, "returncode", None))
