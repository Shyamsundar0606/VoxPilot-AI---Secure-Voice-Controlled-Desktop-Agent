import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import Mock
import pytest

from app.filesystem.roots import ApprovedRoots
from app.models import ToolRequest, Status
from app.projects.discovery import discover, DiscoveryLimits, MANIFESTS
from app.projects.profiles import Profile, Profiles, compose_metadata
from app.projects.service import ProjectService
from app.projects.output import OutputBuffer
from app.agent.executor import CommandExecutor
from app.agent.router import CommandRouter
from app.agent.schemas import parse_intent


@pytest.fixture
def project_env():
    with TemporaryDirectory(prefix="voxpilot-project-test-", dir=Path.cwd()) as directory:
        base = Path(directory); approved = base / "Approved"; approved.mkdir()
        project = approved / "VoxPilot"; project.mkdir()
        (project / "requirements.txt").write_text("")
        (project / "main.py").write_text("print('safe fixture')\n")
        platform = Mock(fixed_drive=Mock(return_value=True))
        roots = ApprovedRoots(platform=platform, roots={"project_1": approved, "documents": base})
        executable = base / "python.exe"; executable.write_bytes(b"MZfixture")
        raw = dict(project_id="voxpilot", display_name="VoxPilot", root="project_1", directory="VoxPilot",
                   runner="python_script", executable=str(executable), entry_point="main.py", arguments=[])
        profiles = Profiles(roots, base / "launch-profiles.json")
        profiles.save(raw, Event())
        processes = Mock(snapshot=Mock(return_value=[]))
        service = ProjectService(roots, profiles, processes, isolated=False)
        yield service, raw, project, approved


def request(tool, **kwargs): return ToolRequest(tool_name=tool, arguments=kwargs)


@pytest.mark.parametrize("phrase,tool,args", [
    ("List my projects", "list_projects", {}), ("List projects in project_1", "list_projects", {"root": "project_1"}),
    ("Open the CyberGuard project", "open_project", {"project": "CyberGuard"}),
    ("Open project VoxPilot", "open_project", {"project": "VoxPilot"}),
    ("Show project information for CyberGuard", "get_project_info", {"project": "CyberGuard"}),
    ("Start the CyberGuard project", "start_project", {"project": "CyberGuard"}),
    ("Run project VoxPilot", "start_project", {"project": "VoxPilot"}),
    ("Show running projects", "list_running_projects", {}),
    ("Stop the CyberGuard project", "stop_project", {"project": "CyberGuard"}),
])
def test_deterministic_commands(phrase, tool, args, project_env):
    service, *_ = project_env
    planner = Mock()
    routed = CommandRouter().route(phrase)
    assert routed.tool_request == request(tool, **args)
    CommandExecutor(projects=service, planner=planner).execute(phrase)
    planner.plan.assert_not_called()


@pytest.mark.parametrize("manifest", MANIFESTS)
def test_manifest_discovery_metadata_only(project_env, manifest, monkeypatch):
    service, _, project, _ = project_env
    (project / "requirements.txt").unlink(); (project / manifest).write_text("invalid content must not be read")
    monkeypatch.setattr(Path, "read_text", Mock(side_effect=AssertionError("Contents read")))
    result = discover(service.roots, DiscoveryLimits(), Event())
    assert result[0]["name"] == "VoxPilot" and MANIFESTS[manifest] in result[0]["type"]


def test_approved_only_sorted_unicode_and_ignored(project_env):
    service, _, project, approved = project_env
    for name in ["École", "Alpha", "node_modules", "build", "dist", "venv", ".git", ".cache"]:
        folder = approved / name; folder.mkdir(); (folder / "package.json").write_text("{}")
    (approved.parent / "package.json").write_text("{}")
    rows = discover(service.roots, DiscoveryLimits(), Event())
    assert [r["name"] for r in rows] == ["Alpha", "VoxPilot", "École"]
    assert all(r["root"] == "project_1" for r in rows)


def test_discovery_bounds_and_cancel(project_env):
    service, _, _, _ = project_env
    assert not discover(service.roots, DiscoveryLimits(depth=0), Event())
    assert not discover(service.roots, DiscoveryLimits(directories=1), Event())
    assert len(discover(service.roots, DiscoveryLimits(results=1), Event())) == 1
    with pytest.raises(ValueError): discover(service.roots, DiscoveryLimits(timeout=1), Event(), clock=Mock(side_effect=[0, 2]))
    cancel = Event(); cancel.set()
    with pytest.raises(ValueError): discover(service.roots, DiscoveryLimits(), cancel)


@pytest.mark.parametrize("change", [{"root": "documents"}, {"directory": "../other"}, {"directory": "C:\\outside"},
    {"runner": "shell"}, {"entry_point": "../main.py"}, {"entry_point": "C:\\outside.py"},
    {"arguments": ["&&", "evil"]}, {"arguments": ["x\nshutdown"]}, {"executable": "python.exe"},
    {"environment_allowlist": ["API_TOKEN"]}, {"environment_allowlist": ["PATH"]}, {"unexpected": "value"}])
