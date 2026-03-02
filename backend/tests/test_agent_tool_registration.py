from agent.run import (
    should_register_default_toolset,
    should_register_simple_test_tool,
)


def test_register_default_toolset_when_agent_config_missing():
    assert should_register_default_toolset(None) is True
    assert should_register_default_toolset({}) is True


def test_register_default_toolset_for_non_default_agent_with_enabled_tools():
    config = {
        "is_AlexManus_default": False,
        "agentpress_tools": {
            "web_search_tool": {"enabled": True},
            "browser_tool": False,
        },
    }

    assert should_register_default_toolset(config) is True


def test_skip_default_toolset_when_agent_explicitly_disables_all_tools():
    config = {
        "is_AlexManus_default": False,
        "agentpress_tools": {
            "web_search_tool": {"enabled": False},
            "browser_tool": False,
            "computer_use_tool": {"enabled": False},
        },
    }

    assert should_register_default_toolset(config) is False


def test_skip_default_toolset_when_disable_flags_are_string_booleans():
    config = {
        "is_AlexManus_default": False,
        "agentpress_tools": {
            "web_search_tool": {"enabled": "false"},
            "browser_tool": "false",
            "computer_use_tool": {"enabled": "0"},
        },
    }

    assert should_register_default_toolset(config) is False


def test_register_default_toolset_when_json_string_config_has_enabled_tool():
    config = {
        "is_AlexManus_default": False,
        "agentpress_tools": (
            '{"web_search_tool":{"enabled":"false"},'
            '"browser_tool":{"enabled":"true"}}'
        ),
    }

    assert should_register_default_toolset(config) is True


def test_skip_default_toolset_when_json_string_config_disables_all_tools():
    config = {
        "is_AlexManus_default": False,
        "agentpress_tools": (
            '{"web_search_tool":{"enabled":"false"},'
            '"browser_tool":{"enabled":"0"}}'
        ),
    }

    assert should_register_default_toolset(config) is False


def test_simple_test_tool_registration_requires_explicit_enable_flag():
    assert should_register_simple_test_tool(env_value=None) is False
    assert should_register_simple_test_tool(env_value="") is False
    assert should_register_simple_test_tool(env_value="false") is False
    assert should_register_simple_test_tool(env_value="0") is False
    assert should_register_simple_test_tool(env_value="true") is True
