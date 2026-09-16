import os
import sys
from threading import Event
from time import monotonic, sleep
from unittest.mock import Mock
import pytest
from app.projects.profiles import Profile
from app.projects.processes import ProcessManager
from tests.test_projects import project_env


def wait_state(manager, expected, timeout=8):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        rows = manager.snapshot()
        if rows and rows[0]["state"] == expected: return rows[0]
        sleep(.05)
    raise AssertionError(f"Did not reach {expected}: {rows}")


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Objects")
@pytest.mark.parametrize("ignore_break", [False, True])
def test_owned_process_graceful_and_forced_stop(project_env, ignore_break):
    service, raw, project, _ = project_env
    source = "import time, signal\n"
    if ignore_break: source += "signal.signal(signal.SIGBREAK, signal.SIG_IGN)\n"
    source += "print('fixture ready', flush=True)\ntime.sleep(30)\n"
    (project / "main.py").write_text(source)
    profile = Profile(**{**raw, "executable": sys.executable})
    plan = service.profiles.plan(profile)
    manager = ProcessManager(stop_timeout=.3, retention=2)
    try:
        identifier = manager.start(plan, Event())
        row = wait_state(manager, "running")
        deadline = monotonic() + 5
        while "fixture ready" not in row["output"] and monotonic() < deadline:
            sleep(.05); row = manager.snapshot()[0]
        assert "fixture ready" in row["output"]
        with pytest.raises(ValueError): manager.start(plan, Event())
        with pytest.raises(ValueError): manager.stop("untrusted-pid", Event())
        started = monotonic()
        manager.stop(identifier, Event())
        if ignore_break: assert monotonic() - started >= .25
        assert wait_state(manager, "completed")["pid"] == row["pid"]
    finally:
        for record in list(manager.records.values()):
            if record["state"] == "running": manager.stop(record["id"], Event())
        manager.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Objects")
def test_detach_leaves_finite_fixture_running_and_no_threads(project_env):
    import threading
    import psutil
    service, raw, project, _ = project_env
    (project / "main.py").write_text("import time\nprint('finite fixture', flush=True)\ntime.sleep(1.5)\n")
    manager = ProcessManager(retention=.1)
    before = {t.ident for t in threading.enumerate()}
    identifier = manager.start(service.profiles.plan(Profile(**{**raw, "executable": sys.executable})), Event())
    row = manager.snapshot()[0]; child = psutil.Process(row["pid"])
    supervisor = manager.records[identifier]["supervisor"]
    manager.close()
    assert child.is_running()
    child.wait(timeout=8); supervisor.wait(timeout=8)
    assert {t.ident for t in threading.enumerate()} == before


def test_cancel_before_launch_and_close_never_terminate(project_env):
    service, raw, *_ = project_env
    manager = ProcessManager()
    cancel = Event(); cancel.set()
    with pytest.raises(ValueError): manager.start(service.profiles.plan(Profile(**raw)), cancel)
    assert not manager.records
    process = Mock()
    manager.records["owned"] = {"supervisor": process, "output": "sensitive"}
    manager.close()
    process.terminate.assert_not_called(); process.kill.assert_not_called()


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Objects")
def test_forced_tree_stop_excludes_unrelated_fixture(project_env):
    import subprocess
    import psutil
    service, raw, project, _ = project_env
    child_script = project / "child.py"
    child_script.write_text("import signal,time\nsignal.signal(signal.SIGBREAK,signal.SIG_IGN)\ntime.sleep(20)\n")
    (project / "main.py").write_text("import subprocess,sys,signal,time\nsignal.signal(signal.SIGBREAK,signal.SIG_IGN)\nsubprocess.Popen([sys.executable,'child.py'],shell=False)\nprint('ready',flush=True)\ntime.sleep(20)\n")
    unrelated = subprocess.Popen([sys.executable, str(child_script)], shell=False, creationflags=subprocess.CREATE_NO_WINDOW)
    manager = ProcessManager(stop_timeout=.3, retention=.1)
    try:
        identifier = manager.start(service.profiles.plan(Profile(**{**raw, "executable": sys.executable})), Event())
        row = manager.snapshot()[0]; root = psutil.Process(row["pid"])
        deadline = monotonic() + 5
        children = []
        while not children and monotonic() < deadline:
            children = root.children(recursive=True); sleep(.05)
        assert children
        manager.stop(identifier, Event())
        for child in children: child.wait(timeout=5)
        assert unrelated.poll() is None
    finally:
        for record in list(manager.records.values()):
            if record["state"] == "running": manager.stop(record["id"], Event())
        manager.close(); unrelated.terminate(); unrelated.wait(timeout=5)


def test_subprocess_calls_explicitly_disable_shell():
    import ast
    from pathlib import Path
    for name in ("platform.py", "processes.py"):
        tree = ast.parse((Path(__file__).parents[1] / "app" / "projects" / name).read_text(encoding="utf-8"))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "Popen"]
        assert calls
        for node in calls:
            shell = next(k.value for k in node.keywords if k.arg == "shell")
            assert isinstance(shell, ast.Constant) and shell.value is False
