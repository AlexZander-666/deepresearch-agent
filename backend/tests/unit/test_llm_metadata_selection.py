from services.llm import _extract_adk_metadata


def test_extract_adk_metadata_prefers_explicit_session_over_temporary_user_message():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "temporary recovery prompt"},
        {
            "role": "user",
            "content": "real user prompt",
            "app_name": "AlexManus",
            "user_id": "u-123",
            "session_id": "s-123",
            "thread_id": "t-123",
        },
    ]

    metadata = _extract_adk_metadata(messages)
    assert metadata["user_id"] == "u-123"
    assert metadata["session_id"] == "s-123"
    assert metadata["thread_id"] == "t-123"


def test_extract_adk_metadata_uses_latest_when_scores_tie():
    messages = [
        {"role": "user", "content": "first"},
        {"role": "user", "content": "second"},
    ]

    metadata = _extract_adk_metadata(messages)
    assert metadata["session_id"] == "default_session"
    assert metadata["user_id"] == "default_user"


def test_extract_adk_metadata_returns_defaults_without_user_messages():
    messages = [{"role": "system", "content": "sys only"}]

    metadata = _extract_adk_metadata(messages)
    assert metadata == {
        "app_name": "AlexManus",
        "user_id": "default_user",
        "session_id": "default_session",
        "thread_id": None,
    }