def test_invalid_profiles(project_env, change):
    service, raw, *_ = project_env
    with pytest.raises((ValueError, OSError)): service.profiles.save({**raw, **change}, Event())


@pytest.mark.parametrize("entry", ["pip", "os", "main;evil", "main.__import__('os')", "..main", "-c"])
def test_invalid_module(project_env, entry):
    service, raw, *_ = project_env
    with pytest.raises((ValueError, OSError)): service.profiles.plan(Profile(**{**raw, "runner": "python_module", "entry_point": entry}))


def test_valid_module_fixed_args_environment(project_env, monkeypatch):
    service, raw, project, _ = project_env
    monkeypatch.setenv("API_TOKEN", "PRIVATE_SENTINEL")
    monkeypatch.setenv("LANG", "en_US")
    plan = service.profiles.plan(Profile(**{**raw, "runner": "python_module", "entry_point": "main", "arguments": ["--port", "8080"], "environment_allowlist": ["LANG"]}))
    assert plan["argv"][1:] == ["-m", "main", "--port", "8080"]
    assert plan["environment"] == {"LANG": "en_US"}
    assert "PRIVATE_SENTINEL" not in json.dumps(plan)


def test_npm_fixed_existing_script(project_env):
    service, raw, project, _ = project_env
    node = Path(raw["executable"]).with_name("node.exe"); node.write_bytes(b"MZfixture")
    cli = node.parent / "npm-cli.js"; cli.write_text("fixture")
    (project / "package.json").write_text(json.dumps({"scripts": {"dev": "vite"}}))
    profile = {**raw, "runner": "npm_script", "entry_point": "dev", "executable": str(node), "npm_cli": str(cli)}
    assert service.profiles.plan(Profile(**profile))["argv"][2:] == ["--ignore-scripts", "run-script", "dev"]
    for change in ({"entry_point": "missing"}, {"arguments": ["--anything"]}, {"npm_cli": "relative.js"}):
        with pytest.raises(ValueError): service.profiles.plan(Profile(**{**profile, **change}))


@pytest.mark.parametrize("option", ["privileged", "volumes", "build", "command", "entrypoint", "env_file", "environment", "network_mode", "pid", "devices", "ports", "extends"])
def test_compose_rejects_unsafe_options(option):
    spec = {"services": {"web": {"image": "nginx@sha256:" + "a" * 64, option: True}}}
    with pytest.raises(ValueError): compose_metadata(json.dumps(spec))


def test_compose_fixed_local_endpoint(project_env):
    service, raw, project, _ = project_env
    docker = Path(raw["executable"]).with_name("docker.exe"); docker.write_bytes(b"MZfixture")
    (project / "compose.yaml").write_text(json.dumps({"services": {"web": {"image": "nginx@sha256:" + "a" * 64}}}))
    profile = Profile(**{**raw, "runner": "docker_compose", "entry_point": "compose.yaml", "executable": str(docker)})
    plan = service.profiles.plan(profile)
    assert plan["argv"][1:3] == ["--host", "npipe:////./pipe/docker_engine"]
    assert plan["argv"][-5:] == ["up", "--no-build", "--pull", "never", "--abort-on-container-exit"]
    assert "volumes" not in plan["compose"]


def test_confirmation_binding_replay(project_env):
    service, raw, *_ = project_env
    result = service.execute(request("start_project", project="VoxPilot"))
    assert result.confirmation and not result.store_history
    service.processes.start.assert_not_called()
    c = result.confirmation
    assert service.confirm(c["token"], c["hash"]).status == Status.COMPLETED
    service.processes.start.assert_called_once()
    assert service.confirm(c["token"], c["hash"]).status == Status.FAILED


@pytest.mark.parametrize("mutation", ["hash", "token", "expired", "cancel", "profile", "file"])
def test_changed_expired_mismatched_confirmation(project_env, mutation):
    service, raw, project, _ = project_env
    clock = [0]; service.clock = lambda: clock[0]
    c = service.execute(request("start_project", project="VoxPilot")).confirmation
    if mutation == "hash": c["hash"] = "different"
    if mutation == "token": c["token"] = "different"
    if mutation == "expired": clock[0] = 31
    if mutation == "cancel": service.cancel()
    if mutation == "profile": service.profiles.save({**raw, "arguments": ["changed"]}, Event())
    if mutation == "file": (project / "main.py").write_text("print('changed')")
    assert service.confirm(c["token"], c["hash"]).status == Status.FAILED
    service.processes.start.assert_not_called()


def test_ambiguity_numbered_selection(project_env):
    service, _, _, approved = project_env
    nested = approved / "Other" / "VoxPilot"; nested.mkdir(parents=True); (nested / "Cargo.toml").write_text("")
    result = service.execute(request("open_project", project="VoxPilot"))
    assert len(result.document_selection["labels"]) == 2
    service.roots.platform.open_folder.assert_not_called()
    assert service.execute(selection=(result.document_selection["token"], 2)).status == Status.COMPLETED
    service.roots.platform.open_folder.assert_called_once()
    assert service.execute(selection=(result.document_selection["token"], 2)).status == Status.FAILED


