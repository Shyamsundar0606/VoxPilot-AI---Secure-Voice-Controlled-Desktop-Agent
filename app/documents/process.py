"""Killable parser boundary. Windows Job Object caps memory before parsing."""
import ctypes
import os
from multiprocessing import get_context
from time import monotonic
from app.documents.errors import DocumentError, DocumentFailureCode


def memory_limit(megabytes):
    if os.name != "nt":
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (megabytes * 1024**2,) * 2)
        return None
    from ctypes import wintypes as w
    class Basic(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64), ("flags", w.DWORD),
                    ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t), ("active", w.DWORD),
                    ("affinity", ctypes.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]
    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ("read", "write", "other", "read_bytes", "write_bytes", "other_bytes")]
    class Extended(ctypes.Structure):
        _fields_ = [("basic", Basic), ("io", IO), ("process_memory", ctypes.c_size_t),
                    ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
    kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    info = Extended(); info.basic.flags = 0x100; info.process_memory = megabytes * 1024**2
    if not handle or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)) or not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        if handle: kernel.CloseHandle(handle)
        raise DocumentError(DocumentFailureCode.ISOLATION_UNAVAILABLE)
    return handle  # Held until process exit; never closed while parsing.


def _child(sender, operation, arguments, memory_mb):
    import logging
    logging.disable(logging.CRITICAL)  # Parser diagnostics can contain document data.
    try:
        handle = memory_limit(memory_mb)
        result = operation(*arguments, progress=lambda state, detail: sender.send(("progress", state, detail)))
        sender.send(("result", result))
    except DocumentError as exc:
        sender.send(("error", exc.to_payload()))
    except MemoryError:
        sender.send(("error", DocumentError(DocumentFailureCode.RESOURCE_LIMIT).to_payload()))
    except BaseException:
        sender.send(("error", DocumentError(DocumentFailureCode.UNKNOWN).to_payload()))
    finally:
        sender.close()


def run_isolated(operation, arguments, limits, cancel, progress, timeout=None):
    context = get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_child, args=(sender, operation, arguments, limits.memory_mb), daemon=True)
    started = monotonic()
    try:
        if cancel.is_set(): raise DocumentError(DocumentFailureCode.CANCELLED)
        process.start(); sender.close()
        while True:
            if cancel.is_set(): raise DocumentError(DocumentFailureCode.CANCELLED)
            if monotonic() - started >= (timeout or limits.extraction_timeout):
                raise DocumentError(DocumentFailureCode.EXTRACTION_TIMEOUT)
            if receiver.poll(0.02):
                event = receiver.recv()
                if event[0] == "progress": progress(event[1], event[2])
                elif event[0] == "result": return event[1]
                elif event[0] == "error": raise DocumentError.from_payload(event[1])
                else: raise DocumentError(DocumentFailureCode.UNKNOWN)
            elif not process.is_alive(): raise DocumentError(DocumentFailureCode.WORKER_STOPPED)
    except (OSError, EOFError):
        raise DocumentError(DocumentFailureCode.PROCESS_UNAVAILABLE) from None
    finally:
        if process.pid is not None:
            if process.is_alive(): process.terminate()
            process.join(); process.close()
        receiver.close(); sender.close()
