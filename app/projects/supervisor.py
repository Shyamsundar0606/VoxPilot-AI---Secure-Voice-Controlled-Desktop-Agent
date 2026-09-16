"""Private, detached lifetime owner. No network, files, or arbitrary command API.

Launched by ProcessManager with a validated plan over an inherited pipe. Once
the UI disconnects, output is discarded and the supervisor exits with its job.
"""
import json
import os
import signal
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.projects.platform import OwnedJob, available_bytes
from app.projects.output import OutputBuffer


def main():
    raw = sys.stdin.buffer.readline(131073)
    if len(raw) > 131072: return 1
    payload = json.loads(raw)
    job = OwnedJob()
    buffer = OutputBuffer(payload["max_bytes"], payload["max_lines"])
    process = job.launch(payload["plan"])
    linked, stop_at, finished_at, docker_stop, uncertain = True, None, None, None, False
    incoming = bytearray()
    def send(value):
        nonlocal linked
        if linked:
            try:
                sys.stdout.write(json.dumps(value) + "\n"); sys.stdout.flush()
            except (OSError, BrokenPipeError): linked = False
    send({"pid": process.pid, "state": "running", "output": ""})
    while True:
        try:
            count = available_bytes(process.stdout)
            if count:
                data = os.read(process.stdout.fileno(), min(count, 8192))
                if linked: buffer.append(data)
        except EOFError: pass
        if docker_stop is not None:
            try:
                count = available_bytes(docker_stop.stdout)
                if count:
                    data = os.read(docker_stop.stdout.fileno(), min(count, 8192))
                    if linked: buffer.append(data)
            except EOFError: pass
        active = job.active()
        if not active and finished_at is None:
            finished_at = time.monotonic()
            buffer.append(b"\n")
        if stop_at is not None and active and time.monotonic() >= stop_at:
            uncertain = bool(payload["plan"].get("compose"))
            job.force(); stop_at = None
        if linked:
            try:
                count = available_bytes(sys.stdin.buffer)
                if count: incoming.extend(os.read(sys.stdin.fileno(), min(count, 1024)))
                if len(incoming) > 4096: raise EOFError()
                while b"\n" in incoming:
                    command, _, tail = incoming.partition(b"\n"); incoming[:] = tail
                    if command == b"stop" and active and stop_at is None:
                        if payload["plan"].get("compose"):
                            stop_plan = dict(payload["plan"])
                            argv = stop_plan["argv"]
                            stop_plan["argv"] = argv[:argv.index("up")] + ["stop", "--timeout", str(max(1, int(payload["stop_timeout"])))]
                            docker_stop = job.launch(stop_plan)
                        else:
                            try: process.send_signal(signal.CTRL_BREAK_EVENT)
                            except OSError: pass
                        stop_at = time.monotonic() + payload["stop_timeout"] + (2 if docker_stop else 0)
                    elif command == b"detach": linked = False
                    elif command != b"poll": continue
                    state = "running" if active else ("stop_unverified" if uncertain or (docker_stop is not None and docker_stop.poll() not in (None, 0)) else "completed")
                    send({"pid": process.pid, "state": state, "output": buffer.text()})
            except EOFError: linked = False
        if not linked: buffer.clear()
        if finished_at is not None and time.monotonic() - finished_at >= payload["retention"]:
            buffer.clear()
        if not active and (not linked or time.monotonic() - finished_at >= payload["retention"]): break
        time.sleep(.02)
    job.close(); process.stdout.close(); process.wait()
    return 1 if uncertain else 0


if __name__ == "__main__":
    try: raise SystemExit(main())
    except Exception: raise SystemExit(1)
