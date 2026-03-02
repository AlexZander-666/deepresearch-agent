from types import SimpleNamespace

from services.model_only_session_service import ModelOnlyDBSessionService


def _part(*, text=None, function_call=None, function_response=None):
    return SimpleNamespace(
        text=text,
        function_call=function_call,
        function_response=function_response,
    )


def test_sanitize_event_parts_keeps_text_and_removes_tool_parts():
    event = SimpleNamespace(
        content=SimpleNamespace(
            parts=[
                _part(text="hello"),
                _part(function_call={"name": "web_search"}),
                _part(function_response={"name": "web_search"}),
            ]
        )
    )

    sanitized = ModelOnlyDBSessionService._sanitize_event_parts(event)

    assert sanitized is event
    assert len(sanitized.content.parts) == 1
    assert sanitized.content.parts[0].text == "hello"


def test_sanitize_event_parts_drops_event_with_only_tool_parts():
    event = SimpleNamespace(
        content=SimpleNamespace(
            parts=[
                _part(function_call={"name": "create_tasks"}),
                _part(function_response={"name": "create_tasks"}),
            ]
        )
    )

    sanitized = ModelOnlyDBSessionService._sanitize_event_parts(event)

    assert sanitized is None
