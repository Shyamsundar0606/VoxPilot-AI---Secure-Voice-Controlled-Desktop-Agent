import json
import os
import subprocess
import sys
from pathlib import Path
from threading import RLock
from time import monotonic, time, sleep
from uuid import uuid4
from app.projects.platform import available_bytes


class ProcessManager:
    def __init__(self, max_bytes=262144, max_lines=500, stop_timeout=10, retention=60):
        from app.projects.output import OutputBuffer
        OutputBuffer(max_bytes, max_lines)
        if not 0 < stop_timeout <= 60 or not 0 < retention <= 3600: raise ValueError("Invalid process timeouts")
        self.max_bytes, self.max_lines, self.stop_timeout, self.retention = max_bytes, max_lines, stop_timeout, retention
        self.records, self._lock = {}, RLock()

    def _receive(self, record, timeout=2):
        deadline, data = monotonic() + timeout, bytearray()
        process = record["supervisor"]
        while monotonic() < deadline:
            try:
                count = available_bytes(process.stdout)
                if count:
                    data.extend(os.read(process.stdout.fileno(), min(count, 8192)))
                    if len(data) > self.max_bytes * 8 + 8192: raise ValueError("Invalid supervisor response")
                    if data.endswith(b"\n"):
                        result = json.loads(data)
                        record.update({k: result[k] for k in ("pid", "state", "output")})
                        return
            except EOFError: break
            if process.poll() is not None: break
            sleep(.01)
        if process.poll() is not None:
            record.update(state="completed" if process.returncode == 0 else "unavailable", output="")
            return
        raise ValueError("Project supervisor did not respond. The project may still be running.")

    def _send(self, record, command):
        record["supervisor"].stdin.write(command.encode() + b"\n")
        record["supervisor"].stdin.flush()
        self._receive(record)

    def snapshot(self):
        with self._lock:
            for record in self.records.values():
                if record["supervisor"].poll() is None: self._send(record, "poll")
                else:
                    record.update(state="completed" if record["supervisor"].returncode == 0 else "unavailable", output="")
            rows = [{k: v for k, v in r.items() if k != "supervisor"} for r in self.records.values()]
            for record in self.records.values(): record["output"] = ""
            return rows

    def start(self, plan, cancel):
        with self._lock:
            profile = plan["profile"]
            if len(self.records) >= 100: raise ValueError("Session project limit reached. Restart VoxPilot after projects finish.")
            if any(r["project_id"] == profile["project_id"] and r["state"] != "completed" for r in self.snapshot()) and not profile["allow_duplicate"]:
                raise ValueError("This project is already running.")
            if cancel.is_set(): raise ValueError("Project launch cancelled.")
            startup = subprocess.STARTUPINFO(); startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW; startup.wShowWindow = 0
            # Fixed supervisor code and current interpreter; no user text in argv.
            process = subprocess.Popen([sys.executable, "-I", str(Path(__file__).with_name("supervisor.py"))],
                shell=False, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
                creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=startup,
                env={k: v for k, v in os.environ.items() if k.upper() in {"SYSTEMROOT", "WINDIR"}})
            record = {"id": uuid4().hex, "project_id": profile["project_id"], "name": profile["display_name"],
                      "pid": None, "start_time": time(), "runner": profile["runner"], "state": "starting", "output": "", "supervisor": process}
            self.records[record["id"]] = record
            payload = {"plan": plan, "max_bytes": self.max_bytes, "max_lines": self.max_lines,
                       "stop_timeout": self.stop_timeout, "retention": self.retention}
            process.stdin.write(json.dumps(payload).encode() + b"\n"); process.stdin.flush()
            self._receive(record, 10)
            record["output"] = ""
            if record["pid"] is None: raise ValueError("Project launch failed safely. Check its profile and local dependencies.")
            return record["id"]

    def stop(self, identifier, cancel):
        with self._lock:
            if identifier not in self.records: raise ValueError("Only VoxPilot-tracked projects can be stopped.")
            record = self.records[identifier]
            if cancel.is_set(): raise ValueError("Project stop cancelled.")
            self._send(record, "stop")
            deadline = monotonic() + self.stop_timeout + 3
            while record["state"] == "running" and monotonic() < deadline:
                # Once delivered, the explicitly approved stop completes in the supervisor.
                if cancel.is_set(): return
                sleep(.05); self._send(record, "poll")
            if record["state"] == "running": raise ValueError("Project stopping is still pending.")
            if record["state"] == "stop_unverified": raise ValueError("Docker did not confirm container termination. Check Docker locally.")
            record["output"] = ""

    def close(self):
        with self._lock:
            for record in self.records.values():
                process = record["supervisor"]
                try:
                    process.stdin.write(b"detach\n"); process.stdin.flush()
                except OSError: pass
                process.stdin.close(); process.stdout.close()
                record["output"] = ""
            self.records.clear()
