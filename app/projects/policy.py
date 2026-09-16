import re
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.security.filesystem_policy import safe_component

PROJECT_TOOLS = frozenset({"list_projects", "open_project", "get_project_info", "start_project", "list_running_projects", "stop_project"})


class ProjectArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    project: str = Field(min_length=1, max_length=120)

    @field_validator("project")
    @classmethod
    def safe_name(cls, value):
        safe_component(value)
        if any(c in value for c in ";&`$(){}"):
            raise ValueError("Invalid project name")
        return value


class ListArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    root: str = "all"

    @field_validator("root")
    @classmethod
    def approved_identifier(cls, value):
        if value != "all" and not re.fullmatch(r"project_[1-9][0-9]*", value):
            raise ValueError("Only explicitly approved project roots are allowed")
        return value


def validate_arguments(tool, args):
    if tool == "list_projects": ListArgs.model_validate(args)
    elif tool == "list_running_projects":
        if args: raise ValueError("Unexpected arguments")
    else: ProjectArgs.model_validate(args)


def project_request(text):
    from app.models import ToolRequest
    value = text.strip().rstrip(".!?")
    if re.fullmatch(r"list (?:my )?projects", value, re.I):
        return ToolRequest(tool_name="list_projects")
    match = re.fullmatch(r"list projects in (.*)", value, re.I)
    if match: return ToolRequest(tool_name="list_projects", arguments={"root": match[1]})
    if re.fullmatch(r"(?:show|list) running projects", value, re.I):
        return ToolRequest(tool_name="list_running_projects")
    match = re.fullmatch(r"show project information for (.+)", value, re.I)
    if match: return ToolRequest(tool_name="get_project_info", arguments={"project": match[1]})
    for pattern in (r"(open|start|run|stop) (?:the )?(.+) project", r"(open|start|run|stop) project (.+)"):
        match = re.fullmatch(pattern, value, re.I)
        if match:
            return ToolRequest(tool_name={"run": "start"}.get(match[1].lower(), match[1].lower()) + "_project", arguments={"project": match[2]})
    return None
