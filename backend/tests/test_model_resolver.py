from utils.config import config
from utils.model_resolver import apply_model_provider_override, resolve_model_config


def _snapshot_config(keys):
    return {key: getattr(config, key, None) for key in keys}


def _restore_config(snapshot):
    for key, value in snapshot.items():
        setattr(config, key, value)


def test_openai_prefixed_deepseek_uses_qwen_credentials():
    keys = [
        "QWEN_API_KEY",
        "QWEN_API_BASE",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_API_BASE",
        "OPENAI_API_KEY",
    ]
    snapshot = _snapshot_config(keys)
    try:
        config.QWEN_API_KEY = "qwen-test-key"
        config.QWEN_API_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        config.DEEPSEEK_API_KEY = None
        config.DEEPSEEK_API_BASE = None
        config.OPENAI_API_KEY = "openai-test-key"

        resolved = resolve_model_config("openai/deepseek-v3.2")

        assert resolved.model_name == "openai/deepseek-v3.2"
        assert resolved.api_key == "qwen-test-key"
        assert resolved.api_base == "https://dashscope.aliyuncs.com/compatible-mode/v1"
        assert resolved.provider.startswith("Qwen")
    finally:
        _restore_config(snapshot)


def test_bare_deepseek_model_is_normalized_for_litellm():
    keys = [
        "QWEN_API_KEY",
        "QWEN_API_BASE",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_API_BASE",
        "OPENAI_API_KEY",
    ]
    snapshot = _snapshot_config(keys)
    try:
        config.QWEN_API_KEY = "qwen-test-key"
        config.QWEN_API_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        config.DEEPSEEK_API_KEY = None
        config.DEEPSEEK_API_BASE = None
        config.OPENAI_API_KEY = "openai-test-key"

        resolved = resolve_model_config("deepseek-v3.2")

        assert resolved.model_name == "openai/deepseek-v3.2"
        assert resolved.api_key == "qwen-test-key"
        assert resolved.api_base == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    finally:
        _restore_config(snapshot)


def test_gpt_model_still_uses_openai_credentials():
    keys = ["OPENAI_API_KEY", "QWEN_API_KEY", "QWEN_API_BASE"]
    snapshot = _snapshot_config(keys)
    try:
        config.OPENAI_API_KEY = "openai-test-key"
        config.QWEN_API_KEY = "qwen-test-key"
        config.QWEN_API_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"

        resolved = resolve_model_config("gpt-4o-mini")

        assert resolved.provider == "OpenAI"
        assert resolved.api_key == "openai-test-key"
        assert resolved.api_base is None
    finally:
        _restore_config(snapshot)


def test_siliconflow_deepseek_model_prefers_siliconflow_credentials():
    keys = [
        "SILICONFLOW_API_KEY",
        "SILICONFLOW_API_BASE",
        "QWEN_API_KEY",
        "QWEN_API_BASE",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_API_BASE",
        "OPENAI_API_KEY",
    ]
    snapshot = _snapshot_config(keys)
    try:
        config.SILICONFLOW_API_KEY = "siliconflow-test-key"
        config.SILICONFLOW_API_BASE = "https://api.siliconflow.cn/v1"
        config.QWEN_API_KEY = "qwen-test-key"
        config.QWEN_API_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        config.DEEPSEEK_API_KEY = "deepseek-test-key"
        config.DEEPSEEK_API_BASE = "https://api.deepseek.com"
        config.OPENAI_API_KEY = "openai-test-key"

        resolved = resolve_model_config("deepseek-ai/DeepSeek-V3.2")

        assert resolved.model_name == "openai/deepseek-ai/DeepSeek-V3.2"
        assert resolved.api_key == "siliconflow-test-key"
        assert resolved.api_base == "https://api.siliconflow.cn/v1"
        assert resolved.provider == "SiliconFlow"
    finally:
        _restore_config(snapshot)


def test_siliconflow_alias_model_routes_to_siliconflow_credentials():
    keys = [
        "SILICONFLOW_API_KEY",
        "SILICONFLOW_API_BASE",
        "QWEN_API_KEY",
        "QWEN_API_BASE",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_API_BASE",
        "OPENAI_API_KEY",
    ]
    snapshot = _snapshot_config(keys)
    try:
        config.SILICONFLOW_API_KEY = "siliconflow-test-key"
        config.SILICONFLOW_API_BASE = "https://api.siliconflow.cn/v1"
        config.QWEN_API_KEY = "qwen-test-key"
        config.QWEN_API_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        config.DEEPSEEK_API_KEY = "deepseek-test-key"
        config.DEEPSEEK_API_BASE = "https://api.deepseek.com"
        config.OPENAI_API_KEY = "openai-test-key"

        resolved = resolve_model_config("deepseek-siliconflow")

        assert resolved.model_name == "openai/deepseek-ai/DeepSeek-V3.2"
        assert resolved.api_key == "siliconflow-test-key"
        assert resolved.api_base == "https://api.siliconflow.cn/v1"
        assert resolved.provider == "SiliconFlow"
    finally:
        _restore_config(snapshot)


def test_provider_override_switches_deepseek_to_siliconflow_alias():
    overridden = apply_model_provider_override("deepseek-v3.2", "siliconflow")
    assert overridden == "deepseek-siliconflow"


def test_provider_override_switches_siliconflow_alias_back_to_dashscope():
    overridden = apply_model_provider_override("deepseek-siliconflow", "dashscope")
    assert overridden == "deepseek-v3.2"


def test_provider_override_does_not_change_non_deepseek_model():
    overridden = apply_model_provider_override("gpt-4o-mini", "siliconflow")
    assert overridden == "gpt-4o-mini"


def test_provider_override_does_not_change_non_target_deepseek_model():
    overridden = apply_model_provider_override(
        "openrouter/deepseek/deepseek-chat",
        "siliconflow",
    )
    assert overridden == "openrouter/deepseek/deepseek-chat"
