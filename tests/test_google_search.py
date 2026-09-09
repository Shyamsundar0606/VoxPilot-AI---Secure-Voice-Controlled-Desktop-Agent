import json
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

from app.agent.executor import CommandExecutor
from app.agent.router import CommandRouter
from app.agent.schemas import parse_intent
from app.agent.intent_planner import IntentPlanner
from app.models import ToolRequest
from app.security.validators import validate_search_query, validate_tool_request
from app.tools.registry import ToolRegistry
from app.tools.web_tools import WebTools


@pytest.mark.parametrize("phrase", ["Search Google for EPITA", "Google EPITA", "Open Google and search for EPITA", "Find EPITA on Google", "search GOOGLE for EPITA"])
def test_clear_search_is_deterministic_and_uses_fixed_endpoint(phrase):
    opener, planner = Mock(return_value=True), Mock()
    registry = ToolRegistry(web=WebTools(opener))
    result = CommandExecutor(registry=registry, planner=planner).execute(phrase)
    assert result.result_message == "Searching Google for EPITA."
    assert result.selected_tool == "search_google"
    opener.assert_called_once_with("https://www.google.com/search?q=EPITA")
    planner.plan.assert_not_called()


@pytest.mark.parametrize("query", ["EPITA Paris", "C++ & Python", "école française", "x; echo hello | calc & $(whoami) `test`", "EPITA? a=b#fragment"])
def test_special_characters_remain_encoded_search_data(query):
    opener = Mock(return_value=True)
    result = WebTools(opener).search_google(query)
    assert result.success
    url = opener.call_args.args[0]
    parsed = urlsplit(url)
    assert (parsed.scheme, parsed.netloc, parsed.path, parsed.fragment) == ("https", "www.google.com", "/search", "")
    assert parse_qs(parsed.query) == {"q": [query]}
    assert " " not in url and "|" not in url and "`" not in url


@pytest.mark.parametrize("query", ["", "   ", "x" * 301, None, 12, "line\nbreak", "line\rbreak", "null\x00byte", "tab\ttext", "hidden\x7f", "line\u2028break", "https://evil.com", "http://google.com", "www.evil.com", "javascript:alert(1)", "//evil.com", "data:text/html,evil"])
def test_invalid_queries_rejected_at_all_boundaries(query):
    with pytest.raises(ValueError): validate_search_query(query)
    with pytest.raises(ValueError): validate_tool_request(ToolRequest(tool_name="search_google", arguments={"query": query}))
    opener = Mock()
    assert not WebTools(opener).search_google(query).success
    opener.assert_not_called()


def structured(query="EPITA", **extra):
    return json.dumps(dict(intent="search_google", arguments={"query": query, **extra}, confidence=0.95, requires_confirmation=False))


def test_valid_model_search_schema():
    request = parse_intent(structured()).to_request()
    assert request == ToolRequest(tool_name="search_google", arguments={"query": "EPITA"})


@pytest.mark.parametrize("extra", [{"domain": "evil.com"}, {"url": "https://evil.com"}, {"scheme": "javascript"}, {"executable": "cmd.exe"}])
def test_model_cannot_choose_destination_or_executable(extra):
    with pytest.raises(ValueError): parse_intent(structured(**extra))


@pytest.mark.parametrize("query", ["https://evil.com", "javascript:alert(1)", "", "x" * 301, "a\nb"])
def test_invalid_model_query_rejected(query):
    with pytest.raises(ValueError): parse_intent(structured(query))


def test_natural_fallback_only_for_unmatched_phrase():
    client = Mock(complete=Mock(return_value=structured()))
    opener = Mock(return_value=True)
    executor = CommandExecutor(registry=ToolRegistry(web=WebTools(opener)), planner=IntentPlanner(client))
    assert executor.execute("Could you look up EPITA on Google please?").selected_tool == "search_google"
    client.complete.assert_called_once()
    opener.assert_called_once_with("https://www.google.com/search?q=EPITA")


def test_model_cannot_invent_query():
    client = Mock(complete=Mock(return_value=structured("unrelated")))
    assert IntentPlanner(client).plan("Could you look up EPITA on Google please?").request is None


@pytest.mark.parametrize("phrase", ["Google", "Search Google for", "Search Google for https://evil.com", "Google javascript:alert(1)", "Google " + "x" * 301, "Google a\nb"])
def test_invalid_deterministic_query_cannot_fall_back_to_model(phrase):
    planner, registry = Mock(), Mock()
    result = CommandExecutor(registry=registry, planner=planner).execute(phrase)
    assert result.selected_tool is None
    registry.execute.assert_not_called(); planner.plan.assert_not_called()


def test_open_google_unchanged():
    request = CommandRouter().route("Open Google").tool_request
    assert request == ToolRequest(tool_name="open_url", arguments={"url_name": "google"})


@pytest.mark.parametrize("text", ["Delete my files", "Run PowerShell", "Format the drive", "Shut down the laptop"])
def test_dangerous_actions_remain_rejected(text):
    client, registry = Mock(), Mock()
    CommandExecutor(registry=registry, planner=IntentPlanner(client)).execute(text)
    client.complete.assert_not_called(); registry.execute.assert_not_called()
