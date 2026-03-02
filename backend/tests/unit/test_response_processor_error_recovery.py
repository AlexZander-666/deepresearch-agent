from agentpress.response_processor import (
    _extract_missing_tools_dict_function_name,
    _is_recoverable_streaming_error,
    _is_tool_call_allowed,
    _should_stop_repeated_stream_tool_call,
)


def test_extract_missing_tools_dict_function_name_with_named_function() -> None:
    error_message = "Function create_tasks is not found in the tools_dict."
    assert _extract_missing_tools_dict_function_name(error_message) == "create_tasks"


def test_extract_missing_tools_dict_function_name_with_empty_function() -> None:
    error_message = "Function  is not found in the tools_dict."
    assert _extract_missing_tools_dict_function_name(error_message) == ""


def test_extract_missing_tools_dict_function_name_non_match() -> None:
    error_message = "something else happened"
    assert _extract_missing_tools_dict_function_name(error_message) is None


def test_is_recoverable_streaming_error_for_api_connection_disconnected() -> None:
    error_message = "litellm.APIConnectionError: Ollama_chatException - Server disconnected"
    assert _is_recoverable_streaming_error(error_message) is True


def test_is_recoverable_streaming_error_for_non_recoverable_error() -> None:
    error_message = "ValueError: invalid schema"
    assert _is_recoverable_streaming_error(error_message) is False


def test_should_stop_repeated_stream_tool_call_for_low_value_tool() -> None:
    per_tool_counts = {}

    assert _should_stop_repeated_stream_tool_call(
        function_name="view_tasks",
        per_tool_counts=per_tool_counts,
        max_calls_per_tool=2,
    ) is False
    assert _should_stop_repeated_stream_tool_call(
        function_name="view_tasks",
        per_tool_counts=per_tool_counts,
        max_calls_per_tool=2,
    ) is False
    assert _should_stop_repeated_stream_tool_call(
        function_name="view_tasks",
        per_tool_counts=per_tool_counts,
        max_calls_per_tool=2,
    ) is True


def test_should_not_stop_repeated_stream_tool_call_for_non_guarded_tool() -> None:
    per_tool_counts = {}

    assert _should_stop_repeated_stream_tool_call(
        function_name="browser_navigate_to",
        per_tool_counts=per_tool_counts,
        max_calls_per_tool=1,
    ) is False


def test_should_stop_repeated_web_search_after_default_guard_limit() -> None:
    per_tool_counts = {}

    assert _should_stop_repeated_stream_tool_call(
        function_name="web_search",
        per_tool_counts=per_tool_counts,
        max_calls_per_tool=3,
    ) is False
    assert _should_stop_repeated_stream_tool_call(
        function_name="web_search",
        per_tool_counts=per_tool_counts,
        max_calls_per_tool=3,
    ) is False
    assert _should_stop_repeated_stream_tool_call(
        function_name="web_search",
        per_tool_counts=per_tool_counts,
        max_calls_per_tool=3,
    ) is True


def test_should_stop_repeated_update_tasks_after_default_guard_limit() -> None:
    per_tool_counts = {}

    assert _should_stop_repeated_stream_tool_call(
        function_name="update_tasks",
        per_tool_counts=per_tool_counts,
        max_calls_per_tool=3,
    ) is False
    assert _should_stop_repeated_stream_tool_call(
        function_name="update_tasks",
        per_tool_counts=per_tool_counts,
        max_calls_per_tool=3,
    ) is False
    assert _should_stop_repeated_stream_tool_call(
        function_name="update_tasks",
        per_tool_counts=per_tool_counts,
        max_calls_per_tool=3,
    ) is True


def test_should_stop_repeated_browser_navigate_after_default_guard_limit() -> None:
    per_tool_counts = {}

    assert _should_stop_repeated_stream_tool_call(
        function_name="browser_navigate_to",
        per_tool_counts=per_tool_counts,
        max_calls_per_tool=3,
    ) is False
    assert _should_stop_repeated_stream_tool_call(
        function_name="browser_navigate_to",
        per_tool_counts=per_tool_counts,
        max_calls_per_tool=3,
    ) is False
    assert _should_stop_repeated_stream_tool_call(
        function_name="browser_navigate_to",
        per_tool_counts=per_tool_counts,
        max_calls_per_tool=3,
    ) is True


def test_should_stop_repeated_create_tasks_after_single_call_by_default_limit() -> None:
    per_tool_counts = {}

    assert _should_stop_repeated_stream_tool_call(
        function_name="create_tasks",
        per_tool_counts=per_tool_counts,
        max_calls_per_tool=3,
    ) is False
    assert _should_stop_repeated_stream_tool_call(
        function_name="create_tasks",
        per_tool_counts=per_tool_counts,
        max_calls_per_tool=3,
    ) is True


def test_should_stop_repeated_scrape_webpage_after_single_call_by_default_limit() -> None:
    per_tool_counts = {}

    assert _should_stop_repeated_stream_tool_call(
        function_name="scrape_webpage",
        per_tool_counts=per_tool_counts,
        max_calls_per_tool=3,
    ) is False
    assert _should_stop_repeated_stream_tool_call(
        function_name="scrape_webpage",
        per_tool_counts=per_tool_counts,
        max_calls_per_tool=3,
    ) is True


def test_is_tool_call_allowed_accepts_all_when_no_allowlist() -> None:
    assert _is_tool_call_allowed(
        function_name="create_tasks",
        allowed_function_names=None,
    ) is True


def test_is_tool_call_allowed_requires_membership_when_allowlist_present() -> None:
    allowed = {"view_tasks", "web_search"}
    assert _is_tool_call_allowed(
        function_name="view_tasks",
        allowed_function_names=allowed,
    ) is True
    assert _is_tool_call_allowed(
        function_name="create_tasks",
        allowed_function_names=allowed,
    ) is False