def test_duplicate_start_and_stop_only_tracked(project_env):
    service, *_ = project_env
    record = dict(id="internal", project_id="voxpilot", name="VoxPilot", pid=123, start_time=456, runner="python_script", state="running", output="")
    service.processes.snapshot.return_value = [record]
    assert service.execute(request("start_project", project="VoxPilot")).confirmation is None
    assert service.execute(request("stop_project", project="123")).confirmation is None
    result = service.execute(request("stop_project", project="VoxPilot"))
    service.processes.stop.assert_not_called()
    assert service.confirm(result.confirmation["token"], result.confirmation["hash"]).status == Status.COMPLETED
    service.processes.stop.assert_called_once()
    assert service.processes.stop.call_args.args[0] == "internal"


def test_output_bounded_decode_and_secret_redaction():
    output = OutputBuffer(max_bytes=80, max_lines=3)
    output.append(b"API_TO"); output.append(b"KEN=PRIVATE_SENTINEL\n")
    assert "PRIVATE_SENTINEL" not in output.text()
    assert "redacted" in output.text()
    output.append(b"bad \xff\n")
    assert "\ufffd" in output.text()
    output.append(b"line\n" * 1000)
    assert len(output.text().encode()) <= 80 and len(output.lines) <= 3
    output.append(b"x" * 1000)
    assert len(output.pending) <= 80
    output.clear(); assert output.text() == "" and not output.pending


@pytest.mark.parametrize("args", [{"project": "../outside"}, {"project": "x; shutdown"}, {"project": "VoxPilot", "executable": "evil.exe"}, {"pid": 123}])
def test_model_cannot_supply_launch_parameters(args):
    with pytest.raises(ValueError): parse_intent(json.dumps(dict(intent="start_project", arguments=args, confidence=.99, requires_confirmation=False)))


def test_model_cannot_bypass_confirmation():
    parsed = parse_intent(json.dumps(dict(intent="start_project", arguments={"project": "VoxPilot"}, confidence=.99, requires_confirmation=False)))
    assert parsed.requires_confirmation


def test_symlink_and_junction_rejected(project_env, monkeypatch):
    service, raw, project, _ = project_env
    original = Path.is_junction
    monkeypatch.setattr(Path, "is_junction", lambda p: p == project or original(p))
    assert not discover(service.roots, DiscoveryLimits(), Event())
    with pytest.raises(ValueError): service.profiles.plan(Profile(**raw))


def test_shutdown_detaches_not_stop(project_env):
    service, *_ = project_env
    service.close()
    service.processes.close.assert_called_once(); service.processes.stop.assert_not_called()


@pytest.mark.parametrize("tool,args", [("list_projects", {"root": "project_1"}), ("open_project", {"project": "École"}),
    ("get_project_info", {"project": "VoxPilot"}), ("start_project", {"project": "VoxPilot"}),
    ("stop_project", {"project": "VoxPilot"}), ("list_running_projects", {})])
def test_all_project_tool_schemas(tool, args):
    value = dict(intent=tool, arguments=args, confidence=.99, requires_confirmation=False)
    assert parse_intent(json.dumps(value)).to_request() == request(tool, **args)
    value["arguments"]["command"] = "untrusted"
    with pytest.raises(ValueError): parse_intent(json.dumps(value))


def test_ollama_project_name_grounding():
    from app.agent.intent_planner import IntentPlanner
    client = Mock(complete=Mock(return_value=json.dumps(dict(intent="start_project", arguments={"project": "VoxPilot"}, confidence=.99, requires_confirmation=False))))
    planner = IntentPlanner(client)
    assert planner.plan("Please start my VoxPilot project").request.tool_name == "start_project"
    assert planner.plan("Please start my other project").request is None


def test_symlink_rejected(project_env, monkeypatch):
    service, raw, project, _ = project_env
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda p: p == project or original(p))
    assert not discover(service.roots, DiscoveryLimits(), Event())
    with pytest.raises(ValueError): service.profiles.plan(Profile(**raw))


def test_stored_plan_tamper_rejected(project_env):
    service, *_ = project_env
    c = service.execute(request("start_project", project="VoxPilot")).confirmation
    value = list(service._pending)
    plan = json.loads(value[3]); plan["argv"].append("tampered")
    value[3] = json.dumps(plan); service._pending = tuple(value)
    assert service.confirm(c["token"], c["hash"]).status == Status.FAILED
    service.processes.start.assert_not_called()


def test_isolated_discovery_and_timeout(project_env):
    service, *_ = project_env
    service.isolated = True
    assert service.execute(request("list_projects")).project_data["projects"][0]["name"] == "VoxPilot"
    service.limits = DiscoveryLimits(timeout=.001)
    assert service.execute(request("list_projects")).status == Status.FAILED
    cancelled = Event(); cancelled.set()
    assert service.execute(request("list_projects"), cancelled).status == Status.FAILED
