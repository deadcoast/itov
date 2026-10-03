"""Windows process identity and atomically job-owned, initially suspended children."""

from __future__ import annotations

import ctypes as C
import os
import subprocess
from ctypes import wintypes as W


def api():
    if os.name != "nt":
        raise ValueError("Managed parallel qualification currently requires Windows 10 or later")
    kernel = C.WinDLL("kernel32", use_last_error=True)
    declarations = {
        "CloseHandle": ([W.HANDLE], W.BOOL),
        "OpenProcess": ([W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
        "GetProcessTimes": ([W.HANDLE, *([C.POINTER(W.FILETIME)] * 4)], W.BOOL),
        "WaitForSingleObject": ([W.HANDLE, W.DWORD], W.DWORD),
        "CreateJobObjectW": ([C.c_void_p, W.LPCWSTR], W.HANDLE),
        "OpenJobObjectW": ([W.DWORD, W.BOOL, W.LPCWSTR], W.HANDLE),
        "SetInformationJobObject": ([W.HANDLE, C.c_int, C.c_void_p, W.DWORD], W.BOOL),
        "QueryInformationJobObject": ([W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.c_void_p], W.BOOL),
        "TerminateJobObject": ([W.HANDLE, W.UINT], W.BOOL),
        "InitializeProcThreadAttributeList": (
            [C.c_void_p, W.DWORD, W.DWORD, C.POINTER(C.c_size_t)],
            W.BOOL,
        ),
        "UpdateProcThreadAttribute": (
            [C.c_void_p, W.DWORD, C.c_size_t, C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p],
            W.BOOL,
        ),
        "DeleteProcThreadAttributeList": ([C.c_void_p], None),
        "CreateProcessW": (
            [
                W.LPCWSTR,
                W.LPWSTR,
                C.c_void_p,
                C.c_void_p,
                W.BOOL,
                W.DWORD,
                C.c_void_p,
                W.LPCWSTR,
                C.c_void_p,
                C.c_void_p,
            ],
            W.BOOL,
        ),
        "ResumeThread": ([W.HANDLE], W.DWORD),
        "GlobalMemoryStatusEx": ([C.c_void_p], W.BOOL),
    }
    for name, (args, result) in declarations.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = args, result
    return kernel


def checked(result):
    if not result:
        raise C.WinError(C.get_last_error())
    return result


def creation_time(kernel, handle):
    times = [W.FILETIME() for _ in range(4)]
    checked(kernel.GetProcessTimes(handle, *(C.byref(value) for value in times)))
    return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime


def process_identity(pid: int) -> dict:
    kernel = api()
    handle = checked(kernel.OpenProcess(0x1000 | 0x100000, False, pid))
    try:
        return {"pid": pid, "created": creation_time(kernel, handle)}
    finally:
        kernel.CloseHandle(handle)


def process_state(identity: dict) -> str:
    """A different creation time proves the recorded process is gone, not ownership of its PID."""
    if (
        type(identity.get("pid")) is not int
        or identity["pid"] <= 0
        or type(identity.get("created")) is not int
    ):
        raise ValueError("Invalid process identity")
    kernel = api()
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, identity["pid"])
    if not handle:
        if C.get_last_error() == 87:  # No such PID; access denied is unknown, never dead.
            return "dead"
        raise C.WinError(C.get_last_error())
    try:
        if creation_time(kernel, handle) != identity["created"]:
            return "dead"
        result = kernel.WaitForSingleObject(handle, 0)
        if result not in (0, 258):
            raise C.WinError(C.get_last_error())
        return "dead" if result == 0 else "alive"
    finally:
        kernel.CloseHandle(handle)


class BasicLimits(C.Structure):
    _fields_ = [
        ("process_time", C.c_int64),
        ("job_time", C.c_int64),
        ("flags", W.DWORD),
        ("minimum_working", C.c_size_t),
        ("maximum_working", C.c_size_t),
        ("process_limit", W.DWORD),
        ("affinity", C.c_size_t),
        ("priority", W.DWORD),
        ("scheduling", W.DWORD),
    ]


class ExtendedLimits(C.Structure):
    _fields_ = [
        ("basic", BasicLimits),
        ("io", C.c_uint64 * 6),
        ("process_memory", C.c_size_t),
        ("job_memory", C.c_size_t),
        ("peak_process", C.c_size_t),
        ("peak_job", C.c_size_t),
    ]


class Accounting(C.Structure):
    _fields_ = [
        ("times", C.c_int64 * 4),
        ("faults", W.DWORD),
        ("total", W.DWORD),
        ("active", W.DWORD),
        ("terminated", W.DWORD),
    ]


class Startup(C.Structure):
    _fields_ = [
        ("cb", W.DWORD),
        ("reserved", W.LPWSTR),
        ("desktop", W.LPWSTR),
        ("title", W.LPWSTR),
        ("x", W.DWORD),
        ("y", W.DWORD),
        ("xsize", W.DWORD),
        ("ysize", W.DWORD),
        ("xchars", W.DWORD),
        ("ychars", W.DWORD),
        ("fill", W.DWORD),
        ("flags", W.DWORD),
        ("show", W.WORD),
        ("reserved_size", W.WORD),
        ("reserved_bytes", C.c_void_p),
        ("stdin", W.HANDLE),
        ("stdout", W.HANDLE),
        ("stderr", W.HANDLE),
    ]


class StartupEx(C.Structure):
    _fields_ = [("startup", Startup), ("attributes", C.c_void_p)]


class ProcessInfo(C.Structure):
    _fields_ = [("process", W.HANDLE), ("thread", W.HANDLE), ("pid", W.DWORD), ("tid", W.DWORD)]


def active_processes(kernel, handle):
    value = Accounting()
    checked(kernel.QueryInformationJobObject(handle, 1, C.byref(value), C.sizeof(value), None))
    return value.active


def job_active(name: str) -> int:
    kernel = api()
    handle = kernel.OpenJobObjectW(0x0004, False, name)
    if not handle:
        if C.get_last_error() == 2:
            return 0
        raise C.WinError(C.get_last_error())
    try:
        return active_processes(kernel, handle)
    finally:
        kernel.CloseHandle(handle)


class Job:
    def __init__(self, name: str):
        self.kernel = api()
        C.set_last_error(0)
        self.handle = checked(self.kernel.CreateJobObjectW(None, name))
        if C.get_last_error() == 183:
            self.kernel.CloseHandle(self.handle)
            raise ValueError("Owned job name already exists")
        self.children: list[ProcessInfo] = []
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            checked(
                self.kernel.SetInformationJobObject(
                    self.handle, 9, C.byref(limits), C.sizeof(limits)
                )
            )
        except BaseException:
            self.kernel.CloseHandle(self.handle)
            raise

    def spawn(self, command: list[str], cwd: str) -> dict:
        size = C.c_size_t()
        self.kernel.InitializeProcThreadAttributeList(None, 1, 0, C.byref(size))
        attributes = C.create_string_buffer(size.value)
        checked(self.kernel.InitializeProcThreadAttributeList(attributes, 1, 0, C.byref(size)))
        startup = StartupEx()
        startup.startup.cb = C.sizeof(startup)
        startup.attributes = C.addressof(attributes)
        info = ProcessInfo()
        try:
            jobs = (W.HANDLE * 1)(self.handle)
            checked(
                self.kernel.UpdateProcThreadAttribute(
                    attributes, 0, 0x2000D, jobs, C.sizeof(jobs), None, None
                )
            )
            checked(
                self.kernel.CreateProcessW(
                    command[0],
                    C.create_unicode_buffer(subprocess.list2cmdline(command)),
                    None,
                    None,
                    False,
                    0x8000000 | 0x80000 | 4,
                    None,
                    cwd,
                    C.byref(startup),
                    C.byref(info),
                )
            )
            self.children.append(info)
            return {"pid": info.pid, "created": creation_time(self.kernel, info.process)}
        finally:
            self.kernel.DeleteProcThreadAttributeList(attributes)

    def resume(self, identity: dict):
        info = next(child for child in self.children if child.pid == identity["pid"])
        if self.kernel.ResumeThread(info.thread) == 0xFFFFFFFF:
            raise C.WinError(C.get_last_error())

    def stop(self):
        import time

        if self.handle is None:
            return
        checked(self.kernel.TerminateJobObject(self.handle, 1))
        deadline = time.monotonic() + 15
        while active_processes(self.kernel, self.handle):
            if time.monotonic() >= deadline:
                raise ValueError("Owned workers have not stopped; keep the device lease")
            time.sleep(0.02)
        for child in self.children:
            remaining = max(0, int((deadline - time.monotonic()) * 1000))
            if self.kernel.WaitForSingleObject(child.process, remaining) != 0:
                raise ValueError("Owned process exit is not confirmed; keep the device lease")
            self.kernel.CloseHandle(child.thread)
            self.kernel.CloseHandle(child.process)
        self.children.clear()
        self.kernel.CloseHandle(self.handle)
        self.handle = None


def host_memory() -> dict:
    class Memory(C.Structure):
        _fields_ = [
            ("length", W.DWORD),
            ("load", W.DWORD),
            *[
                (key, C.c_uint64)
                for key in (
                    "total_physical",
                    "available_physical",
                    "total_commit",
                    "available_commit",
                    "total_virtual",
                    "available_virtual",
                    "extended",
                )
            ],
        ]

    value = Memory()
    value.length = C.sizeof(value)
    checked(api().GlobalMemoryStatusEx(C.byref(value)))
    return {
        key: getattr(value, key)
        for key in ("total_physical", "available_physical", "total_commit", "available_commit")
    }


def process_memory(identity: dict) -> dict:
    class Counters(C.Structure):
        _fields_ = [
            ("size", W.DWORD),
            ("faults", W.DWORD),
            *[
                (key, C.c_size_t)
                for key in (
                    "peak_working",
                    "working",
                    "peak_paged",
                    "paged",
                    "peak_nonpaged",
                    "nonpaged",
                    "commit",
                    "peak_commit",
                    "private",
                )
            ],
        ]

    kernel = api()
    function = C.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
    function.argtypes, function.restype = [W.HANDLE, C.c_void_p, W.DWORD], W.BOOL
    handle = checked(kernel.OpenProcess(0x1000 | 0x0010, False, identity["pid"]))
    try:
        if creation_time(kernel, handle) != identity["created"]:
            raise ValueError("Worker process identity changed")
        value = Counters()
        value.size = C.sizeof(value)
        checked(function(handle, C.byref(value), C.sizeof(value)))
        return {
            key: getattr(value, key)
            for key in ("peak_working", "working", "peak_commit", "private")
        }
    finally:
        kernel.CloseHandle(handle)
