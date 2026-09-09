from unittest.mock import Mock

from app.tools.web_tools import WebTools


def test_google_opens_fixed_url_once():
    opener = Mock(return_value=True)
    result = WebTools(opener).open_url("google")
    opener.assert_called_once_with("https://www.google.com")
    assert result.success and result.message == "Google is now open."


def test_arbitrary_url_is_rejected():
    opener = Mock()
    assert not WebTools(opener).open_url("https://example.org").success
    opener.assert_not_called()
