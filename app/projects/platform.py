"""Windows-only process containment; no attachment to pre-existing processes."""
import ctypes
import os
import subprocess


def available_bytes(stream):
    import msvcrt
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.PeekNamedPipe.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.c_void_p, ctypes.POINTER(w.DWORD), ctypes.c_void_p]
    available = w.DWORD()
    if not kernel.PeekNamedPipe(msvcrt.get_osfhandle(stream.fileno()), None, 0, None, ctypes.byref(available), None):
        raise EOFError()
    return available.value


class OwnedJob:
    def __init__(self):
        if os.name != "nt": raise ValueError("Project launching requires Windows 11")
        from ctypes import wintypes as w
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        declarations = {
            "CreateJobObjectW": ([ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
            "AssignProcessToJobObject": ([w.HANDLE, w.HANDLE], w.BOOL),
            "TerminateJobObject": ([w.HANDLE, w.UINT], w.BOOL),
            "QueryInformationJobObject": ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p], w.BOOL),
            "ResumeThread": ([w.HANDLE], w.DWORD), "CloseHandle": ([w.HANDLE], w.BOOL),
        }
        for name, (args, result) in declarations.items():
            fn = getattr(self.kernel, name); fn.argtypes, fn.restype = args, result
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle: raise OSError("Cannot create process containment")

    def launch(self, plan):
        # This method runs only in the single-threaded, private supervisor.
        # Interpose at CreateProcess so the child cannot run before job assignment.
        import _winapi
        original = _winapi.CreateProcess
        def create(*args):
            args = list(args); args[5] |= 0x4  # CREATE_SUSPENDED
            hp, ht, pid, tid = original(*args)
            try:
                if not self.kernel.AssignProcessToJobObject(self.handle, hp): raise OSError("Job assignment failed")
                if self.kernel.ResumeThread(ht) == 0xFFFFFFFF: raise OSError("Resume failed")
                return hp, ht, pid, tid
            except BaseException:
                _winapi.TerminateProcess(hp, 1)
                _winapi.CloseHandle(ht); _winapi.CloseHandle(hp)
                raise
        _winapi.CreateProcess = create
        try:
            process = subprocess.Popen(plan["argv"], cwd=plan["cwd"], env=plan["environment"], shell=False,
                stdin=subprocess.PIPE if plan.get("compose") else subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            if plan.get("compose"):
                process.stdin.write(plan["compose"].encode("utf-8")); process.stdin.close()
            return process
        finally: _winapi.CreateProcess = original

    def active(self):
        from ctypes import wintypes as w
        class Accounting(ctypes.Structure):
            _fields_ = [("user", ctypes.c_int64), ("kernel", ctypes.c_int64), ("period_user", ctypes.c_int64),
                        ("period_kernel", ctypes.c_int64), ("faults", w.DWORD), ("total", w.DWORD),
                        ("active", w.DWORD), ("terminated", w.DWORD)]
        info = Accounting()
        if not self.kernel.QueryInformationJobObject(self.handle, 1, ctypes.byref(info), ctypes.sizeof(info), None):
            raise OSError("Cannot query owned job")
        return info.active

    def force(self):
        if not self.kernel.TerminateJobObject(self.handle, 1): raise OSError("Cannot stop owned job")

    def close(self):
        if self.handle: self.kernel.CloseHandle(self.handle); self.handle = None
