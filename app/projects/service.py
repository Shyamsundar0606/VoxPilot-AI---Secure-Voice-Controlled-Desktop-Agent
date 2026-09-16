import json
import logging
from threading import Event, RLock
from time import monotonic
from uuid import uuid4
from app.models import ExecutionResult, Status, ToolRequest
from app.projects.discovery import discover, DiscoveryLimits
from app.projects.policy import validate_arguments
from app.projects.profiles import Profiles, digest
from app.projects.processes import ProcessManager

logger = logging.getLogger(__name__)


def outcome(message, success=True, **kwargs):
    return ExecutionResult(original_command="[Project operation]", normalized_command="", selected_tool="project_operation",
        status=Status.COMPLETED if success else Status.FAILED, result_message=message, store_history=False, **kwargs)


def _discover_child(configuration, limits, root, progress):
    from app.filesystem.roots import ApprovedRoots
    roots, path = configuration
    return discover(ApprovedRoots(path, roots=roots), limits, Event(), root)


class ProjectService:
    def __init__(self, roots, profiles=None, processes=None, limits=None, timeout=30, clock=monotonic, isolated=True):
        if not 0 < timeout <= 120: raise ValueError("Invalid project confirmation timeout")
        self.roots, self.profiles = roots, profiles or Profiles(roots)
        self.processes, self.limits = processes or ProcessManager(), limits or DiscoveryLimits()
        self.timeout, self.clock, self.isolated = timeout, clock, isolated
        self._pending = self._selection = None
        self._lock = RLock()

    def cancel(self):
        with self._lock: self._pending = self._selection = None

    def discover(self, cancel, root="all"):
        if not self.isolated: return discover(self.roots, self.limits, cancel, root)
        from app.documents.process import run_isolated
        from app.documents.limits import PdfLimits
        return run_isolated(_discover_child, (self.roots.configuration(), self.limits, root),
            PdfLimits(), cancel, lambda *_: None, timeout=self.limits.timeout)

    def execute(self, request=None, cancel_event=None, selection=None):
        cancel = cancel_event or Event()
        try:
            if cancel.is_set(): return outcome("Project operation cancelled.", False)
            if selection:
                token, number = selection
                with self._lock:
                    pending, self._selection = self._selection, None
                if not pending or token != pending[0] or self.clock() >= pending[1] or type(number) is not int or not 1 <= number <= len(pending[3]):
                    return outcome("Project selection expired or was cancelled.", False)
                request, target = ToolRequest.model_validate_json(pending[2]), pending[3][number - 1]
                return self._act(request.tool_name, target, cancel)
            self.cancel()
            validate_arguments(request.tool_name, request.arguments)
            if request.tool_name == "list_running_projects":
                rows = self.processes.snapshot()
                text = "\n".join(f"{r['name']} — {r['runner']} — {r['state']} — PID {r['pid']}" for r in rows) or "No projects have been launched by this session."
                return outcome(text, project_data={"running": rows})
            if request.tool_name == "stop_project":
                name = request.arguments["project"].casefold()
                rows = [r for r in self.processes.snapshot() if r["state"] == "running" and name in {r["name"].casefold(), r["project_id"].casefold()}]
                if not rows: return outcome("No matching VoxPilot-tracked project is running.", False)
                if len(rows) == 1: return self._stop_proposal(rows[0], cancel)
                token = uuid4().hex
                with self._lock: self._selection = (token, self.clock() + self.timeout, request.model_dump_json(), tuple({"tracked": r} for r in rows))
                return outcome("Choose the tracked project instance to stop.", document_selection={"kind": "project", "token": token,
                    "timeout": self.timeout, "labels": [f"{r['name']} — instance {r['id']} — PID {r['pid']}" for r in rows]})
            items = self.discover(cancel, request.arguments.get("root", "all"))
            profiles = self.profiles.load()
            for item in items:
                item["profiles"] = [p.project_id for p in profiles if p.root == item["root"] and p.directory == item["relative"]]
                if item["profiles"]: item["actions"] = ["open", "info", "start", "stop"]
            if request.tool_name == "list_projects":
                text = "\n".join(f"{i + 1}. {p['name']} — {p['root']}/{p['relative']} — {p['type']} — {', '.join(p['actions'])}" for i, p in enumerate(items)) or "No projects found in explicitly approved project folders."
                return outcome(text, project_data={"projects": items})
            name = request.arguments["project"].casefold()
            matches = [p for p in items if p["name"].casefold() == name or any(profile.project_id.casefold() == name or profile.display_name.casefold() == name for profile in profiles if profile.project_id in p["profiles"])]
            if not matches: return outcome("No matching project was found in approved project folders.", False)
            if len(matches) > 1:
                token = uuid4().hex
                with self._lock: self._selection = (token, self.clock() + self.timeout, request.model_dump_json(), tuple(matches))
                return outcome("Choose the exact project from the numbered approved locations.", document_selection={
                    "kind": "project", "token": token, "timeout": self.timeout,
                    "labels": [f"{p['name']} — {p['root']}/{p['relative']}" for p in matches]})
            return self._act(request.tool_name, matches[0], cancel)
        except Exception:
            logger.info("Project operation rejected: tool=%s", getattr(request, "tool_name", "selection"))
            return outcome("Project operation could not be completed safely. Check approval, profile configuration and discovery limits.", False)

    def _act(self, tool, target, cancel):
        if tool == "stop_project": return self._stop_proposal(target["tracked"], cancel)
        path = self.roots.resolve(target["root"], target["relative"])
        if cancel.is_set(): return outcome("Project operation cancelled.", False)
        if tool == "open_project":
            self.roots.platform.open_folder(path)
            return outcome("Opened project " + target["name"] + ".")
        if tool == "get_project_info":
            return outcome(f"{target['name']}\nApproved root: {target['root']}\nRelative directory: {target['relative']}\nType: {target['type']}\nProfiles: {', '.join(target['profiles']) or 'none'}")
        profiles = [p for p in self.profiles.load() if p.project_id in target["profiles"]]
        if len(profiles) != 1: return outcome("Select one explicit launch profile for this project before starting or stopping it.", False)
        profile = profiles[0]
        if tool != "start_project": return outcome("Unsupported project action.", False)
        plan = self.profiles.plan(profile)
        running = self.processes.snapshot()
        if not profile.allow_duplicate and any(r["project_id"] == profile.project_id and r["state"] != "completed" for r in running):
            return outcome("This project is already running or its state is unavailable.", False)
        details = f"Start {plan['name']}\nProject directory: {plan['directory']}\nRunner: {plan['runner']}\nExecutable: {plan['argv'][0]}\nFixed arguments: {json.dumps(plan['argv'][1:], ensure_ascii=False)}\nWorking directory: {plan['cwd']}\nEnvironment names: {', '.join(plan['environment']) or 'none'}"
        raw, token = json.dumps(plan, sort_keys=True, ensure_ascii=False), uuid4().hex
        with self._lock:
            if cancel.is_set(): return outcome("Project operation cancelled.", False)
            self._pending = (token, self.clock() + self.timeout, tool, raw, digest(plan))
        return outcome("Review this exact project plan, then say Yes or No.", confirmation={"kind": "project", "token": token,
            "hash": digest(plan), "details": details, "timeout": self.timeout})

    def _stop_proposal(self, record, cancel):
        plan = {k: record[k] for k in ("id", "project_id", "pid", "start_time")}
        token = uuid4().hex
        with self._lock:
            if cancel.is_set(): return outcome("Project stop cancelled.", False)
            self._pending = (token, self.clock() + self.timeout, "stop_project", json.dumps(plan, sort_keys=True), digest(plan))
        return outcome("Review the tracked project before confirming its stop.", confirmation={"kind": "project", "token": token,
            "hash": digest(plan), "timeout": self.timeout,
            "details": f"Stop {record['name']}\nRunner: {record['runner']}\nTracked instance: {record['id']}\nPID: {record['pid']}\nGraceful stop, then force only this tracked tree if needed."})

    def confirm(self, token, plan_hash, cancel_event=None):
        cancel = cancel_event or Event()
        with self._lock: pending, self._pending = self._pending, None
        try:
            if not pending or token != pending[0] or self.clock() >= pending[1] or plan_hash != pending[4] or cancel.is_set():
                logger.info("Project confirmation rejected: inactive or mismatched")
                return outcome("Project confirmation expired, mismatched or was cancelled.", False)
            _, _, tool, raw, expected = pending
            plan = json.loads(raw)
            if digest(plan) != expected: return outcome("Project plan changed. Request a new plan.", False)
            if tool == "start_project":
                profiles = [p for p in self.profiles.load() if p.project_id == plan["profile"]["project_id"]]
                if len(profiles) != 1 or digest(self.profiles.plan(profiles[0], instance=plan["instance"])) != expected:
                    return outcome("Project profile or launch files changed. Request a new plan.", False)
                self.processes.start(plan, cancel)
                logger.info("Project confirmation accepted: start_project")
                return outcome("Project started.")
            current = [r for r in self.processes.snapshot() if r["id"] == plan["id"]]
            if len(current) != 1 or any(current[0][k] != v for k, v in plan.items()):
                return outcome("Tracked project changed. Request stopping again.", False)
            self.processes.stop(plan["id"], cancel)
            logger.info("Project confirmation accepted: stop_project")
            return outcome("Project stop requested." if cancel.is_set() else "Project stopped.")
        except Exception:
            logger.info("Project confirmation rejected")
            return outcome("Project action failed safely. Review its profile and current state before retrying.", False)

    def close(self):
        self.cancel(); self.processes.close()
