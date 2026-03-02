import os
import json
import asyncio
import datetime
import uuid
from typing import Optional, Dict, List, Any, AsyncGenerator
from dataclasses import dataclass
import traceback

from dotenv import load_dotenv # type: ignore
from utils.config import config
from agentpress.thread_manager import ThreadManager
from agentpress.response_processor import ProcessorConfig
from agent.prompt import get_system_prompt
from agent.gemini_prompt import get_gemini_system_prompt
from utils.logger import logger
from services.langfuse import langfuse
try:
    from langfuse.client import StatefulTraceClient # type: ignore
except ImportError:
    # 对于 langfuse 3.x 版本，尝试不同的导入路径
    try:
        from langfuse import StatefulTraceClient # type: ignore
    except ImportError:
        # 如果都失败，使用 Any 类型
        from typing import Any
        StatefulTraceClient = Any


load_dotenv(override=True)

DEEPSEEK_DASHSCOPE_MODEL = "deepseek-v3.2"
DEEPSEEK_SILICONFLOW_MODEL_ALIAS = "deepseek-siliconflow"
REQUIRED_RESEARCH_CHAIN_STAGES: List[tuple[str, tuple[str, ...]]] = [
    ("has_created_tasks", ("create_tasks",)),
    ("has_viewed_tasks", ("view_tasks",)),
    ("has_web_search", ("web_search",)),
    ("has_scrape_webpage", ("scrape_webpage",)),
    ("has_screenshot", ("screenshot",)),
    ("has_updated_tasks", ("update_tasks",)),
]
REQUIRED_RESEARCH_CHAIN_TOOL_TO_STAGE_KEY = {
    tool_name: stage_key
    for stage_key, stage_tools in REQUIRED_RESEARCH_CHAIN_STAGES
    for tool_name in stage_tools
}
NON_SKIPPABLE_REQUIRED_STAGE_KEYS: set[str] = {
    "has_created_tasks",
    "has_viewed_tasks",
    "has_web_search",
    "has_updated_tasks",
}
RECOVERABLE_NON_TERMINATING_TOOL_FAILURES: set[str] = {
    # task-list / research tools
    "create_tasks",
    "view_tasks",
    "update_tasks",
    "web_search",
    "scrape_webpage",
    # computer-use tools
    "move_to",
    "click",
    "scroll",
    "typing",
    "press",
    "wait",
    "mouse_down",
    "mouse_up",
    "drag_to",
    "screenshot",
    # browser tools
    "browser_navigate_to",
    "browser_input_text",
    "browser_click_element",
    "browser_send_keys",
    "browser_scroll_down",
    "browser_scroll_up",
    "browser_go_back",
    "browser_wait",
    # file-style tools (when custom toolchains leak into deep-research runs)
    "edit_file",
    "read_file",
    "write_file",
    "list_files",
    "search_files",
    "create_file",
}
DEEP_RESEARCH_ALLOWED_TOOL_NAMES: set[str] = {
    # task-list / research chain
    "create_tasks",
    "view_tasks",
    "update_tasks",
    "delete_tasks",
    "clean_path",
    "web_search",
    "scrape_webpage",
    "screenshot",
    # desktop computer-use
    "move_to",
    "click",
    "scroll",
    "typing",
    "press",
    "wait",
    "mouse_down",
    "mouse_up",
    "drag_to",
    # browser-use
    "browser_navigate_to",
    "browser_input_text",
    "browser_click_element",
    "browser_send_keys",
    "browser_scroll_down",
    "browser_scroll_up",
    "browser_go_back",
    "browser_wait",
}


@dataclass
class AgentConfig:
    thread_id: str
    project_id: str
    stream: bool
    native_max_auto_continues: int = 0
    max_iterations: int = 100
    model_name: str = "deepseek-v3.2"
    enable_thinking: Optional[bool] = False
    reasoning_effort: Optional[str] = 'low'
    enable_context_manager: bool = True
    agent_config: Optional[dict] = None
    trace: Optional[StatefulTraceClient] = None # type: ignore
    is_agent_builder: Optional[bool] = False
    target_agent_id: Optional[str] = None


def decide_agent_iteration_continuation(
    *,
    agent_should_terminate: bool,
    last_tool_call: Optional[str],
    terminating_tool_names: set[str],
    completed_non_terminating_tools: set[str],
    failed_non_terminating_tools: set[str],
    previous_completed_signature: Optional[tuple[str, ...]],
    repeated_signature_streak: int,
    max_repeated_tool_rounds: int = 5,
    recoverable_non_terminating_tools: Optional[set[str]] = None,
) -> tuple[bool, Optional[tuple[str, ...]], int, Optional[str]]:
    """
    Decide whether the outer agent loop should continue.

    Returns:
        (should_continue, updated_signature, updated_streak, stop_reason)
    """
    if agent_should_terminate or last_tool_call in terminating_tool_names:
        return False, previous_completed_signature, repeated_signature_streak, "terminated"

    if failed_non_terminating_tools:
        recoverable_tools = recoverable_non_terminating_tools or set()
        recoverable_failed_tools = failed_non_terminating_tools.intersection(recoverable_tools)
        unrecoverable_failed_tools = failed_non_terminating_tools.difference(recoverable_tools)

        if unrecoverable_failed_tools:
            return False, previous_completed_signature, repeated_signature_streak, "tool_failed"

        if recoverable_failed_tools and not completed_non_terminating_tools:
            failure_signature = tuple(
                sorted(f"failed:{tool_name}" for tool_name in recoverable_failed_tools)
            )
            if failure_signature == previous_completed_signature:
                repeated_signature_streak += 1
            else:
                repeated_signature_streak = 1

            effective_max_repeated_rounds = min(max_repeated_tool_rounds, 3)
            if repeated_signature_streak >= effective_max_repeated_rounds:
                return (
                    False,
                    failure_signature,
                    repeated_signature_streak,
                    "repeated_tool_rounds",
                )

            return True, failure_signature, repeated_signature_streak, "recoverable_tool_failed"

    if completed_non_terminating_tools:
        current_signature = tuple(sorted(completed_non_terminating_tools))
        planning_signatures = {
            ("create_tasks",),
            ("view_tasks",),
            ("create_tasks", "view_tasks"),
        }
        is_planning_signature = current_signature in planning_signatures
        was_planning_signature = previous_completed_signature in planning_signatures

        if current_signature == previous_completed_signature:
            repeated_signature_streak += 1
        elif is_planning_signature and was_planning_signature:
            # Treat alternating create/view rounds as one planning-only streak.
            repeated_signature_streak += 1
        else:
            repeated_signature_streak = 1

        # Task-planning loops are low-value if they keep repeating without execution.
        effective_max_repeated_rounds = max_repeated_tool_rounds
        if is_planning_signature:
            effective_max_repeated_rounds = min(max_repeated_tool_rounds, 3)
            if (
                current_signature == ("create_tasks",)
                and previous_completed_signature == ("create_tasks",)
            ):
                # Allow a few more retries for create_tasks-only rounds, because
                # create_tasks may be reused as a guardrail/hint tool when a task list
                # already exists.
                effective_max_repeated_rounds = min(max_repeated_tool_rounds, 3)
        elif current_signature == ("screenshot",):
            # Computer-use flows can require several screenshot refresh rounds before
            # the model switches to action tools.
            effective_max_repeated_rounds = max(max_repeated_tool_rounds, 6)

        if repeated_signature_streak >= effective_max_repeated_rounds:
            return False, current_signature, repeated_signature_streak, "repeated_tool_rounds"

        return True, current_signature, repeated_signature_streak, None

    return False, None, 0, "no_tools_completed"


def build_web_search_fallback_text(
    results: list[dict],
    max_items: int = 5,
    screenshot_summary: Optional[Dict[str, Any]] = None,
    include_fallback_notice: bool = True,
    include_screenshot_observation: bool = False,
) -> str:
    """Build a deterministic structured report when the model fails to close properly."""
    if not results and not screenshot_summary:
        return ""

    intro_line = (
        "已触发自动兜底收敛流程。以下是基于当前可用证据生成的结构化报告："
        if include_fallback_notice
        else "基于当前已收集证据的结构化总结如下："
    )
    lines = [intro_line, "", "一、结论"]
    if include_fallback_notice:
        lines.extend(
            [
                "- 当前回合已完成自动化证据收集，并输出可复核的来源列表。",
                "- 若工具链在中途循环中断，本报告属于快速收敛版本，建议在下一轮补充更细分数据。",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "- 当前回合已完成自动化证据收集，并输出可复核的来源列表。",
                "- 以下内容优先基于已执行工具返回的事实证据进行整理。",
                "",
            ]
        )

    key_titles: List[str] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if title:
            key_titles.append(title)
        if len(key_titles) >= 3:
            break

    lines.append("二、关键证据（基于检索标题）")
    if key_titles:
        for title in key_titles:
            lines.append(f"- {title}")
    else:
        lines.append("- 未提取到可用的检索标题证据。")
    lines.append("")

    lines.append("三、工具执行记录")
    lines.append(f"- web_search：提取到 {len(results)} 条候选来源。")
    if include_screenshot_observation and screenshot_summary and isinstance(screenshot_summary, dict):
        screenshot_url = str(screenshot_summary.get("url") or "").strip()
        width = screenshot_summary.get("width")
        height = screenshot_summary.get("height")
        timestamp = str(screenshot_summary.get("timestamp") or "").strip()
        size_text = (
            f"{width}x{height}"
            if isinstance(width, int) and isinstance(height, int)
            else "unknown-size"
        )
        if screenshot_url:
            lines.append(
                f"- computer-use/sandbox screenshot：{screenshot_url} ({size_text})"
                + (f", captured_at={timestamp}" if timestamp else "")
            )
    lines.append("")

    lines.append("四、参考来源")
    count = 0
    for item in results:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        if not title or not url:
            continue
        count += 1
        lines.append(f"{count}. {title} - {url}")
        if count >= max_items:
            break
    if count == 0:
        lines.append("1. 暂无可用来源链接")
    lines.append("")

    lines.extend(
        [
            "五、风险与不确定性",
            "- 不同来源发布时间、统计口径、样本范围可能不一致。",
            "- 当前结果主要依赖公开网页检索，可能缺少付费数据库与一手调研补充。",
            "",
            "六、下一步建议",
            "1. 对关键指标（市场规模、增速、投融资）做统一口径表格化复核。",
            "2. 对结论影响最大的来源进行二次交叉验证并记录时间戳。",
            "3. 如需高置信度版本，继续执行分主题深挖并补充官方报告数据。",
        ]
    )

    return "\n".join(lines)


_RECOVERABLE_STREAM_ERROR_MARKERS = (
    "apiconnectionerror",
    "server disconnected",
    "connection reset",
    "connection aborted",
    "remote end closed connection",
    "temporarily unavailable",
    "connection timed out",
    "timeout reading from redis",
)

_PROVIDER_ACCOUNT_STREAM_ERROR_MARKERS = (
    "overdue-payment",
    "account is in good standing",
    "model-studio/error-code",
    "openaiexception - access denied",
    "insufficient balance",
    "quota exceeded",
    "balance_not_enough",
)

_BALANCE_NOT_ENOUGH_ERROR_MARKERS = (
    "balance_not_enough",
    "insufficient balance",
    "余额不足",
    "余额不够",
)

_LOW_VALUE_NO_TOOL_RESPONSE_MARKERS = (
    "hello! i'm alexmanus",
    "i'm alexmanus",
    "i'm here to help you",
    "i have access to comprehensive tools",
    "how can i assist",
    "what would you like me to",
    "我是alexmanus",
    "我可以帮助你",
    "i understand you want me to continue processing",
    "continue processing the previous request",
    "based on our conversation history",
    "i haven't created a task list yet",
    "i understand you want me to",
    "i don't have the `browser_navigate_to` tool",
    "i don't have the browser_navigate_to tool",
    "however, looking at the tools available",
    "i only have access to",
    "let me create a structured approach",
    "plan execution",
    "我目前只能使用",
    "我来继续处理之前的请求",
    "我将继续处理之前的请求",
    "我理解您的意思。您是指让我继续处理之前的请求",
    "基于我们的对话历史",
    "还没有创建任务列表",
    "让我重新开始整个流程",
    "当前的工具集中没有",
    "没有\"screenshot\"工具",
    "并没有\"screenshot\"这个工具",
    "没有独立的`screenshot`工具",
    "无法完成这个具体请求",
    "i cannot execute",
    "current toolset has no",
)


def is_recoverable_stream_error_message(error_message: Optional[str]) -> bool:
    """Classify transient stream failures that are worth retrying/falling back for."""
    if not isinstance(error_message, str):
        return False
    normalized = error_message.lower()
    return any(marker in normalized for marker in _RECOVERABLE_STREAM_ERROR_MARKERS)


def is_provider_account_stream_error_message(error_message: Optional[str]) -> bool:
    """Detect provider-side account/billing rejections that may require model/provider switch."""
    if not isinstance(error_message, str):
        return False
    normalized = error_message.lower()
    return any(
        marker in normalized for marker in _PROVIDER_ACCOUNT_STREAM_ERROR_MARKERS
    )


def is_balance_not_enough_error_message(error_message: Optional[str]) -> bool:
    """Detect explicit balance-not-enough account blocking markers."""
    if error_message is None:
        return False
    try:
        normalized = str(error_message).strip().lower()
    except Exception:
        return False
    if not normalized:
        return False
    return any(marker in normalized for marker in _BALANCE_NOT_ENOUGH_ERROR_MARKERS)


def is_tool_blocked_by_current_run(tool_result_output: Any) -> bool:
    """Detect allowlist-gating failures returned by the runtime execution layer."""
    if tool_result_output is None:
        return False

    try:
        normalized = str(tool_result_output).strip().lower()
    except Exception:
        return False

    if not normalized:
        return False

    return "is not available in current run" in normalized


def choose_recoverable_stream_fallback_model(
    *,
    current_model_name: str,
    configured_fallback_model: Optional[str],
    error_message: Optional[str] = None,
    siliconflow_available: Optional[bool] = None,
    dashscope_available: Optional[bool] = None,
) -> Optional[str]:
    """Select a fallback model when recoverable stream errors happen on unstable providers."""
    if not isinstance(current_model_name, str) or not current_model_name.strip():
        return None

    normalized_current = current_model_name.strip().lower()
    if normalized_current.startswith("openai/"):
        normalized_current = normalized_current[len("openai/"):]

    if is_provider_account_stream_error_message(error_message):
        if siliconflow_available is None:
            siliconflow_key = getattr(config, "SILICONFLOW_API_KEY", None)
            siliconflow_available = (
                isinstance(siliconflow_key, str) and bool(siliconflow_key.strip())
            )

        if dashscope_available is None:
            qwen_key = getattr(config, "QWEN_API_KEY", None)
            deepseek_key = getattr(config, "DEEPSEEK_API_KEY", None)
            dashscope_available = (
                (isinstance(qwen_key, str) and bool(qwen_key.strip()))
                or (isinstance(deepseek_key, str) and bool(deepseek_key.strip()))
            )

        is_siliconflow_deepseek_model = (
            normalized_current.startswith("deepseek-ai/")
            or "deepseek-siliconflow" in normalized_current
        )
        is_deepseek_family_model = "deepseek" in normalized_current
        is_dashscope_deepseek_model = (
            is_deepseek_family_model and not is_siliconflow_deepseek_model
        )

        if is_dashscope_deepseek_model and siliconflow_available:
            return DEEPSEEK_SILICONFLOW_MODEL_ALIAS

        if is_siliconflow_deepseek_model and dashscope_available:
            return DEEPSEEK_DASHSCOPE_MODEL

    fallback_model = (configured_fallback_model or "").strip()
    if not fallback_model:
        return None
    if fallback_model == current_model_name:
        return None

    # Keep model switching conservative for transient connection errors:
    # only auto-switch away from ollama stacks.
    if "ollama" in normalized_current:
        return fallback_model
    return None


def is_low_value_no_tool_response(response_text: Optional[str]) -> bool:
    """Detect generic assistant chatter that should not be treated as a completed deep-research answer."""
    if not isinstance(response_text, str):
        return True

    normalized = response_text.strip().lower()
    if not normalized:
        return True

    # Structured summaries are considered substantive even if they include a
    # transitional sentence that matches low-value markers.
    if is_structured_research_summary_text(response_text):
        return False

    if any(marker in normalized for marker in _LOW_VALUE_NO_TOOL_RESPONSE_MARKERS):
        # Non-deep flows may return short concrete deliverables (e.g., screenshot URL).
        # Avoid misclassifying those as low-value.
        if "http://" in normalized or "https://" in normalized:
            return False
        return True

    return False


def is_structured_research_summary_text(response_text: Optional[str]) -> bool:
    """
    Detect whether final assistant text looks like a deliverable structured summary.
    """
    if not isinstance(response_text, str):
        return False

    normalized = response_text.strip().lower()
    if len(normalized) < 40:
        return False

    section_markers = (
        "一、结论",
        "二、关键证据",
        "四、参考来源",
        "五、风险",
        "六、下一步建议",
        "conclusion",
        "key evidence",
        "sources",
        "risks",
        "next steps",
    )
    hit_count = 0
    for marker in section_markers:
        if marker in normalized:
            hit_count += 1
            if hit_count >= 2:
                return True

    return False


def build_stream_error_fallback_text(
    *,
    error_message: str,
    current_model_name: str,
    retry_count: int,
    max_retries: int,
) -> str:
    """Build a deterministic user-facing summary when stream retries are exhausted."""
    safe_error_message = str(error_message or "unknown stream error").strip()
    safe_model_name = str(current_model_name or "unknown-model").strip()
    safe_retry_count = max(0, int(retry_count))
    safe_max_retries = max(1, int(max_retries))

    if is_provider_account_stream_error_message(safe_error_message):
        return "\n".join(
            [
                "本轮深度搜索在模型供应商账户状态校验阶段被拒绝，已触发自动恢复与收敛流程。",
                "",
                "一、异常概览",
                f"- 当前模型：{safe_model_name}",
                f"- 自动恢复尝试：{safe_retry_count}/{safe_max_retries}",
                f"- 错误信息：{safe_error_message}",
                "",
                "二、当前状态",
                "- 当前回合未完成完整 tool use 链路，因此不输出伪造研究结论。",
                "- 系统已保留上下文，可在切换可用 provider 后继续任务清单与检索流程。",
                "",
                "三、建议下一步",
                "1. 切换到可用 provider（如 SiliconFlow）后重试同一请求。",
                "2. 若仍失败，检查对应 provider 的账户状态、余额和 API Key 配置。",
            ]
        )

    return "\n".join(
        [
            "本轮深度搜索在模型流式阶段发生连接中断，已触发自动恢复与收敛流程。",
            "",
            "一、异常概览",
            f"- 当前模型：{safe_model_name}",
            f"- 自动恢复尝试：{safe_retry_count}/{safe_max_retries}",
            f"- 错误信息：{safe_error_message}",
            "",
            "二、当前状态",
            "- 本轮尚未获取到足够工具结果用于完整研究结论。",
            "- 系统已保留上下文，下一轮可继续执行任务清单与检索流程。",
            "",
            "三、建议下一步",
            "1. 继续执行同一请求，让系统使用已切换模型完成剩余 tool use / web-search / sandbox 流程。",
            "2. 若仍中断，优先检查 Ollama 服务健康状态与模型负载，再重试。",
        ]
    )


def build_environment_blocked_report_text(
    *,
    error_message: str,
    current_model_name: str,
) -> str:
    """Build an explicit environment-blocked report for account balance errors."""
    safe_error_message = str(error_message or "BALANCE_NOT_ENOUGH").strip()
    safe_model_name = str(current_model_name or "unknown-model").strip()
    return "\n".join(
        [
            "环境阻塞报告（BALANCE_NOT_ENOUGH）",
            "",
            "一、阻塞原因",
            f"- 当前模型：{safe_model_name}",
            f"- 错误信息：{safe_error_message}",
            "- 上游模型供应商返回余额不足，当前环境无法继续执行深度研究工具链。",
            "",
            "二、当前处理策略",
            "- 已停止触发 web-search synthetic 总结。",
            "- 当前回合不输出伪造研究结论，避免误导性结果。",
            "",
            "三、建议下一步",
            "1. 充值或切换到余额充足的 provider/model 后重试同一请求。",
            "2. 重试时可沿用当前线程上下文，继续 create/view/search/update 链路。",
        ]
    )


def normalize_web_search_results(raw_results: Any, max_items: int = 10) -> List[Dict[str, str]]:
    """Normalize raw web search payload into deterministic title/url pairs."""
    normalized: List[Dict[str, str]] = []
    if not isinstance(raw_results, list):
        return normalized

    for item in raw_results:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        if not title or not url:
            continue
        normalized.append({"title": title, "url": url})
        if len(normalized) >= max_items:
            break
    return normalized


def should_allow_task_replan(user_request: Optional[str]) -> bool:
    """Allow task re-planning only when the user explicitly asks for it."""
    if not user_request or not isinstance(user_request, str):
        return False

    normalized = user_request.strip().lower()
    english_markers = (
        "replan",
        "re-plan",
        "recreate task",
        "reset task",
        "new task list",
    )
    chinese_markers = (
        "重新规划",
        "重规划",
        "重新计划",
        "重建任务",
        "重置任务",
        "新建任务清单",
    )

    return any(marker in normalized for marker in english_markers) or any(
        marker in user_request for marker in chinese_markers
    )


def should_require_task_list_bootstrap(user_request: Optional[str]) -> bool:
    """
    Decide whether the run should enforce create_tasks before view_tasks when no task list exists.
    """
    if not isinstance(user_request, str):
        return False

    normalized = user_request.strip().lower()
    if not normalized:
        return False

    english_markers = (
        "deep research",
        "research workflow",
        "structured report",
        "with citations",
        "task list",
        "create_tasks",
        "web_search",
    )
    chinese_markers = (
        "深度搜索",
        "深度研究",
        "调研",
        "任务清单",
        "create_tasks",
        "web_search",
    )
    return any(marker in normalized for marker in english_markers) or any(
        marker in user_request for marker in chinese_markers
    )


def should_require_scrape_stage(user_request: Optional[str]) -> bool:
    """
    Enforce scrape_webpage stage only when the user explicitly asks for page-level extraction.
    """
    if not isinstance(user_request, str):
        return False

    normalized = user_request.strip().lower()
    if not normalized:
        return False

    english_markers = (
        "scrape",
        "crawl",
        "extract webpage",
        "full page content",
    )
    chinese_markers = (
        "抓取",
        "爬取",
        "网页内容提取",
        "整页内容",
    )
    return any(marker in normalized for marker in english_markers) or any(
        marker in user_request for marker in chinese_markers
    )


def should_require_screenshot_stage(user_request: Optional[str]) -> bool:
    """
    Enforce screenshot stage only when the user explicitly requests visual capture.
    """
    if not isinstance(user_request, str):
        return False

    normalized = user_request.strip().lower()
    if not normalized:
        return False

    english_markers = (
        "screenshot",
        "screen capture",
        "visual proof",
    )
    chinese_markers = (
        "截图",
        "屏幕截图",
        "视觉证据",
    )
    return any(marker in normalized for marker in english_markers) or any(
        marker in user_request for marker in chinese_markers
    )


def should_allow_task_deletion_tools(user_request: Optional[str]) -> bool:
    """Allow destructive task-list tools only when explicitly requested."""
    if not isinstance(user_request, str):
        return False

    normalized = user_request.strip().lower()
    if not normalized:
        return False

    english_markers = (
        "delete task",
        "remove task",
        "clear task",
        "reset task list",
    )
    chinese_markers = (
        "删除任务",
        "清空任务",
        "移除任务",
        "重置任务清单",
    )
    return any(marker in normalized for marker in english_markers) or any(
        marker in user_request for marker in chinese_markers
    )


def should_allow_path_cleanup_tools(user_request: Optional[str]) -> bool:
    """Allow clean_path only when user explicitly asks path cleanup."""
    if not isinstance(user_request, str):
        return False

    normalized = user_request.strip().lower()
    if not normalized:
        return False

    english_markers = (
        "clean path",
        "normalize path",
        "fix file path",
    )
    chinese_markers = (
        "清理路径",
        "规范路径",
        "修复路径",
    )
    return any(marker in normalized for marker in english_markers) or any(
        marker in user_request for marker in chinese_markers
    )


def advance_required_research_chain_state(
    *,
    chain_progress: Dict[str, bool],
    current_stage_index: int,
    task_list_state: Optional[Dict[str, Any]],
    available_functions: Dict[str, Any],
    scrape_stage_failed: bool = False,
) -> int:
    """Move required chain stage forward only; never regress completed stages."""
    stage_index = max(0, current_stage_index)
    max_stage_index = len(REQUIRED_RESEARCH_CHAIN_STAGES)

    total_tasks = 0
    if isinstance(task_list_state, dict):
        maybe_total_tasks = task_list_state.get("total_tasks", 0)
        if isinstance(maybe_total_tasks, int):
            total_tasks = maybe_total_tasks
    if total_tasks > 0:
        chain_progress["has_created_tasks"] = True

    while (
        stage_index < max_stage_index
        and chain_progress.get(REQUIRED_RESEARCH_CHAIN_STAGES[stage_index][0], False)
    ):
        stage_index += 1

    scrape_stage_index = 3
    if (
        stage_index <= scrape_stage_index
        and chain_progress.get("has_web_search", False)
        and not chain_progress.get("has_scrape_webpage", False)
    ):
        scrape_tool_available = "scrape_webpage" in available_functions
        if scrape_stage_failed or not scrape_tool_available:
            chain_progress["has_scrape_webpage"] = True
            stage_index = max(stage_index, scrape_stage_index + 1)
            logger.info(
                "Advancing required deep-research chain past scrape_webpage stage due to %s.",
                "tool_failure" if scrape_stage_failed else "tool_unavailable",
            )

    while (
        stage_index < max_stage_index
        and chain_progress.get(REQUIRED_RESEARCH_CHAIN_STAGES[stage_index][0], False)
    ):
        stage_index += 1

    return min(stage_index, max_stage_index)


def mark_required_research_chain_progress(
    chain_progress: Dict[str, bool],
    function_name: str,
) -> Optional[str]:
    """Mark required chain stage as completed for the given tool name."""
    stage_key = REQUIRED_RESEARCH_CHAIN_TOOL_TO_STAGE_KEY.get(function_name)
    if not stage_key:
        return None
    chain_progress[stage_key] = True
    return stage_key


def apply_task_list_tool_gating(
    *,
    available_functions: Dict[str, Any],
    task_list_state: Dict[str, Any],
    allow_task_replan: bool,
    previous_completed_signature: Optional[tuple[str, ...]],
    repeated_signature_streak: int,
    prefer_task_bootstrap_when_missing: bool = False,
    bootstrap_completed: bool = False,
    require_view_tasks_refresh_before_execution: bool = False,
) -> Dict[str, Any]:
    """
    Apply task-list-aware tool gating to prevent low-value planning loops.
    """
    gated_functions = dict(available_functions)
    task_list_tools = {"create_tasks", "view_tasks", "update_tasks"}
    total_tasks = task_list_state.get("total_tasks", 0)
    has_tasks = isinstance(total_tasks, int) and total_tasks > 0
    task_list_missing_or_empty = (not task_list_state.get("exists")) or (not has_tasks)

    if (
        prefer_task_bootstrap_when_missing
        and task_list_missing_or_empty
        and not bootstrap_completed
        and "create_tasks" in gated_functions
    ):
        gated_functions = {"create_tasks": gated_functions["create_tasks"]}
        logger.info(
            "Task list bootstrap required and no task list exists yet; exposing only create_tasks until bootstrap succeeds."
        )
        return gated_functions

    if (
        require_view_tasks_refresh_before_execution
        and task_list_state.get("exists")
        and task_list_state.get("pending_tasks", 0) > 0
        and "view_tasks" in gated_functions
    ):
        gated_functions = {"view_tasks": gated_functions["view_tasks"]}
        logger.info(
            "Execution-stage guard enabled; forcing view_tasks to refresh next pending task before execution tools."
        )
        return gated_functions

    if (
        task_list_state.get("exists")
        and not allow_task_replan
        and bootstrap_completed
        and "create_tasks" in gated_functions
    ):
        gated_functions.pop("create_tasks", None)
        logger.info(
            "Task-list bootstrap already completed; disabled create_tasks to avoid redundant replanning."
        )

    if (
        task_list_state.get("exists")
        and task_list_state.get("pending_tasks", 0) > 0
        and not allow_task_replan
        and "create_tasks" in gated_functions
    ):
        gated_functions.pop("create_tasks", None)
        logger.info(
            "Task list already exists with pending tasks (total_tasks=%s, completed_tasks=%s, pending_tasks=%s); "
            "temporarily disabled create_tasks to force execution flow via view_tasks/update_tasks.",
            task_list_state.get("total_tasks", 0),
            task_list_state.get("completed_tasks", 0),
            task_list_state.get("pending_tasks", 0),
        )

    if (
        task_list_state.get("exists")
        and task_list_state.get("pending_tasks", 0) > 0
        and not allow_task_replan
        and not bootstrap_completed
        and previous_completed_signature == ("create_tasks",)
        and "view_tasks" in gated_functions
    ):
        gated_functions = {"view_tasks": gated_functions["view_tasks"]}
        logger.info(
            "create_tasks completed in previous round; forcing view_tasks before execution tools."
        )
        return gated_functions

    if (
        task_list_state.get("exists")
        and task_list_state.get("pending_tasks", 0) > 0
        and "update_tasks" in gated_functions
    ):
        previous_signature_set = set(previous_completed_signature or ())
        if not previous_signature_set or previous_signature_set.issubset(task_list_tools):
            gated_functions.pop("update_tasks", None)
            logger.info(
                "Temporarily disabled update_tasks until at least one execution tool runs after planning."
            )

    if (
        task_list_state.get("exists")
        and task_list_state.get("pending_tasks", 0) > 0
        and previous_completed_signature == ("view_tasks",)
        and repeated_signature_streak >= 2
        and "view_tasks" in gated_functions
    ):
        gated_functions.pop("view_tasks", None)
        logger.info(
            "Temporarily disabled view_tasks after repeated view-only rounds; "
            "next pending task hint='%s'",
            task_list_state.get("next_pending_task_content", ""),
        )

    if (
        task_list_state.get("exists")
        and task_list_state.get("pending_tasks", 0) > 0
        and previous_completed_signature == ("update_tasks",)
        and repeated_signature_streak >= 1
        and "update_tasks" in gated_functions
    ):
        gated_functions.pop("update_tasks", None)
        logger.info(
            "Temporarily disabled update_tasks after repeated update-only rounds; "
            "forcing execution tools before next progress update. next pending task hint='%s'",
            task_list_state.get("next_pending_task_content", ""),
        )

    return gated_functions


def apply_deep_research_focus_gating(
    *,
    available_functions: Dict[str, Any],
    user_request: Optional[str],
    allow_task_replan: bool,
) -> Dict[str, Any]:
    """
    Trim low-value tools for deep-research flows to reduce tool-selection drift.
    """
    if not should_require_task_list_bootstrap(user_request):
        gated_functions = dict(available_functions)
        request_text = user_request if isinstance(user_request, str) else ""
        normalized_request = request_text.strip().lower()
        sandbox_or_browser_markers = (
            "sandbox",
            "browser",
            "screenshot",
            "desktop",
            "click",
            "navigate",
            "电脑",
            "桌面",
            "截图",
            "浏览器",
            "点击",
            "输入",
        )
        if any(marker in normalized_request for marker in sandbox_or_browser_markers) or any(
            marker in request_text for marker in ("电脑", "桌面", "截图", "浏览器", "点击", "输入")
        ):
            for task_tool in ("create_tasks", "view_tasks", "update_tasks", "delete_tasks", "clean_path"):
                gated_functions.pop(task_tool, None)
        return gated_functions

    gated_functions = {
        tool_name: tool_impl
        for tool_name, tool_impl in available_functions.items()
        if tool_name in DEEP_RESEARCH_ALLOWED_TOOL_NAMES
    }
    if not gated_functions:
        logger.warning(
            "Deep-research allowlist gating produced an empty toolset; falling back to original available functions."
        )
        gated_functions = dict(available_functions)

    for noisy_tool in ("test_calculator", "test_echo", "clear_all"):
        gated_functions.pop(noisy_tool, None)

    if not allow_task_replan and not should_allow_task_deletion_tools(user_request):
        gated_functions.pop("delete_tasks", None)

    if not should_allow_path_cleanup_tools(user_request):
        gated_functions.pop("clean_path", None)

    return gated_functions


def apply_high_frequency_tool_gating(
    *,
    available_functions: Dict[str, Any],
    previous_completed_signature: Optional[tuple[str, ...]],
    repeated_signature_streak: int,
    task_list_state: Optional[Dict[str, Any]] = None,
    web_search_streak_threshold: int = 2,
    screenshot_streak_threshold: int = 4,
) -> Dict[str, Any]:
    """
    Proactively disable high-frequency repeated execution tools before loop hard-stop.

    This is a main-path tool switch guard, not a fallback. It nudges the model to
    synthesize existing evidence or switch to different action tools.
    """
    gated_functions = dict(available_functions)
    effective_web_search_streak_threshold = web_search_streak_threshold
    if isinstance(task_list_state, dict):
        pending_tasks = task_list_state.get("pending_tasks", 0)
        has_pending_tasks = isinstance(pending_tasks, int) and pending_tasks > 0
        if has_pending_tasks and "update_tasks" in gated_functions:
            effective_web_search_streak_threshold = min(
                web_search_streak_threshold,
                2,
            )

    if (
        previous_completed_signature == ("web_search",)
        and repeated_signature_streak >= effective_web_search_streak_threshold
        and "web_search" in gated_functions
    ):
        gated_functions.pop("web_search", None)
        logger.info(
            "Temporarily disabled web_search after repeated search-only rounds "
            "(streak=%s, threshold=%s).",
            repeated_signature_streak,
            effective_web_search_streak_threshold,
        )

    if (
        previous_completed_signature == ("screenshot",)
        and repeated_signature_streak >= screenshot_streak_threshold
        and "screenshot" in gated_functions
    ):
        gated_functions.pop("screenshot", None)
        logger.info(
            "Temporarily disabled screenshot after repeated screenshot-only rounds "
            "(streak=%s, threshold=%s).",
            repeated_signature_streak,
            screenshot_streak_threshold,
        )

    return gated_functions


def apply_cumulative_tool_budget_gating(
    *,
    available_functions: Dict[str, Any],
    cumulative_completed_tool_counts: Dict[str, int],
    allow_task_replan: bool,
) -> Dict[str, Any]:
    """
    Gate tools based on cumulative completion counts across the whole run.
    """
    gated_functions = dict(available_functions)

    def completed_count(tool_name: str) -> int:
        raw = cumulative_completed_tool_counts.get(tool_name, 0)
        return raw if isinstance(raw, int) and raw > 0 else 0

    if (
        not allow_task_replan
        and completed_count("create_tasks") >= 1
        and "create_tasks" in gated_functions
    ):
        gated_functions.pop("create_tasks", None)
        logger.info(
            "Cumulative budget gating disabled create_tasks (completed=%s).",
            completed_count("create_tasks"),
        )

    if completed_count("web_search") >= 3 and "web_search" in gated_functions:
        gated_functions.pop("web_search", None)
        logger.info(
            "Cumulative budget gating disabled web_search (completed=%s, budget=3).",
            completed_count("web_search"),
        )

    if completed_count("view_tasks") >= 3 and "view_tasks" in gated_functions:
        gated_functions.pop("view_tasks", None)
        logger.info(
            "Cumulative budget gating disabled view_tasks (completed=%s, budget=3).",
            completed_count("view_tasks"),
        )

    if completed_count("update_tasks") >= 3 and "update_tasks" in gated_functions:
        gated_functions.pop("update_tasks", None)
        logger.info(
            "Cumulative budget gating disabled update_tasks (completed=%s, budget=3).",
            completed_count("update_tasks"),
        )

    if completed_count("screenshot") >= 3 and "screenshot" in gated_functions:
        gated_functions.pop("screenshot", None)
        logger.info(
            "Cumulative budget gating disabled screenshot (completed=%s, budget=3).",
            completed_count("screenshot"),
        )

    return gated_functions


def apply_failed_tool_budget_gating(
    *,
    available_functions: Dict[str, Any],
    cumulative_failed_tool_counts: Dict[str, int],
    default_failure_budget: int = 3,
) -> Dict[str, Any]:
    """
    Disable tools that repeatedly fail within the same run.
    """
    gated_functions = dict(available_functions)
    per_tool_limits = {
        "scrape_webpage": 2,
        "browser_navigate_to": 2,
        "browser_click_element": 3,
        "browser_input_text": 3,
        "browser_send_keys": 3,
        "browser_scroll_down": 3,
        "browser_scroll_up": 3,
        "move_to": 3,
        "click": 3,
        "screenshot": 4,
    }

    for tool_name, raw_count in cumulative_failed_tool_counts.items():
        if not isinstance(tool_name, str):
            continue
        if not isinstance(raw_count, int) or raw_count <= 0:
            continue
        limit = per_tool_limits.get(tool_name, default_failure_budget)
        if raw_count < limit:
            continue
        if tool_name in gated_functions:
            gated_functions.pop(tool_name, None)
            logger.info(
                "Failure budget gating disabled %s (failed=%s, budget=%s).",
                tool_name,
                raw_count,
                limit,
            )

    return gated_functions


def apply_required_research_chain_gating(
    *,
    available_functions: Dict[str, Any],
    enforce_chain: bool,
    chain_progress: Dict[str, bool],
    stage_index: Optional[int] = None,
    fallback_functions: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Enforce a minimal deep-research chain:
    create_tasks -> view_tasks -> web_search -> scrape_webpage -> screenshot -> update_tasks
    """
    if not enforce_chain:
        return dict(available_functions)

    gated_functions = dict(available_functions)
    fallback = fallback_functions or {}

    if stage_index is None:
        stage_index = 0
        while (
            stage_index < len(REQUIRED_RESEARCH_CHAIN_STAGES)
            and chain_progress.get(REQUIRED_RESEARCH_CHAIN_STAGES[stage_index][0], False)
        ):
            stage_index += 1
    else:
        stage_index = max(0, min(stage_index, len(REQUIRED_RESEARCH_CHAIN_STAGES)))

    if stage_index >= len(REQUIRED_RESEARCH_CHAIN_STAGES):
        return gated_functions

    for current_stage_index in range(stage_index, len(REQUIRED_RESEARCH_CHAIN_STAGES)):
        stage_key, stage_tools = REQUIRED_RESEARCH_CHAIN_STAGES[current_stage_index]
        if chain_progress.get(stage_key):
            continue

        matched_tools = [tool_name for tool_name in stage_tools if tool_name in gated_functions]
        if not matched_tools:
            # Restore current-stage tool from original toolset when previous gating removed it.
            matched_tools = [tool_name for tool_name in stage_tools if tool_name in fallback]
            if matched_tools:
                constrained = {
                    tool_name: fallback[tool_name]
                    for tool_name in matched_tools
                }
                logger.info(
                    "Enforcing deep-research chain stage '%s' (index=%s) using fallback toolset; restricting tools to %s",
                    stage_key,
                    current_stage_index,
                    matched_tools,
                )
                return constrained
            if stage_key in NON_SKIPPABLE_REQUIRED_STAGE_KEYS:
                logger.warning(
                    "Deep-research chain stage '%s' (index=%s) has no available tools and cannot be skipped; "
                    "returning empty toolset to trigger direct stage compensation.",
                    stage_key,
                    current_stage_index,
                )
                return {}
            logger.info(
                "Deep-research chain stage '%s' (index=%s) has no available tools in current round; trying next stage.",
                stage_key,
                current_stage_index,
            )
            continue

        constrained = {
            tool_name: gated_functions[tool_name]
            for tool_name in matched_tools
        }
        logger.info(
            "Enforcing deep-research chain stage '%s' (index=%s); restricting tools to %s",
            stage_key,
            current_stage_index,
            matched_tools,
        )
        return constrained

    return gated_functions


def build_repeated_tool_recovery_hint(
    signature: Optional[tuple[str, ...]],
) -> Optional[str]:
    """Return an extra one-shot instruction when repeated tool rounds are detected."""
    if not signature:
        return None

    failed_tools = [
        tool_name.split(":", 1)[1]
        for tool_name in signature
        if isinstance(tool_name, str) and tool_name.startswith("failed:")
    ]
    if failed_tools:
        failed_tools_text = ", ".join(sorted(set(failed_tools)))
        return (
            "You are repeatedly calling tools that fail. Stop repeating the same failing call. "
            f"Failed tools in recent rounds: {failed_tools_text}. "
            "Switch to alternative available tools, use existing evidence, and continue the chain."
        )

    planning_signatures = {
        ("create_tasks",),
        ("view_tasks",),
        ("create_tasks", "view_tasks"),
    }
    if signature in planning_signatures:
        return (
            "You are repeating task-planning tools. Do not call create_tasks again unless the "
            "user explicitly asks to replan. Call view_tasks once, execute the next pending task "
            "with execution tools, then use update_tasks."
        )
    if signature == ("screenshot",):
        return (
            "You are repeating screenshot without progress. Perform a concrete computer action "
            "(open/navigate/click/type) before taking another screenshot. If the request is "
            "already satisfied, provide a concise final summary now."
        )
    if signature == ("web_search",):
        return (
            "You are repeating web_search queries. Stop duplicate searches and synthesize the "
            "current evidence into a structured final summary with conclusions, sources, and risks."
        )
    if signature == ("update_tasks",):
        return (
            "You are repeating update_tasks without real task execution progress. Stop calling "
            "update_tasks repeatedly. Call view_tasks, execute the next pending task with domain "
            "tools, then call update_tasks once with concrete completion evidence."
        )
    return None


def merge_temporary_message_with_hint(
    temporary_message: Optional[dict],
    hint_text: Optional[str],
) -> Optional[dict]:
    """Append a textual correction hint to temporary user context for the next iteration."""
    if not hint_text or not isinstance(hint_text, str) or not hint_text.strip():
        return temporary_message

    hint_block = {"type": "text", "text": hint_text.strip()}

    if not temporary_message:
        return {"role": "user", "content": [hint_block]}

    if not isinstance(temporary_message, dict):
        return {"role": "user", "content": [hint_block]}

    merged = dict(temporary_message)
    content = merged.get("content")

    if isinstance(content, list):
        merged["content"] = [*content, hint_block]
    elif isinstance(content, str) and content.strip():
        merged["content"] = [{"type": "text", "text": content}, hint_block]
    else:
        merged["content"] = [hint_block]

    merged.setdefault("role", "user")
    return merged


def _coerce_bool(value: Any) -> bool:
    """Parse bool-like values from mixed config shapes."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on", "enabled"}:
            return True
        if normalized in {"false", "0", "no", "off", "disabled", ""}:
            return False
    return bool(value)


def _normalize_agentpress_tools(raw_tools: Any) -> Optional[Dict[str, Any]]:
    """
    Normalize tools config from common persisted shapes.

    Some historical rows persist `agentpress_tools` as a JSON string.
    """
    if isinstance(raw_tools, dict):
        return raw_tools

    if isinstance(raw_tools, str):
        stripped = raw_tools.strip()
        if not stripped:
            return {}
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    return None


def _is_agentpress_tool_enabled(tool_config: Any) -> bool:
    """Normalize different agentpress tool config shapes to a boolean."""
    if isinstance(tool_config, dict):
        return _coerce_bool(tool_config.get("enabled", False))
    return _coerce_bool(tool_config)


def should_register_default_toolset(agent_config: Optional[Dict[str, Any]]) -> bool:
    """
    Decide whether to register the baseline runtime toolset.

    Rules:
    - Missing/empty agent config => register baseline tools (backward-compatible fallback)
    - AlexManus default agent => register baseline tools
    - Custom agent with no explicit agentpress_tools => register baseline tools (migration-safe)
    - Custom agent with explicit tool config => register only if at least one tool is enabled
    """
    if not isinstance(agent_config, dict) or not agent_config:
        return True

    if agent_config.get("is_AlexManus_default", False):
        return True

    raw_tools = _normalize_agentpress_tools(agent_config.get("agentpress_tools"))
    if raw_tools is None or not raw_tools:
        return True

    return any(_is_agentpress_tool_enabled(tool_cfg) for tool_cfg in raw_tools.values())


def should_register_simple_test_tool(
    env_value: Optional[str] = None,
) -> bool:
    """
    Register SimpleTestTool only when explicitly enabled via env.
    """
    raw_value = env_value if env_value is not None else os.getenv("ENABLE_SIMPLE_TEST_TOOL", "")
    return _coerce_bool(raw_value)


def choose_tool_execution_strategy(
    *,
    enforce_task_chain: bool,
) -> str:
    """
    Pick tool execution strategy for current round.

    Deep-research runs should execute tools in strict sequence to keep behavior
    aligned with task-list order.
    """
    return "sequential" if enforce_task_chain else "parallel"


def choose_max_xml_tool_calls_per_iteration(
    *,
    configured_max_calls: int,
    enforce_task_chain: bool,
    required_chain_stage_index: int,
) -> int:
    """
    Cap same-round XML tool calls to avoid long stalls and out-of-order drift.
    """
    safe_max_calls = max(1, int(configured_max_calls))
    if not enforce_task_chain:
        return safe_max_calls

    # Planning/progress stages must be strictly one-step-per-round.
    if required_chain_stage_index in {0, 1, 5}:
        return 1

    # Execution stages can use at most 2 calls to keep latency bounded.
    return min(safe_max_calls, 2)


def should_force_tool_failed_fallback(
    *,
    stop_reason: Optional[str],
    failed_non_terminating_tools: set[str],
    completed_non_terminating_tools: set[str],
    has_substantive_final_response: bool,
    has_evidence: bool,
) -> bool:
    """
    Decide whether tool failure should force a synthetic fallback summary.
    """
    if stop_reason != "tool_failed":
        return False
    if completed_non_terminating_tools:
        return False
    if not failed_non_terminating_tools:
        return False
    if has_substantive_final_response:
        return False
    return not has_evidence


def should_force_direct_chain_convergence(
    *,
    prefer_task_bootstrap_when_missing: bool,
    stop_reason: Optional[str],
    consecutive_no_real_tool_rounds: int,
    max_no_real_tool_rounds: int,
    has_substantive_final_response: bool,
) -> bool:
    """
    Force direct create/view/search/update chain after repeated rounds without any real tool completion.
    """
    if not prefer_task_bootstrap_when_missing:
        return False
    if has_substantive_final_response:
        return False
    if stop_reason not in {
        "no_tools_completed",
        "tool_failed",
        "repeated_tool_rounds",
        "recoverable_tool_failed",
        "terminated",
    }:
        return False
    if max_no_real_tool_rounds <= 0:
        return False
    return consecutive_no_real_tool_rounds >= max_no_real_tool_rounds


def should_force_structured_summary_without_fallback_notice(
    *,
    stop_reason: Optional[str],
    low_value_final_response: bool,
    has_evidence: bool,
) -> bool:
    """
    Force a structured, no-notice summary when final text is low-value but evidence exists.
    """
    if not low_value_final_response:
        return False
    if not has_evidence:
        return False
    return stop_reason in {
        "no_tools_completed",
        "terminated",
        "tool_failed",
        "repeated_tool_rounds",
    }


def should_retry_after_blocked_tool_call(
    *,
    stop_reason: Optional[str],
    blocked_non_terminating_tools: set[str],
    completed_non_terminating_tools: set[str],
    blocked_retry_count: int,
    max_blocked_retries: int,
) -> bool:
    """
    Allow one bounded recovery retry when the model calls tools blocked by current stage gating.
    """
    if stop_reason != "tool_failed":
        return False
    if not blocked_non_terminating_tools:
        return False
    if completed_non_terminating_tools:
        return False
    return blocked_retry_count < max(0, max_blocked_retries)


def choose_direct_required_stage_compensation(
    *,
    stop_reason: Optional[str],
    required_chain_stage_index: int,
    required_chain_progress: Dict[str, bool],
    blocked_non_terminating_tools: set[str],
) -> Optional[str]:
    """
    Decide whether to directly compensate a required deep-research stage.

    Returns:
        - "create_tasks" when stage-0 is pending and loop stopped due to no-tools
          or blocked tool mismatch.
        - "view_tasks" when stage-1 is pending and loop stopped due to no-tools
          or blocked tool mismatch.
        - "web_search" when stage-2 is pending and loop stopped due to no-tools
          or blocked tool mismatch.
        - "update_tasks" when stage-5 is pending and loop stopped due to no-tools
          or blocked tool mismatch.
        - None otherwise.
    """
    blocked_mismatch = (
        stop_reason in {"tool_failed", "recoverable_tool_failed"}
        and bool(blocked_non_terminating_tools)
    )
    no_tools_stop = stop_reason == "no_tools_completed"
    terminated_without_chain_progress = stop_reason == "terminated"
    if not (blocked_mismatch or no_tools_stop or terminated_without_chain_progress):
        return None

    if (
        required_chain_stage_index == 0
        and not required_chain_progress.get("has_created_tasks", False)
    ):
        return "create_tasks"

    if (
        required_chain_stage_index == 1
        and not required_chain_progress.get("has_viewed_tasks", False)
    ):
        return "view_tasks"

    if (
        required_chain_stage_index == 2
        and not required_chain_progress.get("has_web_search", False)
    ):
        return "web_search"

    if (
        required_chain_stage_index == 5
        and not required_chain_progress.get("has_updated_tasks", False)
    ):
        return "update_tasks"

    return None


class ToolManager:
    def __init__(self, thread_manager: ThreadManager, project_id: str, thread_id: str):
        self.thread_manager = thread_manager
        self.project_id = project_id
        self.thread_id = thread_id
    
    def register_all_tools(self):
        if should_register_simple_test_tool():
            from agent.tools.simple_test_tool import SimpleTestTool
            self.thread_manager.add_tool(SimpleTestTool)
            logger.info("SimpleTestTool registered (ENABLE_SIMPLE_TEST_TOOL=true).")
        else:
            logger.info("SimpleTestTool skipped (set ENABLE_SIMPLE_TEST_TOOL=true to enable).")

        from agent.tools.task_list_tool import TaskListTool
        self.thread_manager.add_tool(TaskListTool, project_id=self.project_id, thread_manager=self.thread_manager, thread_id=self.thread_id)
        
        try:
            from agent.tools.sandbox_web_search_tool import SandboxWebSearchTool
            self.thread_manager.add_tool(
                SandboxWebSearchTool,
                project_id=self.project_id,
                thread_manager=self.thread_manager,
            )
        except Exception as e:
            # Web search is optional in local/dev setups where Tavily isn't installed/configured.
            logger.warning(f"Skipping SandboxWebSearchTool registration: {e}")

        from agent.tools.computer_use_tool import ComputerUseTool
        self.thread_manager.add_tool(ComputerUseTool, project_id=self.project_id, thread_manager=self.thread_manager)
        
        from agent.tools.sb_browser_tool import SandboxBrowserTool
        self.thread_manager.add_tool(SandboxBrowserTool, project_id=self.project_id, thread_manager=self.thread_manager)
    
    def register_agent_builder_tools(self, agent_id: str):
        # TODO
        pass
    
    def register_custom_tools(self, enabled_tools: Dict[str, Any]):
        # TODO
        pass

# class MCPManager:
#     def __init__(self, thread_manager: ThreadManager, account_id: str):
#         self.thread_manager = thread_manager
#         self.account_id = account_id
    
#     async def register_mcp_tools(self, agent_config: dict) -> Optional[MCPToolWrapper]:
#         all_mcps = []
        
#         if agent_config.get('configured_mcps'):
#             all_mcps.extend(agent_config['configured_mcps'])
        
#         if agent_config.get('custom_mcps'):
#             for custom_mcp in agent_config['custom_mcps']:
#                 custom_type = custom_mcp.get('customType', custom_mcp.get('type', 'sse'))
                
#                 if custom_type == 'pipedream':
#                     if 'config' not in custom_mcp:
#                         custom_mcp['config'] = {}
                    
#                     if not custom_mcp['config'].get('external_user_id'):
#                         profile_id = custom_mcp['config'].get('profile_id')
#                         if profile_id:
#                             try:
#                                 from pipedream import profile_service
#                                 from uuid import UUID
                                
#                                 profile = await profile_service.get_profile(UUID(self.account_id), UUID(profile_id))
#                                 if profile:
#                                     custom_mcp['config']['external_user_id'] = profile.external_user_id
#                             except Exception as e:
#                                 logger.error(f"Error retrieving external_user_id from profile {profile_id}: {e}")
                    
#                     if 'headers' in custom_mcp['config'] and 'x-pd-app-slug' in custom_mcp['config']['headers']:
#                         custom_mcp['config']['app_slug'] = custom_mcp['config']['headers']['x-pd-app-slug']
                
#                 elif custom_type == 'composio':
#                     qualified_name = custom_mcp.get('qualifiedName')
#                     if not qualified_name:
#                         qualified_name = f"composio.{custom_mcp['name'].replace(' ', '_').lower()}"
                    
#                     mcp_config = {
#                         'name': custom_mcp['name'],
#                         'qualifiedName': qualified_name,
#                         'config': custom_mcp.get('config', {}),
#                         'enabledTools': custom_mcp.get('enabledTools', []),
#                         'instructions': custom_mcp.get('instructions', ''),
#                         'isCustom': True,
#                         'customType': 'composio'
#                     }
#                     all_mcps.append(mcp_config)
#                     continue
                
#                 mcp_config = {
#                     'name': custom_mcp['name'],
#                     'qualifiedName': f"custom_{custom_type}_{custom_mcp['name'].replace(' ', '_').lower()}",
#                     'config': custom_mcp['config'],
#                     'enabledTools': custom_mcp.get('enabledTools', []),
#                     'instructions': custom_mcp.get('instructions', ''),
#                     'isCustom': True,
#                     'customType': custom_type
#                 }
#                 all_mcps.append(mcp_config)
        
#         if not all_mcps:
#             return None
        
#         mcp_wrapper_instance = MCPToolWrapper(mcp_configs=all_mcps)
#         try:
#             await mcp_wrapper_instance.initialize_and_register_tools()
            
#             updated_schemas = mcp_wrapper_instance.get_schemas()
#             for method_name, schema_list in updated_schemas.items():
#                 for schema in schema_list:
#                     self.thread_manager.tool_registry.tools[method_name] = {
#                         "instance": mcp_wrapper_instance,
#                         "schema": schema
#                     }
            
#             logger.info(f"⚡ Registered {len(updated_schemas)} MCP tools (Redis cache enabled)")
#             return mcp_wrapper_instance
#         except Exception as e:
#             logger.error(f"Failed to initialize MCP tools: {e}")
#             return None


class PromptManager:
    @staticmethod
    # async def build_system_prompt(model_name: str, agent_config: Optional[dict], 
    #                               is_agent_builder: bool, thread_id: str, 
    #                               mcp_wrapper_instance: Optional[MCPToolWrapper]) -> dict:
    async def build_system_prompt(model_name: str, agent_config: Optional[dict], 
                                  is_agent_builder: bool, thread_id: str, ) -> dict:    
        
        # 可以根据不同模型的特性，添加不同的系统提示词
        if "gemini-2.5-flash" in model_name.lower() and "gemini-2.5-pro" not in model_name.lower():
            default_system_content = get_gemini_system_prompt()
        else:
            default_system_content = get_system_prompt()
        
        system_content = default_system_content

        now = datetime.datetime.now(datetime.timezone.utc)
        datetime_info = f"\n\n=== CURRENT DATE/TIME INFORMATION ===\n"
        datetime_info += f"Today's date: {now.strftime('%A, %B %d, %Y')}\n"
        datetime_info += f"Current UTC time: {now.strftime('%H:%M:%S UTC')}\n"
        datetime_info += f"Current year: {now.strftime('%Y')}\n"
        datetime_info += f"Current month: {now.strftime('%B')}\n"
        datetime_info += f"Current day: {now.strftime('%A')}\n"
        datetime_info += "Use this information for any time-sensitive tasks, research, or when current date/time context is needed.\n"
        
        system_content += datetime_info

        return {"role": "system", "content": system_content}

class MessageManager:
    """
    消息管理器类
    
    负责构建临时消息，包括浏览器状态和图像上下文信息。
    这些临时消息会在AI处理用户请求时作为上下文信息提供给模型。
    """
    
    def __init__(self, client, thread_id: str, model_name: str, trace: Optional[StatefulTraceClient]): # type: ignore
        """
        初始化消息管理器
        
        Args:
            client: 数据库客户端，用于查询消息表
            thread_id: 线程ID，用于标识特定的对话线程
            model_name: 模型名称，用于判断是否支持图像处理
            trace: 追踪客户端，用于日志记录
        """
        self.client = client
        self.thread_id = thread_id
        self.model_name = model_name
        self.trace = trace
    
    async def build_temporary_message(self) -> Optional[dict]:
        """
        构建临时消息
        
        这个方法会：
        1. 获取最新的浏览器状态信息（包括截图）
        2. 获取最新的图像上下文信息
        3. 将这些信息组合成一个临时消息，供AI模型使用
        
        Returns:
            Optional[dict]: 包含浏览器状态和图像信息的临时消息，如果没有相关信息则返回None
        """
        temp_message_content_list = []  # 存储临时消息的内容列表

        # 获取最新的浏览器状态消息
        latest_browser_state_msg = await self.client.table('messages').select('*').eq('thread_id', self.thread_id).eq('type', 'browser_state').order('created_at', desc=True).limit(1).execute()
        
        if latest_browser_state_msg.data and len(latest_browser_state_msg.data) > 0:
            try:
                # 解析浏览器状态内容
                browser_content = latest_browser_state_msg.data[0]["content"]
                if isinstance(browser_content, str):
                    browser_content = json.loads(browser_content)
                
                # 提取截图信息
                screenshot_base64 = browser_content.get("screenshot_base64")  # Base64编码的截图
                screenshot_url = browser_content.get("base64_data")  # 截图的base64数据
                
                # 复制浏览器状态文本，移除截图相关字段
                browser_state_text = browser_content.copy()
                browser_state_text.pop('screenshot_base64', None)
                browser_state_text.pop('base64_data', None)

                # 如果有浏览器状态文本信息，添加到临时消息中
                if browser_state_text:
                    temp_message_content_list.append({
                        "type": "text",
                        "text": f"The following is the current state of the browser:\n{json.dumps(browser_state_text, indent=2)}"
                    })
                
                # 检查模型是否支持图像处理（Gemini、Anthropic、OpenAI）
                if 'gemini' in self.model_name.lower() or 'anthropic' in self.model_name.lower() or 'openai' in self.model_name.lower():
                    # 优先使用URL，如果没有则使用Base64
                    if screenshot_url:
                        temp_message_content_list.append({
                            "type": "image_url",
                            "image_url": {
                                "url": screenshot_url,
                                "format": "image/jpeg"
                            }
                        })
                    elif screenshot_base64:
                        temp_message_content_list.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{screenshot_base64}",
                            }
                        })

            except Exception as e:
                logger.error(f"Error parsing browser state: {e}")

        # 获取最新的图像上下文消息
        latest_image_context_msg = await self.client.table('messages').select('*').eq('thread_id', self.thread_id).eq('type', 'image_context').order('created_at', desc=True).limit(1).execute()
        
        if latest_image_context_msg.data and len(latest_image_context_msg.data) > 0:
            try:
                # 解析图像上下文内容
                image_context_content = latest_image_context_msg.data[0]["content"] if isinstance(latest_image_context_msg.data[0]["content"], dict) else json.loads(latest_image_context_msg.data[0]["content"])
                
                # 提取图像信息
                base64_image = image_context_content.get("base64")  # Base64编码的图像
                mime_type = image_context_content.get("mime_type")  # 图像的MIME类型
                file_path = image_context_content.get("file_path", "unknown file")  # 图像文件路径

                # 如果有图像数据，添加到临时消息中
                if base64_image and mime_type:
                    # 添加图像描述文本
                    temp_message_content_list.append({
                        "type": "text",
                        "text": f"Here is the image you requested to see: '{file_path}'"
                    })
                    # 添加图像URL
                    temp_message_content_list.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{base64_image}",
                        }
                    })

                # 处理完图像上下文后，删除该消息（避免重复使用）
                await self.client.table('messages').delete().eq('message_id', latest_image_context_msg.data[0]["message_id"]).execute()
                
            except Exception as e:
                logger.error(f"Error parsing image context: {e}")

        # 如果有临时消息内容，返回格式化的消息
        if temp_message_content_list:
            return {"role": "user", "content": temp_message_content_list}
        return None

class AgentRunner:

    def __init__(self, config: AgentConfig):
        self.config = config

    async def _latest_task_list_state(self) -> Dict[str, Any]:
        """Inspect latest task_list message for tool-gating decisions."""
        state: Dict[str, Any] = {
            "exists": False,
            "total_tasks": 0,
            "completed_tasks": 0,
            "pending_tasks": 0,
            "next_pending_task_content": "",
        }

        try:
            result = await self.client.table('messages').select('content').eq(
                'thread_id', self.config.thread_id
            ).eq(
                'type', 'task_list'
            ).order(
                'created_at', desc=True
            ).limit(1).execute()

            if not result.data:
                return state

            state["exists"] = True
            content = result.data[0].get('content')
            if isinstance(content, str):
                content = json.loads(content)

            tasks = content.get('tasks', []) if isinstance(content, dict) else []
            state["total_tasks"] = len(tasks) if isinstance(tasks, list) else 0

            if not isinstance(tasks, list):
                return state

            for task in tasks:
                if not isinstance(task, dict):
                    continue
                status = str(task.get("status", "")).strip().lower()
                if status == "completed":
                    state["completed_tasks"] += 1
                else:
                    state["pending_tasks"] += 1
                    if not state["next_pending_task_content"]:
                        state["next_pending_task_content"] = str(task.get("content", "")).strip()
        except Exception as e:
            logger.warning(f"Failed to read task_list state for tool gating: {e}")

        return state

    async def _direct_create_tasks_fallback(self, user_request: Optional[str]) -> bool:
        """Create a minimal executable task list when stage-0 bootstrap is skipped by the model."""
        try:
            from agent.tools.task_list_tool import TaskListTool

            normalized_request = (
                user_request.strip()
                if isinstance(user_request, str) and user_request.strip()
                else "Complete requested deep-research workflow"
            )
            plan_tasks = [
                f"Clarify scope and key objective: {normalized_request}",
                "Collect evidence using web_search and capture key sources",
                "Synthesize findings and mark progress via update_tasks",
            ]

            tool = TaskListTool(
                project_id=self.config.project_id,
                thread_manager=self.thread_manager,
                thread_id=self.config.thread_id,
            )
            result = await tool.create_tasks(
                section_title="Deep Research Plan",
                task_contents=plan_tasks,
            )
            if not result or not result.success:
                logger.warning(
                    "Direct fallback create_tasks failed: %s",
                    getattr(result, "output", "unknown error"),
                )
                return False
            return True
        except Exception as e:
            logger.warning(f"Direct fallback create_tasks execution failed: {e}")
            return False

    async def _direct_view_tasks_fallback(self) -> bool:
        """Force one task-list inspection when stage-1 is pending but model refuses to call view_tasks."""
        try:
            from agent.tools.task_list_tool import TaskListTool

            tool = TaskListTool(
                project_id=self.config.project_id,
                thread_manager=self.thread_manager,
                thread_id=self.config.thread_id,
            )
            result = await tool.view_tasks()
            if not result or not result.success:
                logger.warning(
                    "Direct fallback view_tasks failed: %s",
                    getattr(result, "output", "unknown error"),
                )
                return False
            return True
        except Exception as e:
            logger.warning(f"Direct fallback view_tasks execution failed: {e}")
            return False

    async def _direct_web_search_fallback_results(
        self,
        query: str,
        max_items: int = 5,
    ) -> List[Dict[str, str]]:
        """Run one direct web_search call when the model is stuck in non-search loops."""
        if not query or not isinstance(query, str):
            return []

        try:
            from agent.tools.sandbox_web_search_tool import SandboxWebSearchTool

            tool = SandboxWebSearchTool(
                project_id=self.config.project_id,
                thread_manager=self.thread_manager,
            )
            result = await tool.web_search(query=query.strip(), num_results=max_items)
            if not result or not result.success:
                logger.warning(
                    "Direct fallback web_search failed: %s",
                    getattr(result, "output", "unknown error"),
                )
                return []

            payload = json.loads(result.output) if isinstance(result.output, str) else {}
            return normalize_web_search_results(payload.get("results"), max_items=max_items)
        except Exception as e:
            logger.warning(f"Direct fallback web_search execution failed: {e}")
            return []

    async def _direct_screenshot_fallback_summary(self) -> Optional[Dict[str, Any]]:
        """Capture one deterministic screenshot when tool loops are stuck."""
        try:
            from agent.tools.computer_use_tool import ComputerUseTool

            for attempt in range(2):
                tool = ComputerUseTool(
                    project_id=self.config.project_id,
                    thread_manager=self.thread_manager,
                )
                result = await tool.screenshot()
                if result and result.success:
                    payload = json.loads(result.output) if isinstance(result.output, str) else {}
                    if not isinstance(payload, dict):
                        return None

                    screenshot_obj = payload.get("screenshot", {})
                    if not isinstance(screenshot_obj, dict):
                        screenshot_obj = {}

                    url = str(
                        screenshot_obj.get("url")
                        or payload.get("base64_data")
                        or ""
                    ).strip()
                    if not url:
                        return None

                    width = screenshot_obj.get("width")
                    height = screenshot_obj.get("height")
                    timestamp = str(payload.get("timestamp") or "").strip()

                    return {
                        "url": url,
                        "width": width if isinstance(width, int) else None,
                        "height": height if isinstance(height, int) else None,
                        "timestamp": timestamp,
                    }

                output_text = str(getattr(result, "output", "unknown error"))
                should_reset_sandbox = (
                    attempt == 0
                    and (
                        "could not be instantiated" in output_text
                        or "doesn't exist" in output_text
                    )
                )
                if should_reset_sandbox:
                    reset_ok = await self._reset_project_sandbox_metadata()
                    if reset_ok:
                        logger.warning(
                            "Direct fallback screenshot hit stale sandbox metadata; reset and retry once."
                        )
                        continue

                logger.warning("Direct fallback screenshot failed: %s", output_text)
                return None
        except Exception as e:
            logger.warning(f"Direct fallback screenshot execution failed: {e}")
            return None

    async def _direct_update_tasks_fallback(self) -> bool:
        """Mark at least one pending task completed when model refuses update_tasks stage."""
        try:
            from agent.tools.task_list_tool import TaskListTool

            tool = TaskListTool(
                project_id=self.config.project_id,
                thread_manager=self.thread_manager,
                thread_id=self.config.thread_id,
            )
            result = await tool.update_tasks(status="completed")
            if not result or not result.success:
                logger.warning(
                    "Direct fallback update_tasks failed: %s",
                    getattr(result, "output", "unknown error"),
                )
                return False
            return True
        except Exception as e:
            logger.warning(f"Direct fallback update_tasks execution failed: {e}")
            return False

    async def _direct_execute_required_chain_convergence(
        self,
        *,
        user_request: Optional[str],
        task_list_state: Optional[Dict[str, Any]],
        existing_web_search_results: Optional[List[Dict[str, str]]] = None,
        max_search_items: int = 5,
    ) -> Dict[str, Any]:
        """Directly execute create/view/search/update chain as hard convergence path."""
        direct_results = normalize_web_search_results(
            existing_web_search_results or [],
            max_items=max_search_items,
        )
        create_ok = await self._direct_create_tasks_fallback(user_request)
        view_ok = await self._direct_view_tasks_fallback()

        refreshed_task_list_state = await self._latest_task_list_state()
        state_for_query = (
            refreshed_task_list_state
            if isinstance(refreshed_task_list_state, dict)
            else (task_list_state or {})
        )
        primary_query = (
            str(state_for_query.get("next_pending_task_content") or "").strip()
            if isinstance(state_for_query, dict)
            else ""
        )
        fallback_query = (
            user_request.strip()
            if isinstance(user_request, str)
            else ""
        )
        query_candidates: List[str] = []
        for query in (primary_query, fallback_query):
            normalized_query = query.strip()
            if normalized_query and normalized_query not in query_candidates:
                query_candidates.append(normalized_query)

        if not direct_results:
            for query in query_candidates:
                direct_results = await self._direct_web_search_fallback_results(
                    query=query,
                    max_items=max_search_items,
                )
                if direct_results:
                    break

        update_ok = await self._direct_update_tasks_fallback()

        return {
            "create_ok": create_ok,
            "view_ok": view_ok,
            "update_ok": update_ok,
            "results": direct_results,
            "query_candidates": query_candidates,
        }

    async def _reset_project_sandbox_metadata(self) -> bool:
        """Clear stale sandbox metadata so the next tool call can lazily recreate sandbox."""
        try:
            if not getattr(self, "client", None):
                return False
            project_table = self.client.table("projects").eq(
                "project_id",
                self.config.project_id,
            )
            await project_table.update({"sandbox": json.dumps({})})
            return True
        except Exception as e:
            logger.warning(f"Failed to reset stale project sandbox metadata: {e}")
            return False
    
    async def setup(self):
        try:
            if not self.config.trace:
                self.config.trace = langfuse.trace(name="run_agent", session_id=self.config.thread_id, metadata={"project_id": self.config.project_id})
                logger.info(f"Langfuse trace created successfully")
            else:
                logger.info(f"Using existing trace")
     
            # 使用 Google ADK 框架承接服务
            self.thread_manager = ADKThreadManager(
                        project_id=self.config.project_id,  # 传递实际的project_id
                        trace=self.config.trace, 
                        is_agent_builder=self.config.is_agent_builder or False, 
                        target_agent_id=self.config.target_agent_id, 
                        agent_config=self.config.agent_config
                    )
            logger.info(f"ADKThreadManager created successfully")

            # 初始化数据库客户端
            self.client = await self.thread_manager.db.client
            logger.info(f"Database client initialized successfully")

            # 获取账户ID
            from utils.auth_utils import AuthUtils
            self.account_id = await AuthUtils.get_account_id_from_thread(self.client, self.config.thread_id)
            if not self.account_id: 
                raise ValueError("Could not determine account ID for thread")

            # 获取项目信息
            project = await self.client.table('projects').select('*').eq('project_id', self.config.project_id).execute()
            if not project.data or len(project.data) == 0:
                raise ValueError(f"Project {self.config.project_id} not found")

            project_data = project.data[0]
            sandbox_info = project_data.get('sandbox', {})

            # 处理 sandbox_info 可能是字符串的情况
            if isinstance(sandbox_info, str):
                try:
                    import json
                    sandbox_info = json.loads(sandbox_info)
                except (json.JSONDecodeError, TypeError):
                    sandbox_info = {}

            if not sandbox_info.get('id'):
                # 沙箱是懒加载的，当需要时创建和持久化沙箱元数据
                # 如果沙箱不存在，工具会调用 `_ensure_sandbox()` 来创建和持久化沙箱元数据
                logger.info(f"No sandbox found for project {self.config.project_id}; will create lazily when needed")
            
        except Exception as setup_error:
            logger.error(f"Error details: {traceback.format_exc()}")
            raise setup_error
        
    async def setup_tools(self):
        tool_manager = ToolManager(self.thread_manager, self.config.project_id, self.config.thread_id)
        if should_register_default_toolset(self.config.agent_config):
            tool_manager.register_all_tools()
            available_functions = self.thread_manager.tool_registry.get_available_functions()
            logger.info(
                f"Registered baseline AgentPress toolset for current run "
                f"(tool_count={len(available_functions)}, tools={list(available_functions.keys())})"
            )
        else:
            logger.warning(
                "Agent config explicitly disabled all AgentPress tools; "
                "running without baseline toolset"
            )
    
    async def run(self) -> AsyncGenerator[Dict[str, Any], None]:
        await self.setup()
        await self.setup_tools()

        # TODO : 接入MCP
        # mcp_wrapper_instance = await self.setup_mcp_tools()

        # 构建系统提示词
        system_message = await PromptManager.build_system_prompt(
            self.config.model_name, 
            self.config.agent_config, 
            self.config.is_agent_builder,
            self.config.thread_id, 
        )
        # 初始化迭代次数
        iteration_count = 0

        # 初始化继续执行标志
        continue_execution = True

        # 获取最新消息 - 从events表获取
        latest_user_message = await self.client.table('events').select('*').eq('session_id', self.config.thread_id).order('timestamp', desc=True).limit(10).execute()

        # 提取用户请求内容
        user_request = None
        if latest_user_message.data and len(latest_user_message.data) > 0:            
            # 找到最新的用户消息
            for i, event in enumerate(latest_user_message.data):
                if event.get('author') == 'user':
                    content = event.get('content', {})
                    timestamp = event.get('timestamp')
                    
                    import json
                    # 解析content字段
                    if isinstance(content, str):
                        try:
                            content = json.loads(content)
                        except json.JSONDecodeError:
                            content = {"content": content}
                    
                    # 提取用户请求
                    if isinstance(content, dict):
                        if isinstance(content.get('content'), str) and content.get('content', '').strip():
                            user_request = content.get('content', '')
                        elif isinstance(content.get('text'), str) and content.get('text', '').strip():
                            user_request = content.get('text', '')
                        elif isinstance(content.get('parts'), list):
                            text_parts: List[str] = []
                            for part in content.get('parts', []):
                                if isinstance(part, dict):
                                    text = part.get('text')
                                    if isinstance(text, str) and text.strip():
                                        text_parts.append(text.strip())
                            user_request = "\n".join(text_parts).strip()
                        else:
                            user_request = ''
                        logger.info(f"Extracted user request: {user_request}")
                    break
            
            if self.config.trace and user_request:
                self.config.trace.update(input=user_request)

        message_manager = MessageManager(self.client, self.config.thread_id, self.config.model_name, self.config.trace)
        previous_completed_signature: Optional[tuple[str, ...]] = None
        repeated_signature_streak = 0
        max_repeated_tool_rounds = 5
        repeated_signature_recovery_counts: Dict[tuple[str, ...], int] = {}
        max_repeated_signature_recovery_attempts = 1
        pending_recovery_hint: Optional[str] = None
        latest_web_search_results: List[Dict[str, str]] = []
        latest_screenshot_summary: Optional[Dict[str, Any]] = None
        last_full_response_text = ""
        active_model_name = self.config.model_name
        configured_stream_error_fallback_model = os.getenv(
            "RECOVERABLE_STREAM_FALLBACK_MODEL",
            "deepseek-v3.2",
        )
        recoverable_stream_error_retry_count = 0
        max_recoverable_stream_error_retries = 2
        recent_provider_account_error_message: Optional[str] = None
        require_scrape_stage = should_require_scrape_stage(user_request)
        require_screenshot_stage = should_require_screenshot_stage(user_request)
        required_chain_progress: Dict[str, bool] = {
            "has_created_tasks": False,
            "has_viewed_tasks": False,
            "has_web_search": False,
            "has_scrape_webpage": not require_scrape_stage,
            "has_screenshot": not require_screenshot_stage,
            "has_updated_tasks": False,
        }
        required_chain_stage_index = 0
        required_chain_scrape_failed = False
        required_chain_update_retry_count = 0
        max_required_chain_update_retries = 3
        cumulative_completed_tool_counts: Dict[str, int] = {}
        cumulative_failed_tool_counts: Dict[str, int] = {}
        blocked_tool_recovery_retry_count = 0
        max_blocked_tool_recovery_retries = 1
        final_summary_retry_count = 0
        max_final_summary_retries = 1
        consecutive_no_real_tool_rounds = 0
        require_view_tasks_refresh_before_execution = False
        recent_balance_not_enough_error_message: Optional[str] = None
        try:
            max_no_real_tool_rounds_before_direct_chain = max(
                1,
                int(os.getenv("DEEP_FORCE_DIRECT_CHAIN_NO_TOOL_ROUNDS", "3")),
            )
        except ValueError:
            max_no_real_tool_rounds_before_direct_chain = 3
        run_started_at = datetime.datetime.now(datetime.timezone.utc)
        time_budget_exceeded = False
        try:
            max_agent_run_seconds = max(
                60,
                int(os.getenv("MAX_AGENT_RUN_SECONDS", "180")),
            )
        except ValueError:
            max_agent_run_seconds = 180
        try:
            max_xml_tool_calls_per_iteration = max(
                1,
                int(os.getenv("MAX_XML_TOOL_CALLS_PER_ITERATION", "8")),
            )
        except ValueError:
            max_xml_tool_calls_per_iteration = 8

        # 进入循环执行
        while continue_execution and iteration_count < self.config.max_iterations:
            elapsed_seconds = (
                datetime.datetime.now(datetime.timezone.utc) - run_started_at
            ).total_seconds()
            if elapsed_seconds >= max_agent_run_seconds:
                time_budget_exceeded = True
                continue_execution = False
                logger.warning(
                    "Stopping agent execution due to runtime budget exceeded (%ss >= %ss).",
                    int(elapsed_seconds),
                    max_agent_run_seconds,
                )
                break

            iteration_count += 1          
            logger.info(
                "Looping：continue_execution=%s, iteration_count=%s, max_iterations=%s, active_model=%s",
                continue_execution,
                iteration_count,
                self.config.max_iterations,
                active_model_name,
            )
        
            temporary_message = await message_manager.build_temporary_message()
            temporary_message = merge_temporary_message_with_hint(
                temporary_message,
                pending_recovery_hint,
            )
            pending_recovery_hint = None
            logger.info(f"temporary_message created successfully: {temporary_message}")
            
            generation = self.config.trace.generation(name="thread_manager.run_thread") if self.config.trace else None
            try:          
                # 获取可用函数
                raw_available_functions = self.thread_manager.tool_registry.get_available_functions()
                available_functions = dict(raw_available_functions)

                task_list_state = await self._latest_task_list_state()
                allow_task_replan = should_allow_task_replan(user_request)
                prefer_task_bootstrap_when_missing = should_require_task_list_bootstrap(
                    user_request
                )
                required_chain_stage_index = advance_required_research_chain_state(
                    chain_progress=required_chain_progress,
                    current_stage_index=required_chain_stage_index,
                    task_list_state=task_list_state,
                    available_functions=raw_available_functions,
                    scrape_stage_failed=required_chain_scrape_failed,
                )
                if required_chain_stage_index < 5:
                    required_chain_update_retry_count = 0
                bootstrap_completed = required_chain_stage_index > 0
                pending_tasks = task_list_state.get("pending_tasks", 0)
                has_pending_tasks = isinstance(pending_tasks, int) and pending_tasks > 0
                if not has_pending_tasks:
                    require_view_tasks_refresh_before_execution = False
                logger.info(
                    "Deep-research chain state before gating: stage_index=%s/%s, progress=%s, task_list_state=%s, allow_task_replan=%s, prefer_task_bootstrap=%s, require_scrape_stage=%s, require_screenshot_stage=%s, require_view_refresh=%s, scrape_failed=%s",
                    required_chain_stage_index,
                    len(REQUIRED_RESEARCH_CHAIN_STAGES),
                    required_chain_progress,
                    task_list_state,
                    allow_task_replan,
                    prefer_task_bootstrap_when_missing,
                    require_scrape_stage,
                    require_screenshot_stage,
                    require_view_tasks_refresh_before_execution,
                    required_chain_scrape_failed,
                )
                available_functions = apply_task_list_tool_gating(
                    available_functions=available_functions,
                    task_list_state=task_list_state,
                    allow_task_replan=allow_task_replan,
                    previous_completed_signature=previous_completed_signature,
                    repeated_signature_streak=repeated_signature_streak,
                    prefer_task_bootstrap_when_missing=prefer_task_bootstrap_when_missing,
                    bootstrap_completed=bootstrap_completed,
                    require_view_tasks_refresh_before_execution=require_view_tasks_refresh_before_execution,
                )
                available_functions = apply_deep_research_focus_gating(
                    available_functions=available_functions,
                    user_request=user_request,
                    allow_task_replan=allow_task_replan,
                )
                available_functions = apply_high_frequency_tool_gating(
                    available_functions=available_functions,
                    previous_completed_signature=previous_completed_signature,
                    repeated_signature_streak=repeated_signature_streak,
                    task_list_state=task_list_state,
                )
                available_functions = apply_cumulative_tool_budget_gating(
                    available_functions=available_functions,
                    cumulative_completed_tool_counts=cumulative_completed_tool_counts,
                    allow_task_replan=allow_task_replan,
                )
                available_functions = apply_failed_tool_budget_gating(
                    available_functions=available_functions,
                    cumulative_failed_tool_counts=cumulative_failed_tool_counts,
                )
                chain_fallback_functions = apply_deep_research_focus_gating(
                    available_functions=raw_available_functions,
                    user_request=user_request,
                    allow_task_replan=allow_task_replan,
                )
                available_functions = apply_required_research_chain_gating(
                    available_functions=available_functions,
                    enforce_chain=prefer_task_bootstrap_when_missing,
                    chain_progress=required_chain_progress,
                    stage_index=required_chain_stage_index,
                    fallback_functions=chain_fallback_functions,
                )

                # TODO
                # 获取可用的 MCP Servers
                logger.info(f"Get available functions: {list(available_functions.keys())}")
                effective_tool_execution_strategy = choose_tool_execution_strategy(
                    enforce_task_chain=prefer_task_bootstrap_when_missing,
                )
                effective_max_xml_tool_calls = choose_max_xml_tool_calls_per_iteration(
                    configured_max_calls=max_xml_tool_calls_per_iteration,
                    enforce_task_chain=prefer_task_bootstrap_when_missing,
                    required_chain_stage_index=required_chain_stage_index,
                )

                response = await self.thread_manager.run_thread( 
                        thread_id=self.config.thread_id,
                        system_prompt=system_message,
                        stream=self.config.stream,
                        llm_model=active_model_name,
                        llm_temperature=0,
                        llm_max_tokens=102400,
                        tool_choice="auto",
                        available_functions = available_functions,
                        max_xml_tool_calls=effective_max_xml_tool_calls,
                        temporary_message=temporary_message,
                        processor_config=ProcessorConfig(
                            xml_tool_calling=True,
                            native_tool_calling=False,
                            execute_tools=True,
                            execute_on_stream=True,
                            tool_execution_strategy=effective_tool_execution_strategy,
                            xml_adding_strategy="user_message",
                            allowed_function_names=set(available_functions.keys()),
                        ),
                        include_xml_examples=True,
                        native_max_auto_continues=self.config.native_max_auto_continues,
                        enable_thinking=self.config.enable_thinking,
                        reasoning_effort=self.config.reasoning_effort,
                        enable_context_manager=self.config.enable_context_manager,
                        generation=generation
                    )
   
                if isinstance(response, dict) and "status" in response and response["status"] == "error":
                    yield response
                    break

                terminating_tool_names = {'ask', 'complete', 'web-browser-takeover'}
                last_tool_call = None
                agent_should_terminate = False
                completed_non_terminating_tools = set()
                failed_non_terminating_tools = set()
                blocked_non_terminating_tools = set()
                error_detected = False
                full_response = ""
                stream_error_message: Optional[str] = None
                stream_error_is_recoverable = False
                tolerated_chain_scrape_failure = False

                try:
                    if hasattr(response, '__aiter__') and not isinstance(response, dict):
                        all_chunk = []
                        index = 0
                        tool_call_assistant_map: Dict[str, str] = {}
                        async for chunk in response:
                            # 拆分包含多个 tool_calls 的最终 assistant 消息，并建立 tool_call_id → assistant_message_id 的映射
                            try:
                                if isinstance(chunk, dict) and chunk.get('type') == 'assistant':
                                    metadata_obj = chunk.get('metadata', {})
                                    if isinstance(metadata_obj, str):
                                        try:
                                            metadata_obj = json.loads(metadata_obj)
                                        except Exception:
                                            metadata_obj = {}
                                    stream_status = metadata_obj.get('stream_status')
                                    if stream_status == 'complete':
                                        content_obj = chunk.get('content', '{}')
                                        if isinstance(content_obj, str):
                                            try:
                                                content_obj = json.loads(content_obj)
                                            except Exception:
                                                content_obj = {}
                                        tool_calls = content_obj.get('tool_calls') or []
                                        if isinstance(tool_calls, list) and len(tool_calls) > 0:
                                            from uuid import uuid4
                                            assistant_text = content_obj.get('content', '')
                                            base_ts_str = chunk.get('created_at')
                                            try:
                                                base_dt = (
                                                    datetime.datetime.fromisoformat(base_ts_str)
                                                    if isinstance(base_ts_str, str)
                                                    else datetime.datetime.now(datetime.timezone.utc)
                                                )
                                            except Exception:
                                                base_dt = datetime.datetime.now(datetime.timezone.utc)
                                            for i, tc in enumerate(tool_calls):
                                                # 🔧 生成确定性UUID，与后端拆分逻辑保持一致
                                                tool_call_id = tc.get('id') if isinstance(tc, dict) else f"unknown_{i}"
                                                import hashlib
                                                seed_data = f"assistant_split_{tool_call_id}_{self.config.thread_id}_{i}_v1"
                                                hash_object = hashlib.md5(seed_data.encode())
                                                hex_dig = hash_object.hexdigest()
                                                new_assistant_id = f"{hex_dig[:8]}-{hex_dig[8:12]}-{hex_dig[12:16]}-{hex_dig[16:20]}-{hex_dig[20:]}"
                                                
                                                new_content = {
                                                    "role": "assistant",
                                                    "content": assistant_text if i == 0 else "",
                                                    "tool_calls": [tc]
                                                }
                                                new_chunk = dict(chunk)
                                                new_chunk['message_id'] = new_assistant_id
                                                new_chunk['content'] = json.dumps(new_content)
                                                # 设置严格递增的 created_at，避免前端 key 抖动
                                                try:
                                                    new_dt = base_dt + datetime.timedelta(milliseconds=i)
                                                    new_chunk['created_at'] = new_dt.isoformat()
                                                except Exception:
                                                    pass
                                                # 为每页提供稳定顺序号
                                                try:
                                                    metadata_copy = dict(metadata_obj) if isinstance(metadata_obj, dict) else {}
                                                    metadata_copy['tool_index'] = i
                                                    new_chunk['metadata'] = json.dumps(metadata_copy)
                                                except Exception:
                                                    pass
                                                # 记录映射，供后续 tool 结果重写assistant_message_id
                                                try:
                                                    tool_call_id = tc.get('id') if isinstance(tc, dict) else None
                                                    if tool_call_id:
                                                        tool_call_assistant_map[tool_call_id] = new_assistant_id
                                                except Exception:
                                                    pass
                                                all_chunk.append({"index": index, "chunk": new_chunk})
                                                index += 1
                                                yield new_chunk
                                            # 不再下发原始的合并assistant，直接进入下一条chunk
                                            continue
                            except Exception:
                                pass

                            # 重写每个工具结果的 assistant_message_id，指向对应拆分后的 assistant 消息
                            try:
                                if isinstance(chunk, dict) and chunk.get('type') == 'tool':
                                    metadata_obj = chunk.get('metadata', {})
                                    if isinstance(metadata_obj, str):
                                        try:
                                            metadata_obj = json.loads(metadata_obj)
                                        except Exception:
                                            metadata_obj = {}
                                    tool_call_id = metadata_obj.get('tool_call_id') or metadata_obj.get('tool_call')
                                    mapped_assistant_id = tool_call_assistant_map.get(str(tool_call_id)) if tool_call_id else None
                                    if mapped_assistant_id:
                                        metadata_obj['assistant_message_id'] = mapped_assistant_id
                                        chunk['metadata'] = json.dumps(metadata_obj)

                                    # Cache latest successful web_search results for deterministic fallback summary.
                                    content_obj = chunk.get('content', {})
                                    if isinstance(content_obj, str):
                                        try:
                                            content_obj = json.loads(content_obj)
                                        except Exception:
                                            content_obj = {}
                                    if isinstance(content_obj, dict):
                                        tool_name = str(content_obj.get('tool_name') or '').strip()
                                        if tool_name == 'web_search':
                                            raw_result = content_obj.get('result', '')
                                            parsed_result = {}
                                            if isinstance(raw_result, str):
                                                try:
                                                    parsed_result = json.loads(raw_result)
                                                except Exception:
                                                    parsed_result = {}
                                            elif isinstance(raw_result, dict):
                                                parsed_result = raw_result

                                            if isinstance(parsed_result, dict):
                                                candidates = parsed_result.get('results') or []
                                                normalized_results: List[Dict[str, str]] = []
                                                if isinstance(candidates, list):
                                                    for item in candidates:
                                                        if not isinstance(item, dict):
                                                            continue
                                                        title = str(item.get('title') or '').strip()
                                                        url = str(item.get('url') or '').strip()
                                                        if title and url:
                                                            normalized_results.append({
                                                                'title': title,
                                                                'url': url,
                                                            })
                                                        if len(normalized_results) >= 10:
                                                            break
                                                if normalized_results:
                                                    latest_web_search_results = normalized_results
                                        elif tool_name == 'screenshot':
                                            raw_result = content_obj.get('result', '')
                                            parsed_result = {}
                                            if isinstance(raw_result, str):
                                                try:
                                                    parsed_result = json.loads(raw_result)
                                                except Exception:
                                                    parsed_result = {}
                                            elif isinstance(raw_result, dict):
                                                parsed_result = raw_result

                                            if isinstance(parsed_result, dict):
                                                screenshot_obj = parsed_result.get('screenshot', {})
                                                if not isinstance(screenshot_obj, dict):
                                                    screenshot_obj = {}
                                                screenshot_url = str(
                                                    screenshot_obj.get('url')
                                                    or parsed_result.get('base64_data')
                                                    or ''
                                                ).strip()
                                                if screenshot_url:
                                                    width = screenshot_obj.get('width')
                                                    height = screenshot_obj.get('height')
                                                    latest_screenshot_summary = {
                                                        'url': screenshot_url,
                                                        'width': width if isinstance(width, int) else None,
                                                        'height': height if isinstance(height, int) else None,
                                                        'timestamp': str(parsed_result.get('timestamp') or '').strip(),
                                                    }
                                        if tool_name and is_tool_blocked_by_current_run(
                                            content_obj.get('result')
                                        ):
                                            blocked_non_terminating_tools.add(tool_name)
                                        tool_result_output = content_obj.get('result')
                                        if is_balance_not_enough_error_message(tool_result_output):
                                            recent_balance_not_enough_error_message = str(
                                                tool_result_output
                                            ).strip()
                            except Exception:
                                pass
                            if isinstance(chunk, dict) and chunk.get('type') == 'status' and chunk.get('status') == 'error':
                                error_detected = True
                                status_error_message = chunk.get('message')
                                if isinstance(status_error_message, str) and status_error_message.strip():
                                    stream_error_message = status_error_message.strip()
                                    stream_error_is_recoverable = (
                                        is_recoverable_stream_error_message(stream_error_message)
                                        or is_provider_account_stream_error_message(stream_error_message)
                                    )
                                    if is_provider_account_stream_error_message(stream_error_message):
                                        recent_provider_account_error_message = stream_error_message
                                    if is_balance_not_enough_error_message(stream_error_message):
                                        recent_balance_not_enough_error_message = stream_error_message
                                all_chunk.append({"index": index, "chunk": chunk})
                                index += 1
                                yield chunk
                                continue

                            if chunk.get('type') == 'status':
                                try:
                                    metadata = chunk.get('metadata', {})
                                    if isinstance(metadata, str):
                                        metadata = json.loads(metadata)
                                    content_obj = chunk.get('content', {})
                                    if isinstance(content_obj, str):
                                        try:
                                            content_obj = json.loads(content_obj)
                                        except Exception:
                                            content_obj = {}

                                    if metadata.get('agent_should_terminate'):
                                        agent_should_terminate = True
                                        if content_obj.get('function_name'):
                                            last_tool_call = content_obj['function_name']
                                        elif content_obj.get('xml_tag_name'):
                                            last_tool_call = content_obj['xml_tag_name']

                                    status_type = content_obj.get('status_type')
                                    function_name = (
                                        content_obj.get('function_name')
                                        or content_obj.get('xml_tag_name')
                                        or ''
                                    )
                                    if isinstance(function_name, str):
                                        function_name = function_name.strip()
                                    else:
                                        function_name = str(function_name).strip()

                                    if function_name:
                                        if function_name in terminating_tool_names and status_type in {
                                            'tool_started',
                                            'tool_completed',
                                            'tool_failed',
                                            'tool_error',
                                        }:
                                            last_tool_call = function_name
                                        elif status_type == 'tool_completed':
                                            completed_non_terminating_tools.add(function_name)
                                            cumulative_completed_tool_counts[function_name] = (
                                                cumulative_completed_tool_counts.get(function_name, 0) + 1
                                            )
                                            if prefer_task_bootstrap_when_missing:
                                                if function_name in {"create_tasks", "update_tasks"}:
                                                    require_view_tasks_refresh_before_execution = True
                                                elif function_name == "view_tasks":
                                                    require_view_tasks_refresh_before_execution = False
                                            updated_stage_key = mark_required_research_chain_progress(
                                                required_chain_progress,
                                                function_name,
                                            )
                                            if function_name == "scrape_webpage":
                                                required_chain_scrape_failed = False
                                            if function_name == "update_tasks":
                                                required_chain_update_retry_count = 0
                                            if updated_stage_key:
                                                required_chain_stage_index = advance_required_research_chain_state(
                                                    chain_progress=required_chain_progress,
                                                    current_stage_index=required_chain_stage_index,
                                                    task_list_state=task_list_state,
                                                    available_functions=chain_fallback_functions,
                                                    scrape_stage_failed=required_chain_scrape_failed,
                                                )
                                                logger.info(
                                                    "Deep-research chain progressed via tool_completed '%s' -> stage_key=%s, stage_index=%s/%s, progress=%s",
                                                    function_name,
                                                    updated_stage_key,
                                                    required_chain_stage_index,
                                                    len(REQUIRED_RESEARCH_CHAIN_STAGES),
                                                    required_chain_progress,
                                                )
                                        elif status_type in {'tool_failed', 'tool_error'}:
                                            failed_non_terminating_tools.add(function_name)
                                            cumulative_failed_tool_counts[function_name] = (
                                                cumulative_failed_tool_counts.get(function_name, 0) + 1
                                            )
                                            maybe_tool_error = (
                                                content_obj.get("message")
                                                or content_obj.get("error")
                                                or content_obj.get("result")
                                            )
                                            if is_balance_not_enough_error_message(maybe_tool_error):
                                                recent_balance_not_enough_error_message = str(
                                                    maybe_tool_error
                                                ).strip()
                                            if function_name == "scrape_webpage":
                                                required_chain_scrape_failed = True
                                                required_chain_stage_index = advance_required_research_chain_state(
                                                    chain_progress=required_chain_progress,
                                                    current_stage_index=required_chain_stage_index,
                                                    task_list_state=task_list_state,
                                                    available_functions=chain_fallback_functions,
                                                    scrape_stage_failed=required_chain_scrape_failed,
                                                )
                                                logger.warning(
                                                    "scrape_webpage failed; advanced deep-research chain to stage_index=%s/%s with progress=%s",
                                                    required_chain_stage_index,
                                                    len(REQUIRED_RESEARCH_CHAIN_STAGES),
                                                    required_chain_progress,
                                                )
                                                if (
                                                    prefer_task_bootstrap_when_missing
                                                    and required_chain_stage_index >= 4
                                                ):
                                                    tolerated_chain_scrape_failure = True

                                    if status_type == 'error':
                                        maybe_error_message = content_obj.get('message')
                                        if isinstance(maybe_error_message, str) and maybe_error_message.strip():
                                            stream_error_message = maybe_error_message.strip()
                                            stream_error_is_recoverable = (
                                                is_recoverable_stream_error_message(stream_error_message)
                                                or is_provider_account_stream_error_message(stream_error_message)
                                            )
                                            if is_provider_account_stream_error_message(stream_error_message):
                                                recent_provider_account_error_message = stream_error_message
                                            if is_balance_not_enough_error_message(stream_error_message):
                                                recent_balance_not_enough_error_message = stream_error_message

                                    # 将包含 tool_call_id 的状态消息也补充 assistant_message_id，便于前端按页更新进度
                                    tool_call_id_in_status = metadata.get('tool_call_id') or content_obj.get('tool_call_id')
                                    if tool_call_id_in_status:
                                        mapped_assistant_id = tool_call_assistant_map.get(str(tool_call_id_in_status))
                                        if mapped_assistant_id:
                                            metadata['assistant_message_id'] = mapped_assistant_id
                                            chunk['metadata'] = json.dumps(metadata)
                                except Exception:
                                    pass
                            
                            if chunk.get('type') == 'assistant' and 'content' in chunk:
                                try:
                                    content = chunk.get('content', '{}')
                                    assistant_text = ""
                                    if isinstance(content, str):
                                        assistant_content_json = json.loads(content)
                                    else:
                                        assistant_content_json = content

                                    if isinstance(assistant_content_json, dict):
                                        maybe_text = assistant_content_json.get('content')
                                        if not isinstance(maybe_text, str):
                                            maybe_text = assistant_content_json.get('text')
                                        if isinstance(maybe_text, str):
                                            assistant_text = maybe_text

                                    if isinstance(assistant_text, str):
                                        full_response += assistant_text
                                        if '</ask>' in assistant_text or '</complete>' in assistant_text or '</web-browser-takeover>' in assistant_text:
                                            if '</ask>' in assistant_text:
                                                            xml_tool = 'ask'
                                            elif '</complete>' in assistant_text:
                                                            xml_tool = 'complete'
                                            elif '</web-browser-takeover>' in assistant_text:
                                                            xml_tool = 'web-browser-takeover'

                                            last_tool_call = xml_tool

                                except json.JSONDecodeError:
                                    # Some adapters may emit plain-text assistant chunks.
                                    if isinstance(content, str):
                                        full_response += content
                                except Exception:
                                    pass

                            all_chunk.append({"index": index, "chunk": chunk})
                            index += 1
                            yield chunk
                    else:
                        error_detected = True

                    if error_detected:
                        if (
                            stream_error_is_recoverable
                            and recoverable_stream_error_retry_count < max_recoverable_stream_error_retries
                        ):
                            recoverable_stream_error_retry_count += 1
                            fallback_model = choose_recoverable_stream_fallback_model(
                                current_model_name=active_model_name,
                                configured_fallback_model=configured_stream_error_fallback_model,
                                error_message=stream_error_message,
                            )
                            if fallback_model:
                                logger.warning(
                                    "Recoverable stream error detected; switching model from %s to %s and retrying (%s/%s).",
                                    active_model_name,
                                    fallback_model,
                                    recoverable_stream_error_retry_count,
                                    max_recoverable_stream_error_retries,
                                )
                                active_model_name = fallback_model
                            else:
                                logger.warning(
                                    "Recoverable stream error detected on model %s; retrying with same model (%s/%s).",
                                    active_model_name,
                                    recoverable_stream_error_retry_count,
                                    max_recoverable_stream_error_retries,
                                )
                            pending_recovery_hint = (
                                "The previous run hit a transient stream connection error. Continue from current context, "
                                "prioritize completing pending tools, and finish with a structured final summary."
                            )
                            continue_execution = True
                            previous_completed_signature = None
                            repeated_signature_streak = 0
                            continue
                        if generation:
                            generation.end(output=full_response, status_message="error_detected", level="ERROR")
                        break
                        
                    effective_failed_non_terminating_tools = (
                        failed_non_terminating_tools - {"scrape_webpage"}
                        if tolerated_chain_scrape_failure
                        else failed_non_terminating_tools
                    )
                    effective_failed_tools_for_continuation = (
                        effective_failed_non_terminating_tools - blocked_non_terminating_tools
                        if blocked_non_terminating_tools and completed_non_terminating_tools
                        else effective_failed_non_terminating_tools
                    )
                    effective_last_tool_call = last_tool_call
                    if (
                        isinstance(last_tool_call, str)
                        and last_tool_call in blocked_non_terminating_tools
                    ):
                        logger.warning(
                            "Ignoring blocked terminating tool '%s' for continuation decision.",
                            last_tool_call,
                        )
                        effective_last_tool_call = None
                    recoverable_non_terminating_tools_for_continuation = (
                        RECOVERABLE_NON_TERMINATING_TOOL_FAILURES - blocked_non_terminating_tools
                    )
                    (
                        continue_execution,
                        previous_completed_signature,
                        repeated_signature_streak,
                        stop_reason,
                    ) = decide_agent_iteration_continuation(
                        agent_should_terminate=agent_should_terminate,
                        last_tool_call=effective_last_tool_call,
                        terminating_tool_names=terminating_tool_names,
                        completed_non_terminating_tools=completed_non_terminating_tools,
                        failed_non_terminating_tools=effective_failed_tools_for_continuation,
                        previous_completed_signature=previous_completed_signature,
                        repeated_signature_streak=repeated_signature_streak,
                        max_repeated_tool_rounds=max_repeated_tool_rounds,
                        recoverable_non_terminating_tools=recoverable_non_terminating_tools_for_continuation,
                    )
                    if completed_non_terminating_tools:
                        blocked_tool_recovery_retry_count = 0
                        consecutive_no_real_tool_rounds = 0
                        recent_balance_not_enough_error_message = None
                    else:
                        consecutive_no_real_tool_rounds += 1

                    round_has_substantive_final_response = (
                        isinstance(full_response, str)
                        and len(full_response.strip()) >= 300
                        and is_structured_research_summary_text(full_response)
                    )
                    balance_not_enough_error_seen = (
                        is_balance_not_enough_error_message(stream_error_message)
                        or is_balance_not_enough_error_message(
                            recent_provider_account_error_message
                        )
                        or bool(recent_balance_not_enough_error_message)
                    )

                    if (
                        should_force_direct_chain_convergence(
                            prefer_task_bootstrap_when_missing=prefer_task_bootstrap_when_missing,
                            stop_reason=stop_reason,
                            consecutive_no_real_tool_rounds=consecutive_no_real_tool_rounds,
                            max_no_real_tool_rounds=max_no_real_tool_rounds_before_direct_chain,
                            has_substantive_final_response=round_has_substantive_final_response,
                        )
                        and not balance_not_enough_error_seen
                    ):
                        direct_chain_state = await self._direct_execute_required_chain_convergence(
                            user_request=user_request,
                            task_list_state=task_list_state,
                            existing_web_search_results=latest_web_search_results,
                            max_search_items=5,
                        )
                        direct_chain_results = normalize_web_search_results(
                            direct_chain_state.get("results", []),
                            max_items=10,
                        )
                        if direct_chain_results:
                            latest_web_search_results = direct_chain_results
                        hard_convergence_text = build_web_search_fallback_text(
                            direct_chain_results,
                            max_items=5,
                            screenshot_summary=latest_screenshot_summary,
                            include_fallback_notice=False,
                        )
                        if not hard_convergence_text:
                            chain_queries = direct_chain_state.get("query_candidates") or []
                            chain_query_text = (
                                " / ".join(chain_queries)
                                if isinstance(chain_queries, list) and chain_queries
                                else "N/A"
                            )
                            hard_convergence_text = "\n".join(
                                [
                                    "基于当前执行结果的结构化总结如下：",
                                    "",
                                    "一、执行概览",
                                    "- 系统在连续多轮无真实工具调用后触发硬收敛策略。",
                                    "- 已直执行完整链路：create_tasks -> view_tasks -> web_search -> update_tasks。",
                                    "",
                                    "二、链路结果",
                                    f"- create_tasks：{'success' if direct_chain_state.get('create_ok') else 'failed'}",
                                    f"- view_tasks：{'success' if direct_chain_state.get('view_ok') else 'failed'}",
                                    f"- web_search：{'success' if direct_chain_results else 'failed'} (query={chain_query_text})",
                                    f"- update_tasks：{'success' if direct_chain_state.get('update_ok') else 'failed'}",
                                    "",
                                    "三、来源与证据",
                                    "- 本轮未检索到可用来源链接，建议检查检索环境后重试。",
                                    "",
                                    "四、下一步建议",
                                    "1. 优先排查工具或网络环境后，复跑同一任务。",
                                    "2. 若仅 web_search 失败，可保留任务清单并补充可用 provider 后继续。",
                                ]
                            )

                        try:
                            hard_convergence_message_id = str(uuid.uuid4())
                            thread_run_id = getattr(self.config, "agent_run_id", None)
                            hard_convergence_metadata = {
                                "stream_status": "complete",
                                "thread_run_id": str(thread_run_id) if thread_run_id is not None else None,
                                "convergence_mode": "hard_direct_chain",
                                "direct_chain_status": {
                                    "create_tasks": bool(direct_chain_state.get("create_ok")),
                                    "view_tasks": bool(direct_chain_state.get("view_ok")),
                                    "web_search": bool(direct_chain_results),
                                    "update_tasks": bool(direct_chain_state.get("update_ok")),
                                },
                            }
                            saved_message = await self.thread_manager.add_message(
                                thread_id=self.config.thread_id,
                                type="assistant",
                                content={"role": "assistant", "content": hard_convergence_text},
                                is_llm_message=True,
                                metadata=hard_convergence_metadata,
                                message_id=hard_convergence_message_id,
                            )
                            yield {
                                "type": "assistant",
                                "message_id": hard_convergence_message_id,
                                "thread_id": self.config.thread_id,
                                "content": json.dumps({"role": "assistant", "content": hard_convergence_text}),
                                "metadata": json.dumps(hard_convergence_metadata),
                                "created_at": (
                                    saved_message.get("created_at").isoformat()
                                    if isinstance(saved_message, dict)
                                    and isinstance(saved_message.get("created_at"), datetime.datetime)
                                    else (
                                        str(saved_message.get("created_at"))
                                        if isinstance(saved_message, dict) and saved_message.get("created_at")
                                        else datetime.datetime.now(datetime.timezone.utc).isoformat()
                                    )
                                ),
                            }
                        except Exception as hard_convergence_emit_error:
                            logger.warning(
                                "Failed to emit hard direct-chain convergence summary: %s",
                                hard_convergence_emit_error,
                            )

                        continue_execution = False
                        previous_completed_signature = None
                        repeated_signature_streak = 0
                        logger.warning(
                            "Triggered hard direct-chain convergence after %s no-real-tool rounds (threshold=%s).",
                            consecutive_no_real_tool_rounds,
                            max_no_real_tool_rounds_before_direct_chain,
                        )
                        continue

                    direct_stage_compensation = choose_direct_required_stage_compensation(
                        stop_reason=stop_reason,
                        required_chain_stage_index=required_chain_stage_index,
                        required_chain_progress=required_chain_progress,
                        blocked_non_terminating_tools=blocked_non_terminating_tools,
                    )
                    should_execute_direct_stage_compensation = (
                        prefer_task_bootstrap_when_missing
                        and direct_stage_compensation in {"create_tasks", "view_tasks", "web_search", "update_tasks"}
                    )

                    if should_retry_after_blocked_tool_call(
                        stop_reason=stop_reason,
                        blocked_non_terminating_tools=blocked_non_terminating_tools,
                        completed_non_terminating_tools=completed_non_terminating_tools,
                        blocked_retry_count=blocked_tool_recovery_retry_count,
                        max_blocked_retries=max_blocked_tool_recovery_retries,
                    ) and not should_execute_direct_stage_compensation:
                        blocked_tool_recovery_retry_count += 1
                        blocked_tools_text = ", ".join(sorted(blocked_non_terminating_tools))
                        allowed_tools_hint = ", ".join(
                            sorted(available_functions.keys())
                        )
                        pending_recovery_hint = (
                            "The previous round called tools that are blocked in the current stage. "
                            f"Blocked tools: {blocked_tools_text}. "
                            "Do not repeat those calls. Use only currently available tools: "
                            f"{allowed_tools_hint}."
                        )
                        continue_execution = True
                        previous_completed_signature = None
                        repeated_signature_streak = 0
                        logger.warning(
                            "Blocked tool call recovery retry (%s/%s). blocked_tools=%s allowed_tools=%s",
                            blocked_tool_recovery_retry_count,
                            max_blocked_tool_recovery_retries,
                            sorted(blocked_non_terminating_tools),
                            sorted(available_functions.keys()),
                        )
                        continue

                    if (
                        prefer_task_bootstrap_when_missing
                        and direct_stage_compensation == "create_tasks"
                    ):
                        direct_create_ok = await self._direct_create_tasks_fallback(user_request)
                        if direct_create_ok:
                            require_view_tasks_refresh_before_execution = True
                            updated_stage_key = mark_required_research_chain_progress(
                                required_chain_progress,
                                "create_tasks",
                            )
                            required_chain_stage_index = advance_required_research_chain_state(
                                chain_progress=required_chain_progress,
                                current_stage_index=required_chain_stage_index,
                                task_list_state=task_list_state,
                                available_functions=chain_fallback_functions,
                                scrape_stage_failed=required_chain_scrape_failed,
                            )
                            pending_recovery_hint = (
                                "Task list is ready. Call view_tasks next, then continue execution tools."
                            )
                            continue_execution = True
                            previous_completed_signature = None
                            repeated_signature_streak = 0
                            blocked_tool_recovery_retry_count = 0
                            consecutive_no_real_tool_rounds = 0
                            logger.warning(
                                "Executed direct required-stage compensation '%s' -> stage_key=%s stage_index=%s/%s.",
                                direct_stage_compensation,
                                updated_stage_key,
                                required_chain_stage_index,
                                len(REQUIRED_RESEARCH_CHAIN_STAGES),
                            )
                            continue

                    if (
                        prefer_task_bootstrap_when_missing
                        and direct_stage_compensation == "view_tasks"
                    ):
                        direct_view_ok = await self._direct_view_tasks_fallback()
                        if direct_view_ok:
                            require_view_tasks_refresh_before_execution = False
                            updated_stage_key = mark_required_research_chain_progress(
                                required_chain_progress,
                                "view_tasks",
                            )
                            required_chain_stage_index = advance_required_research_chain_state(
                                chain_progress=required_chain_progress,
                                current_stage_index=required_chain_stage_index,
                                task_list_state=task_list_state,
                                available_functions=chain_fallback_functions,
                                scrape_stage_failed=required_chain_scrape_failed,
                            )
                            pending_recovery_hint = (
                                "Task list has been viewed. Execute the next pending task using web_search now."
                            )
                            continue_execution = True
                            previous_completed_signature = None
                            repeated_signature_streak = 0
                            blocked_tool_recovery_retry_count = 0
                            consecutive_no_real_tool_rounds = 0
                            logger.warning(
                                "Executed direct required-stage compensation '%s' -> stage_key=%s stage_index=%s/%s.",
                                direct_stage_compensation,
                                updated_stage_key,
                                required_chain_stage_index,
                                len(REQUIRED_RESEARCH_CHAIN_STAGES),
                            )
                            continue

                    if (
                        prefer_task_bootstrap_when_missing
                        and direct_stage_compensation == "web_search"
                    ):
                        primary_query = (
                            str(task_list_state.get("next_pending_task_content") or "").strip()
                            if isinstance(task_list_state, dict)
                            else ""
                        )
                        fallback_query = (
                            user_request.strip()
                            if isinstance(user_request, str)
                            else ""
                        )
                        query_candidates: List[str] = []
                        for query in (primary_query, fallback_query):
                            normalized_query = query.strip()
                            if normalized_query and normalized_query not in query_candidates:
                                query_candidates.append(normalized_query)

                        direct_results: List[Dict[str, str]] = []
                        for compensation_query in query_candidates:
                            direct_results = await self._direct_web_search_fallback_results(
                                query=compensation_query,
                                max_items=5,
                            )
                            if direct_results:
                                break

                        if direct_results:
                            latest_web_search_results = direct_results
                            updated_stage_key = mark_required_research_chain_progress(
                                required_chain_progress,
                                "web_search",
                            )
                            required_chain_stage_index = advance_required_research_chain_state(
                                chain_progress=required_chain_progress,
                                current_stage_index=required_chain_stage_index,
                                task_list_state=task_list_state,
                                available_functions=chain_fallback_functions,
                                scrape_stage_failed=required_chain_scrape_failed,
                            )
                            pending_recovery_hint = (
                                "Web search evidence is ready. Continue required execution stages and avoid blocked tools."
                            )
                            continue_execution = True
                            previous_completed_signature = None
                            repeated_signature_streak = 0
                            blocked_tool_recovery_retry_count = 0
                            consecutive_no_real_tool_rounds = 0
                            logger.warning(
                                "Executed direct required-stage compensation '%s' -> stage_key=%s stage_index=%s/%s.",
                                direct_stage_compensation,
                                updated_stage_key,
                                required_chain_stage_index,
                                len(REQUIRED_RESEARCH_CHAIN_STAGES),
                            )
                            continue
                        logger.warning(
                            "Direct required-stage compensation '%s' triggered but no web search results were returned. queries=%s",
                            direct_stage_compensation,
                            query_candidates,
                        )

                    if (
                        prefer_task_bootstrap_when_missing
                        and direct_stage_compensation == "update_tasks"
                    ):
                        direct_update_ok = await self._direct_update_tasks_fallback()
                        if direct_update_ok:
                            require_view_tasks_refresh_before_execution = True
                            updated_stage_key = mark_required_research_chain_progress(
                                required_chain_progress,
                                "update_tasks",
                            )
                            required_chain_stage_index = advance_required_research_chain_state(
                                chain_progress=required_chain_progress,
                                current_stage_index=required_chain_stage_index,
                                task_list_state=task_list_state,
                                available_functions=chain_fallback_functions,
                                scrape_stage_failed=required_chain_scrape_failed,
                            )
                            required_chain_update_retry_count = 0
                            pending_recovery_hint = (
                                "Task list has been updated. Provide final structured summary after validating evidence."
                            )
                            continue_execution = True
                            previous_completed_signature = None
                            repeated_signature_streak = 0
                            blocked_tool_recovery_retry_count = 0
                            consecutive_no_real_tool_rounds = 0
                            logger.warning(
                                "Executed direct required-stage compensation '%s' -> stage_key=%s stage_index=%s/%s.",
                                direct_stage_compensation,
                                updated_stage_key,
                                required_chain_stage_index,
                                len(REQUIRED_RESEARCH_CHAIN_STAGES),
                            )
                            continue

                    if continue_execution and stop_reason == "recoverable_tool_failed":
                        failed_tools_text = ", ".join(
                            sorted(effective_failed_non_terminating_tools)
                        )
                        pending_recovery_hint = (
                            "Some tools failed in the previous round. "
                            f"Failed tools: {failed_tools_text}. "
                            "Do not repeat identical failing calls. Switch to other available tools, "
                            "use existing evidence, and continue the chain."
                        )

                    if (
                        tolerated_chain_scrape_failure
                        and not continue_execution
                        and stop_reason == "no_tools_completed"
                    ):
                        pending_recovery_hint = (
                            "scrape_webpage failed in the previous round. Continue with screenshot, "
                            "then call update_tasks and finalize a structured report."
                        )
                        continue_execution = True
                        previous_completed_signature = None
                        repeated_signature_streak = 0
                        logger.warning(
                            "Tolerating scrape_webpage failure and continuing deep-research chain."
                        )
                        continue

                    if (
                        prefer_task_bootstrap_when_missing
                        and required_chain_stage_index == 4
                        and not required_chain_progress.get("has_screenshot", False)
                        and not continue_execution
                        and stop_reason == "no_tools_completed"
                    ):
                        direct_screenshot_summary = await self._direct_screenshot_fallback_summary()
                        if direct_screenshot_summary:
                            latest_screenshot_summary = direct_screenshot_summary
                            mark_required_research_chain_progress(
                                required_chain_progress,
                                "screenshot",
                            )
                            required_chain_stage_index = advance_required_research_chain_state(
                                chain_progress=required_chain_progress,
                                current_stage_index=required_chain_stage_index,
                                task_list_state=task_list_state,
                                available_functions=chain_fallback_functions,
                                scrape_stage_failed=required_chain_scrape_failed,
                            )
                            pending_recovery_hint = (
                                "Screenshot evidence is ready. Call update_tasks now, then provide final summary."
                            )
                            continue_execution = True
                            previous_completed_signature = None
                            repeated_signature_streak = 0
                            consecutive_no_real_tool_rounds = 0
                            logger.warning(
                                "Executed direct screenshot fallback to keep deep-research chain progressing."
                            )
                            continue

                    if (
                        prefer_task_bootstrap_when_missing
                        and required_chain_stage_index == 5
                        and not required_chain_progress.get("has_updated_tasks", False)
                        and not continue_execution
                        and stop_reason == "no_tools_completed"
                    ):
                        if required_chain_update_retry_count < max_required_chain_update_retries:
                            required_chain_update_retry_count += 1
                            pending_recovery_hint = (
                                "Do not finish yet. Call update_tasks now with status=\"completed\" "
                                "(task_ids can be omitted to auto-target next pending task), then provide final summary."
                            )
                            continue_execution = True
                            previous_completed_signature = None
                            repeated_signature_streak = 0
                            logger.warning(
                                "Required chain update_tasks stage still pending; retrying model with explicit hint (%s/%s).",
                                required_chain_update_retry_count,
                                max_required_chain_update_retries,
                            )
                            continue

                        direct_update_ok = await self._direct_update_tasks_fallback()
                        if direct_update_ok:
                            require_view_tasks_refresh_before_execution = True
                            mark_required_research_chain_progress(
                                required_chain_progress,
                                "update_tasks",
                            )
                            required_chain_stage_index = advance_required_research_chain_state(
                                chain_progress=required_chain_progress,
                                current_stage_index=required_chain_stage_index,
                                task_list_state=task_list_state,
                                available_functions=chain_fallback_functions,
                                scrape_stage_failed=required_chain_scrape_failed,
                            )
                            required_chain_update_retry_count = 0
                            pending_recovery_hint = (
                                "Task list has been updated. Provide the final structured summary now."
                            )
                            continue_execution = True
                            previous_completed_signature = None
                            repeated_signature_streak = 0
                            consecutive_no_real_tool_rounds = 0
                            logger.warning(
                                "Executed direct update_tasks fallback after repeated no-tool rounds at required update stage."
                            )
                            continue

                    if (
                        prefer_task_bootstrap_when_missing
                        and required_chain_progress.get("has_updated_tasks", False)
                        and not continue_execution
                        and stop_reason == "no_tools_completed"
                        and is_low_value_no_tool_response(full_response)
                    ):
                        if final_summary_retry_count < max_final_summary_retries:
                            final_summary_retry_count += 1
                            pending_recovery_hint = (
                                "The deep-research chain is complete. Do not call more tools. "
                                "Produce the final structured report now with sections: "
                                "conclusion, key evidence, sources, risks, and next steps."
                            )
                            continue_execution = True
                            previous_completed_signature = None
                            repeated_signature_streak = 0
                            logger.warning(
                                "Chain completed but got low-value no-tool response; retrying final summary generation (%s/%s).",
                                final_summary_retry_count,
                                max_final_summary_retries,
                            )
                            continue

                    if (
                        not continue_execution
                        and stop_reason == "repeated_tool_rounds"
                        and previous_completed_signature is not None
                    ):
                        recovery_hint = build_repeated_tool_recovery_hint(previous_completed_signature)
                        if recovery_hint:
                            recovery_attempts = repeated_signature_recovery_counts.get(
                                previous_completed_signature,
                                0,
                            )
                            if recovery_attempts < max_repeated_signature_recovery_attempts:
                                repeated_signature_recovery_counts[previous_completed_signature] = (
                                    recovery_attempts + 1
                                )
                                pending_recovery_hint = recovery_hint
                                continue_execution = True
                                previous_completed_signature = None
                                repeated_signature_streak = 0
                                logger.warning(
                                    "Detected repeated tool rounds for signature=%s; "
                                    "injecting recovery hint and retrying once (attempt=%s/%s).",
                                    tuple(sorted(completed_non_terminating_tools)),
                                    recovery_attempts + 1,
                                    max_repeated_signature_recovery_attempts,
                                )
                                continue

                    recoverable_stream_error_detected = (
                        bool(stream_error_message)
                        and stream_error_is_recoverable
                    )
                    provider_account_stream_error_detected = (
                        bool(stream_error_message)
                        and is_provider_account_stream_error_message(stream_error_message)
                    )
                    if provider_account_stream_error_detected and stream_error_message:
                        recent_provider_account_error_message = stream_error_message
                    if completed_non_terminating_tools:
                        # Tool execution proves the run has recovered from earlier provider rejections.
                        recent_provider_account_error_message = None
                        final_summary_retry_count = 0
                    provider_account_stream_error_seen = (
                        provider_account_stream_error_detected
                        or bool(recent_provider_account_error_message)
                    )
                    balance_not_enough_error_seen = (
                        is_balance_not_enough_error_message(stream_error_message)
                        or is_balance_not_enough_error_message(
                            recent_provider_account_error_message
                        )
                        or bool(recent_balance_not_enough_error_message)
                    )
                    no_non_terminating_tools_completed = not completed_non_terminating_tools
                    low_value_final_response = is_low_value_no_tool_response(full_response)
                    low_value_no_tool_response = (
                        stop_reason in {"no_tools_completed", "terminated"}
                        and no_non_terminating_tools_completed
                        and low_value_final_response
                    )
                    has_substantive_final_response = (
                        isinstance(full_response, str)
                        and len(full_response.strip()) >= 300
                    )
                    if (
                        recoverable_stream_error_detected
                        and not has_substantive_final_response
                        and stop_reason in {"no_tools_completed", "tool_failed"}
                        and recoverable_stream_error_retry_count < max_recoverable_stream_error_retries
                    ):
                        recoverable_stream_error_retry_count += 1
                        fallback_model = choose_recoverable_stream_fallback_model(
                            current_model_name=active_model_name,
                            configured_fallback_model=configured_stream_error_fallback_model,
                            error_message=stream_error_message,
                        )
                        if fallback_model:
                            logger.warning(
                                "Recoverable stream error (%s). Switching model %s -> %s and retrying (%s/%s).",
                                stream_error_message,
                                active_model_name,
                                fallback_model,
                                recoverable_stream_error_retry_count,
                                max_recoverable_stream_error_retries,
                            )
                            active_model_name = fallback_model
                        else:
                            logger.warning(
                                "Recoverable stream error (%s). Retrying model %s (%s/%s).",
                                stream_error_message,
                                active_model_name,
                                recoverable_stream_error_retry_count,
                                max_recoverable_stream_error_retries,
                            )

                        pending_recovery_hint = (
                            "The previous response was interrupted by a transient stream disconnect. "
                            "Continue execution from existing context and produce a complete structured report."
                        )
                        continue_execution = True
                        previous_completed_signature = None
                        repeated_signature_streak = 0
                        continue

                    if continue_execution and stop_reason == "recoverable_tool_failed":
                        logger.warning(
                            "Recoverable tool failures detected; continuing run. failed_tools=%s, streak=%s/%s",
                            sorted(effective_failed_non_terminating_tools),
                            repeated_signature_streak,
                            max_repeated_tool_rounds,
                        )
                    elif continue_execution:
                        logger.info(
                            "Continuing agent execution after completed non-terminating tools: %s (streak=%s/%s)",
                            sorted(completed_non_terminating_tools),
                            repeated_signature_streak,
                            max_repeated_tool_rounds,
                        )
                    elif stop_reason == "tool_failed":
                        logger.warning(
                            "Stopping agent execution after failed non-terminating tools: %s",
                            sorted(failed_non_terminating_tools),
                        )
                    elif stop_reason == "repeated_tool_rounds":
                        logger.warning(
                            "Stopping agent execution after repeated tool rounds: signature=%s, streak=%s",
                            previous_completed_signature,
                            repeated_signature_streak,
                        )
                    elif stop_reason == "terminated":
                        if generation:
                            generation.end(output=full_response, status_message="agent_stopped")

                    low_value_repeated_signatures = {
                        ("create_tasks",),
                        ("view_tasks",),
                        ("create_tasks", "view_tasks"),
                        ("screenshot",),
                    }
                    force_fallback_for_low_value_stop = (
                        stop_reason == "repeated_tool_rounds"
                        and previous_completed_signature in low_value_repeated_signatures
                    )
                    final_response_is_structured = is_structured_research_summary_text(
                        full_response
                    )
                    if prefer_task_bootstrap_when_missing:
                        base_has_substantive_final_response = (
                            isinstance(full_response, str)
                            and len(full_response.strip()) >= 300
                            and final_response_is_structured
                        )
                        has_substantive_final_response = (
                            base_has_substantive_final_response
                            and not force_fallback_for_low_value_stop
                            and not low_value_final_response
                        )
                    else:
                        base_has_substantive_final_response = (
                            isinstance(full_response, str)
                            and len(full_response.strip()) >= 80
                        )
                        # Non-deep runs may contain short concrete deliverables whose
                        # intro text matches low-value markers; keep fallback conservative.
                        has_substantive_final_response = (
                            base_has_substantive_final_response
                            and not force_fallback_for_low_value_stop
                        )
                    force_fallback_for_provider_account_history = (
                        stop_reason in {"no_tools_completed", "terminated"}
                        and no_non_terminating_tools_completed
                        and low_value_no_tool_response
                        and bool(recent_provider_account_error_message)
                        and not has_substantive_final_response
                    )
                    force_fallback_for_stream_error = (
                        (
                            recoverable_stream_error_detected
                            and not has_substantive_final_response
                        )
                        or force_fallback_for_provider_account_history
                    )
                    has_fallback_evidence = bool(latest_web_search_results) or bool(
                        latest_screenshot_summary
                    )
                    force_fallback_for_tool_failed = should_force_tool_failed_fallback(
                        stop_reason=stop_reason,
                        failed_non_terminating_tools=effective_failed_tools_for_continuation,
                        completed_non_terminating_tools=completed_non_terminating_tools,
                        has_substantive_final_response=has_substantive_final_response,
                        has_evidence=has_fallback_evidence,
                    )
                    force_structured_summary_without_fallback_notice = (
                        prefer_task_bootstrap_when_missing
                        and should_force_structured_summary_without_fallback_notice(
                            stop_reason=stop_reason,
                            low_value_final_response=low_value_final_response,
                            has_evidence=has_fallback_evidence,
                        )
                    )
                    force_environment_blocked_report = (
                        balance_not_enough_error_seen
                        and not has_substantive_final_response
                        and stop_reason
                        in {"no_tools_completed", "tool_failed", "terminated", "repeated_tool_rounds"}
                    )
                    logger.info(
                        "Fallback gate snapshot: stop_reason=%s continue=%s deep_mode=%s low_value=%s low_value_no_tool=%s "
                        "has_substantive=%s has_evidence=%s force_low_value_stop=%s force_tool_failed=%s "
                        "force_structured=%s force_stream_error=%s force_env_blocked=%s provider_error_seen=%s response_chars=%s "
                        "completed_tools=%s failed_tools=%s",
                        stop_reason,
                        continue_execution,
                        prefer_task_bootstrap_when_missing,
                        low_value_final_response,
                        low_value_no_tool_response,
                        has_substantive_final_response,
                        has_fallback_evidence,
                        force_fallback_for_low_value_stop,
                        force_fallback_for_tool_failed,
                        force_structured_summary_without_fallback_notice,
                        force_fallback_for_stream_error,
                        force_environment_blocked_report,
                        provider_account_stream_error_seen,
                        len(full_response.strip()) if isinstance(full_response, str) else 0,
                        sorted(completed_non_terminating_tools),
                        sorted(effective_failed_tools_for_continuation),
                    )
                    should_emit_fallback_summary = (
                        (
                            not continue_execution
                            and stop_reason in {"repeated_tool_rounds", "no_tools_completed", "tool_failed"}
                            and (
                                force_fallback_for_tool_failed
                                or not has_substantive_final_response
                            )
                        )
                        or force_structured_summary_without_fallback_notice
                        or force_fallback_for_stream_error
                        or force_environment_blocked_report
                    )
                    if should_emit_fallback_summary:
                        if (
                            not force_environment_blocked_report
                            and not provider_account_stream_error_seen
                            and not latest_web_search_results
                            and user_request
                        ):
                            direct_results = await self._direct_web_search_fallback_results(
                                query=user_request,
                                max_items=5,
                            )
                            if direct_results:
                                latest_web_search_results = direct_results

                        fallback_screenshot_summary = latest_screenshot_summary
                        if (
                            require_screenshot_stage
                            and
                            not force_environment_blocked_report
                            and not fallback_screenshot_summary
                            and not provider_account_stream_error_seen
                            and (
                                force_fallback_for_low_value_stop
                                or force_fallback_for_stream_error
                                or force_structured_summary_without_fallback_notice
                            )
                        ):
                            fallback_screenshot_summary = await self._direct_screenshot_fallback_summary()
                            if fallback_screenshot_summary:
                                latest_screenshot_summary = fallback_screenshot_summary

                        fallback_text = ""
                        if force_environment_blocked_report:
                            balance_error_message_for_report = (
                                recent_balance_not_enough_error_message
                                or stream_error_message
                                or recent_provider_account_error_message
                                or "BALANCE_NOT_ENOUGH"
                            )
                            fallback_text = build_environment_blocked_report_text(
                                error_message=balance_error_message_for_report,
                                current_model_name=active_model_name,
                            )
                        if (
                            not fallback_text
                            and force_structured_summary_without_fallback_notice
                            and not provider_account_stream_error_seen
                        ):
                            fallback_text = build_web_search_fallback_text(
                                latest_web_search_results,
                                max_items=5,
                                screenshot_summary=fallback_screenshot_summary,
                                include_fallback_notice=False,
                            )
                        elif not fallback_text and not provider_account_stream_error_seen:
                            fallback_text = build_web_search_fallback_text(
                                latest_web_search_results,
                                max_items=5,
                                screenshot_summary=fallback_screenshot_summary,
                            )
                        if (
                            not fallback_text
                            and force_fallback_for_stream_error
                            and not force_environment_blocked_report
                        ):
                            fallback_stream_error_message = (
                                stream_error_message
                                or recent_provider_account_error_message
                                or "unknown stream error"
                            )
                            fallback_text = build_stream_error_fallback_text(
                                error_message=fallback_stream_error_message,
                                current_model_name=active_model_name,
                                retry_count=recoverable_stream_error_retry_count,
                                max_retries=max_recoverable_stream_error_retries,
                            )
                        if not fallback_text and force_fallback_for_tool_failed:
                            failed_tools_text = (
                                ", ".join(sorted(failed_non_terminating_tools))
                                if failed_non_terminating_tools
                                else "unknown_tool"
                            )
                            fallback_text = "\n".join(
                                [
                                    "本轮深度研究在工具执行阶段发生失败，系统已执行自动收敛。",
                                    "",
                                    "一、失败概览",
                                    f"- 失败工具：{failed_tools_text}",
                                    "- 该失败会阻断完整自动化链路，因此本轮提前结束。",
                                    "",
                                    "二、建议下一步",
                                    "1. 先修复失败工具或切换等效工具后重试。",
                                    "2. 重试时保留当前任务清单与已完成检索结果，避免重复工作。",
                                ]
                            )
                        if fallback_text:
                            try:
                                fallback_message_id = str(uuid.uuid4())
                                thread_run_id = getattr(self.config, "agent_run_id", None)
                                fallback_metadata = {
                                    "stream_status": "complete",
                                    "thread_run_id": str(thread_run_id) if thread_run_id is not None else None,
                                    "synthetic": (
                                        "environment_blocked_report"
                                        if force_environment_blocked_report
                                        else (
                                            "structured_research_summary"
                                            if force_structured_summary_without_fallback_notice
                                            else (
                                                "stream_error_fallback_summary"
                                                if force_fallback_for_stream_error
                                                else "web_search_fallback_summary"
                                            )
                                        )
                                    ),
                                }
                                saved_message = await self.thread_manager.add_message(
                                    thread_id=self.config.thread_id,
                                    type="assistant",
                                    content={"role": "assistant", "content": fallback_text},
                                    is_llm_message=True,
                                    metadata=fallback_metadata,
                                    message_id=fallback_message_id,
                                )
                                yield {
                                    "type": "assistant",
                                    "message_id": fallback_message_id,
                                    "thread_id": self.config.thread_id,
                                    "content": json.dumps({"role": "assistant", "content": fallback_text}),
                                    "metadata": json.dumps(fallback_metadata),
                                    "created_at": (
                                        saved_message.get("created_at").isoformat()
                                        if isinstance(saved_message, dict)
                                        and isinstance(saved_message.get("created_at"), datetime.datetime)
                                        else (
                                            str(saved_message.get("created_at"))
                                            if isinstance(saved_message, dict) and saved_message.get("created_at")
                                            else datetime.datetime.now(datetime.timezone.utc).isoformat()
                                        )
                                    ),
                                }
                            except Exception as fallback_error:
                                logger.warning(f"Failed to emit fallback web search summary: {fallback_error}")

                except Exception as e:
                    error_msg = f"Error during response streaming: {str(e)}"
                    if generation:
                        generation.end(output=full_response, status_message=error_msg, level="ERROR")
                    yield {
                        "type": "status",
                        "status": "error", 
                        "message": error_msg
                    }
                    break
                     
            except Exception as e:
                error_msg = f"Error running thread: {str(e)}"
                yield {
                    "type": "status",
                    "status": "error", 
                    "message": error_msg
                }
                break
            
            if generation:
                generation.end(output=full_response)
            if isinstance(full_response, str):
                last_full_response_text = full_response

        if time_budget_exceeded:
            has_substantive_last_response = (
                isinstance(last_full_response_text, str)
                and len(last_full_response_text.strip()) >= 300
                and not is_low_value_no_tool_response(last_full_response_text)
                and is_structured_research_summary_text(last_full_response_text)
            )
            if not has_substantive_last_response:
                if not latest_web_search_results and user_request:
                    direct_results = await self._direct_web_search_fallback_results(
                        query=user_request,
                        max_items=5,
                    )
                    if direct_results:
                        latest_web_search_results = direct_results

                timeout_fallback_text = build_web_search_fallback_text(
                    latest_web_search_results,
                    max_items=5,
                    screenshot_summary=latest_screenshot_summary,
                )
                if not timeout_fallback_text:
                    timeout_fallback_text = "\n".join(
                        [
                            "本轮深度研究达到最大运行时长，系统已执行自动收敛。",
                            "",
                            "一、终止原因",
                            f"- 已达到运行时长上限：{max_agent_run_seconds} 秒",
                            "- 在上限内未产出可直接交付的完整结论。",
                            "",
                            "二、建议下一步",
                            "1. 缩小任务范围并减少任务数量后重试。",
                            "2. 保留当前已有检索证据，优先补齐关键来源的页面级抓取。",
                        ]
                    )

                try:
                    fallback_message_id = str(uuid.uuid4())
                    thread_run_id = getattr(self.config, "agent_run_id", None)
                    fallback_metadata = {
                        "stream_status": "complete",
                        "thread_run_id": str(thread_run_id) if thread_run_id is not None else None,
                        "synthetic": "max_duration_fallback_summary",
                    }
                    saved_message = await self.thread_manager.add_message(
                        thread_id=self.config.thread_id,
                        type="assistant",
                        content={"role": "assistant", "content": timeout_fallback_text},
                        is_llm_message=True,
                        metadata=fallback_metadata,
                        message_id=fallback_message_id,
                    )
                    yield {
                        "type": "assistant",
                        "message_id": fallback_message_id,
                        "thread_id": self.config.thread_id,
                        "content": json.dumps({"role": "assistant", "content": timeout_fallback_text}),
                        "metadata": json.dumps(fallback_metadata),
                        "created_at": (
                            saved_message.get("created_at").isoformat()
                            if isinstance(saved_message, dict)
                            and isinstance(saved_message.get("created_at"), datetime.datetime)
                            else (
                                str(saved_message.get("created_at"))
                                if isinstance(saved_message, dict) and saved_message.get("created_at")
                                else datetime.datetime.now(datetime.timezone.utc).isoformat()
                            )
                        ),
                    }
                except Exception as timeout_fallback_error:
                    logger.warning(f"Failed to emit max-duration fallback summary: {timeout_fallback_error}")

        if iteration_count >= self.config.max_iterations and continue_execution:
            has_substantive_last_response = (
                isinstance(last_full_response_text, str)
                and len(last_full_response_text.strip()) >= 300
                and not is_low_value_no_tool_response(last_full_response_text)
                and is_structured_research_summary_text(last_full_response_text)
            )
            if not has_substantive_last_response:
                if not latest_web_search_results and user_request:
                    direct_results = await self._direct_web_search_fallback_results(
                        query=user_request,
                        max_items=5,
                    )
                    if direct_results:
                        latest_web_search_results = direct_results

                max_iter_fallback_text = build_web_search_fallback_text(
                    latest_web_search_results,
                    max_items=5,
                    screenshot_summary=latest_screenshot_summary,
                )
                if not max_iter_fallback_text:
                    max_iter_fallback_text = "\n".join(
                        [
                            "本轮深度研究达到最大迭代次数，系统已执行自动收敛。",
                            "",
                            "一、终止原因",
                            f"- 已达到迭代上限：{self.config.max_iterations}",
                            "- 末轮未产出可直接交付的完整结论。",
                            "",
                            "二、建议下一步",
                            "1. 缩小任务范围并减少任务数量后重试。",
                            "2. 保留当前已有检索证据，优先补齐关键来源的页面级抓取。",
                        ]
                    )

                try:
                    fallback_message_id = str(uuid.uuid4())
                    thread_run_id = getattr(self.config, "agent_run_id", None)
                    fallback_metadata = {
                        "stream_status": "complete",
                        "thread_run_id": str(thread_run_id) if thread_run_id is not None else None,
                        "synthetic": "max_iteration_fallback_summary",
                    }
                    saved_message = await self.thread_manager.add_message(
                        thread_id=self.config.thread_id,
                        type="assistant",
                        content={"role": "assistant", "content": max_iter_fallback_text},
                        is_llm_message=True,
                        metadata=fallback_metadata,
                        message_id=fallback_message_id,
                    )
                    yield {
                        "type": "assistant",
                        "message_id": fallback_message_id,
                        "thread_id": self.config.thread_id,
                        "content": json.dumps({"role": "assistant", "content": max_iter_fallback_text}),
                        "metadata": json.dumps(fallback_metadata),
                        "created_at": (
                            saved_message.get("created_at").isoformat()
                            if isinstance(saved_message, dict)
                            and isinstance(saved_message.get("created_at"), datetime.datetime)
                            else (
                                str(saved_message.get("created_at"))
                                if isinstance(saved_message, dict) and saved_message.get("created_at")
                                else datetime.datetime.now(datetime.timezone.utc).isoformat()
                            )
                        ),
                    }
                except Exception as max_iter_fallback_error:
                    logger.warning(f"Failed to emit max-iteration fallback summary: {max_iter_fallback_error}")

        asyncio.create_task(asyncio.to_thread(lambda: langfuse.flush()))
        #         if isinstance(response, dict) and "status" in response and response["status"] == "error":
        #             yield response
        #             break

        #         last_tool_call = None
        #         agent_should_terminate = False
        #         error_detected = False
        #         full_response = ""
        #         final_response_text = None  # ✅ 用于存储is_final_response的内容
        #         adk_call_completed = False  # ✅ 标记单次ADK调用是否完成

        #         try:
        #             all_chunk = []
        #             if hasattr(response, '__aiter__') and not isinstance(response, dict):
        #                 async for chunk in response:
        #                     print(f"current chunk: {chunk}")
        #                     # ✅ 基于实际事件格式的处理逻辑
        #                     if isinstance(chunk, dict):
        #                         chunk_type = chunk.get('type')
        #                         chunk_content = chunk.get('content', '{}')
        #                         chunk_metadata = chunk.get('metadata', '{}')
                                
        #                         # 解析JSON字符串
        #                         try:
        #                             if isinstance(chunk_content, str):
        #                                 content_data = json.loads(chunk_content)
        #                             else:
        #                                 content_data = chunk_content
                                        
        #                             if isinstance(chunk_metadata, str):
        #                                 metadata_data = json.loads(chunk_metadata)
        #                             else:
        #                                 metadata_data = chunk_metadata
        #                         except json.JSONDecodeError:
        #                             content_data = {}
        #                             metadata_data = {}
                                
        #                         # ✅ 检查assistant消息的完成状态
        #                         if chunk_type == 'assistant' and metadata_data.get('stream_status') == 'complete':
        #                             if content_data.get('content'):
        #                                 final_response_text = content_data['content']
        #                                 logger.info(f"🎯 检测到完整assistant回复: {final_response_text[:100]}...")
                                
        #                         # ✅ 检查finish状态（类似is_final_response）
        #                         elif chunk_type == 'status' and content_data.get('status_type') == 'finish':
        #                             if content_data.get('finish_reason') == 'final':
        #                                 logger.info(f"🏁 检测到final finish状态")
        #                                 # 这表示当前回合的最终响应
                                
        #                         # ✅ 检查thread_run_end（调用完全结束）
        #                         elif chunk_type == 'status' and content_data.get('status_type') == 'thread_run_end':
        #                             logger.info(f"🎯 检测到thread_run_end，ADK调用完全结束")
        #                             adk_call_completed = True
                                
        #                         # ✅ 检查错误状态
        #                         elif chunk_type == 'status' and chunk.get('status') == 'error':
        #                             error_detected = True
        #                             yield chunk
        #                             continue
                        
        #                         # ✅ 检查工具调用和终止条件 (如果还有其他逻辑需要)
        #                         if chunk_type == 'assistant':
        #                             # 🔧 从ADK格式中正确提取文本
        #                             assistant_text = ""
        #                             if content_data.get('content'):
        #                                 # 旧格式：{"content": "text"}
        #                                 assistant_text = str(content_data['content'])
        #                             elif content_data.get('parts'):
        #                                 # ADK格式：{"role": "model", "parts": [{"text": "..."}]}
        #                                 for part in content_data['parts']:
        #                                     if isinstance(part, dict) and 'text' in part:
        #                                         # 🔧 修复：安全处理part['text']，防止list类型导致拼接错误
        #                                         part_text = part['text']
        #                                         if isinstance(part_text, list):
        #                                             part_text = ''.join(str(item) for item in part_text)
        #                                         elif not isinstance(part_text, str):
        #                                             part_text = str(part_text)
        #                                         assistant_text += part_text
                                    
        #                             if assistant_text:
        #                                 # 🔧 修复：确保full_response拼接的类型安全
        #                                 if not isinstance(full_response, str):
        #                                     full_response = str(full_response)
        #                                 if not isinstance(assistant_text, str):
        #                                     assistant_text = str(assistant_text)
        #                                 full_response += assistant_text
                                    
        #                             # 检查XML工具调用
        #                             if isinstance(assistant_text, str):
        #                                 if '</ask>' in assistant_text:
        #                                     last_tool_call = 'ask'
        #                                     agent_should_terminate = True
        #                                 elif '</complete>' in assistant_text:
        #                                     last_tool_call = 'complete' 
        #                                     agent_should_terminate = True
        #                                 elif '</web-browser-takeover>' in assistant_text:
        #                                     last_tool_call = 'web-browser-takeover'
        #                                     agent_should_terminate = True

        #                     yield chunk
                        
        #                 # ✅ 当async for循环结束时，说明事件流耗尽
        #                 if not adk_call_completed:
        #                     adk_call_completed = True
        #                     logger.info(f"🏁 ADK事件流耗尽，单次调用完成")

                      
        #             else:
        #                 error_detected = True
        #             logger.info(f"123all_chunk: {all_chunk}")    
        #         except Exception as stream_error:
        #             error_msg = f"Error during response streaming: {str(stream_error)}"
        #             logger.error(error_msg)
        #             if generation:
        #                 generation.end(output=full_response, status_message=error_msg, level="ERROR")
        #             yield {
        #                 "type": "status",
        #                 "status": "error",
        #                 "message": error_msg
        #             }
        #             break
                    
        #     except Exception as run_error:
        #         error_msg = f"Error running thread: {str(run_error)}"
        #         logger.error(error_msg)
        #         yield {
        #             "type": "status",
        #             "status": "error",
        #             "message": error_msg
        #         }
        #         break
            
        #     # ✅ 外层循环终止判断（基于实际事件）
        #     if error_detected:
        #         logger.info(f"🚨 检测到错误，终止执行")
        #         if generation:
        #             generation.end(output=full_response, status_message="error_detected", level="ERROR")
        #         break
                
        #     # ✅ 基于实际ADK事件的终止判断
        #     if agent_should_terminate or last_tool_call in ['ask', 'complete', 'web-browser-takeover']:
        #         logger.info(f"🛑 Agent明确终止: agent_should_terminate={agent_should_terminate}, last_tool_call={last_tool_call}")
        #         if generation:
        #             generation.end(output=full_response, status_message="agent_stopped")
        #         continue_execution = False
        #         logger.info(f"🛑 设置continue_execution=False，应该退出循环")
                
        #     elif adk_call_completed:
        #         # ✅ ADK调用完成后，继续下一次迭代让Agent执行更多任务
        #         logger.info(f"✅ ADK调用完成，继续执行更多任务 (iteration {iteration_count}/{self.config.max_iterations})")
        #         if final_response_text:
        #             logger.info(f"📝 本轮响应预览: {final_response_text[:200]}...")
        #         # continue_execution保持True，让Agent继续执行任务
                
        #     else:
        #         # ✅ 其他情况
        #         logger.info(f"❓ 未明确的ADK状态 (completed={adk_call_completed}, final_text={bool(final_response_text)})，继续尝试")
            
        #     if generation:
        #         generation.end(output=full_response)

        # # 🔍 循环结束日志
        # logger.info(f"🏁 Agent执行循环结束: continue_execution={continue_execution}, iteration_count={iteration_count}")
        # logger.info(f"🏁 最终状态: max_iterations={self.config.max_iterations}")
        # #                     # ✅ 官方推荐：用is_final_response()获取最终可展示文本
        # #                     if hasattr(chunk, 'is_final_response') and chunk.is_final_response():
        # #                         if hasattr(chunk, 'content') and chunk.content and hasattr(chunk.content, 'parts') and chunk.content.parts:
        # #                             final_response_text = chunk.content.parts[0].text
        # #                             logger.info(f"🎯 检测到final_response: {final_response_text[:100]}...")
                            
        # #                     if isinstance(chunk, dict) and chunk.get('type') == 'status' and chunk.get('status') == 'error':
        # #                         error_detected = True
        # #                         yield chunk
        # #                         continue
                            
        # #                     if chunk.get('type') == 'status':
        # #                         try:
        # #                             metadata = chunk.get('metadata', {})
        # #                             if isinstance(metadata, str):
        # #                                 metadata = json.loads(metadata)
                                    
        # #                             if metadata.get('agent_should_terminate'):
        # #                                 agent_should_terminate = True
                                        
        # #                                 content = chunk.get('content', {})
        # #                                 if isinstance(content, str):
        # #                                     content = json.loads(content)
                                        
        # #                                 if content.get('function_name'):
        # #                                     last_tool_call = content['function_name']
        # #                                 elif content.get('xml_tag_name'):
        # #                                     last_tool_call = content['xml_tag_name']
                                            
        # #                         except Exception:
        # #                             pass
                            
        # #                     if chunk.get('type') == 'assistant' and 'content' in chunk:
        # #                         try:
        # #                             content = chunk.get('content', '{}')
        # #                             if isinstance(content, str):
        # #                                 assistant_content_json = json.loads(content)
        # #                             else:
        # #                                 assistant_content_json = content

        # #                             assistant_text = assistant_content_json.get('content', '')
        # #                             full_response += assistant_text
        # #                             if isinstance(assistant_text, str):
        # #                                 if '</ask>' in assistant_text or '</complete>' in assistant_text or '</web-browser-takeover>' in assistant_text:
        # #                                    if '</ask>' in assistant_text:
        # #                                        xml_tool = 'ask'
        # #                                    elif '</complete>' in assistant_text:
        # #                                        xml_tool = 'complete'
        # #                                    elif '</web-browser-takeover>' in assistant_text:
        # #                                        xml_tool = 'web-browser-takeover'

        # #                                    last_tool_call = xml_tool
                                
        # #                         except json.JSONDecodeError:
        # #                             pass
        # #                         except Exception:
        # #                             pass

        # #                     yield chunk
                        
        # #                 # ✅ 当async for循环结束时，说明这次ADK调用的事件流已耗尽
        # #                 adk_call_completed = True
        # #                 logger.info(f"🏁 ADK事件流耗尽，单次调用完成")
                        
        # #             else:
        # #                 error_detected = True

        # #             if error_detected:
        # #                 logger.info(f"🚨 检测到错误，终止执行")
        # #                 if generation:
        # #                     generation.end(output=full_response, status_message="error_detected", level="ERROR")
        # #                 break
                        
        # #             # ✅ 基于官方建议的外层循环终止判断
        # #             if agent_should_terminate or last_tool_call in ['ask', 'complete', 'web-browser-takeover']:
        # #                 logger.info(f"🛑 Agent明确终止: agent_should_terminate={agent_should_terminate}, last_tool_call={last_tool_call}")
        # #                 if generation:
        # #                     generation.end(output=full_response, status_message="agent_stopped")
        # #                 continue_execution = False
        # #                 logger.info(f"🛑 设置continue_execution=False，应该退出循环")
        # #             elif adk_call_completed and final_response_text:
        # #                 # ✅ ADK调用完成且有最终响应文本，通常表示一轮完整对话结束
        # #                 logger.info(f"✅ ADK调用完成且有最终响应，默认终止外层循环")
        # #                 logger.info(f"📝 最终响应预览: {final_response_text[:200]}...")
        # #                 continue_execution = False
        # #             elif adk_call_completed and not final_response_text:
        # #                 # ✅ ADK调用完成但没有最终响应文本，可能需要继续
        # #                 logger.info(f"⚠️ ADK调用完成但无最终响应文本，继续下一次迭代")
        # #                 # continue_execution保持True，继续下一次迭代
        # #             else:
        # #                 # ✅ 其他情况，可能是ADK内部错误或异常状态
        # #                 logger.info(f"❓ 未明确的ADK状态 (completed={adk_call_completed}, final_text={bool(final_response_text)})，继续尝试")

        # #         except Exception as e:
        # #             error_msg = f"Error during response streaming: {str(e)}"
        # #             if generation:
        # #                 generation.end(output=full_response, status_message=error_msg, level="ERROR")
        # #             yield {
        # #                 "type": "status",
        # #                 "status": "error",
        # #                 "message": error_msg
        # #             }
        # #             break
                    
        # #     except Exception as e:
        # #         error_msg = f"Error running thread: {str(e)}"
        # #         yield {
        # #             "type": "status",
        # #             "status": "error",
        # #             "message": error_msg
        # #         }
        # #         break
            
        # #     if generation:
        # #         generation.end(output=full_response)

        # # # 🔍 循环结束日志
        # # logger.info(f"🏁 Agent执行循环结束: continue_execution={continue_execution}, iteration_count={iteration_count}")
        # # logger.info(f"🏁 最终状态: max_iterations={self.config.max_iterations}")

        # asyncio.create_task(asyncio.to_thread(lambda: langfuse.flush()))

    def _convert_adk_event_to_format(self, adk_event) -> Optional[Dict[str, Any]]:
        """将ADK事件转换为你的格式"""
        try:
            if adk_event.type == "assistant_response_start":
                return {
                    "type": "status",
                    "content": {"status_type": "assistant_response_start"},
                    "metadata": {"thread_run_id": self.config.agent_run_id}
                }
            
            elif adk_event.type == "assistant_response":
                # 处理助手响应
                content = adk_event.content
                if content and hasattr(content, 'parts'):
                    text_content = ""
                    for part in content.parts:
                        if hasattr(part, 'text'):
                            # 🔧 确保类型安全，防止字符串拼接错误
                            part_text = part.text
                            if isinstance(part_text, list):
                                part_text = ''.join(str(item) for item in part_text)
                            elif not isinstance(part_text, str):
                                part_text = str(part_text)
                            text_content += part_text
                    
                    return {
                        "type": "assistant",
                        "content": {"role": "assistant", "content": text_content},
                        "metadata": {"stream_status": "chunk", "thread_run_id": self.config.agent_run_id}
                    }
            
            elif adk_event.type == "tool_started":
                # 处理工具调用
                return {
                    "type": "status",
                    "content": {
                        "role": "assistant",
                        "status_type": "tool_started",
                        "tool_name": adk_event.tool_name,
                        "tool_args": adk_event.tool_args
                    },
                    "metadata": {"thread_run_id": self.config.agent_run_id}
                }
            
            elif adk_event.type == "tool_result":
                # 处理工具结果
                return {
                    "type": "tool",
                    "content": {
                        "role": "tool",
                        "tool_name": adk_event.tool_name,
                        "result": adk_event.result
                    },
                    "metadata": {"thread_run_id": self.config.agent_run_id}
                }
            
            elif adk_event.type == "assistant_response_end":
                # 处理响应结束
                return {
                    "type": "status",
                    "content": {"status_type": "assistant_response_end"},
                    "metadata": {"thread_run_id": self.config.agent_run_id}
                }
            
            return None
            
        except Exception as convert_error:
            print(f"  ⚠️ 事件转换失败: {convert_error}")
            return None

from agentpress.adk_thread_manager import ADKThreadManager
from typing import  Union

async def run_agent(
    thread_id: str,
    project_id: str,
    stream: bool,
    thread_manager: Optional[Union[ThreadManager, ADKThreadManager]] = None,  
    native_max_auto_continues: int = 0,
    max_iterations: int = 100,
    model_name: str = "deepseek-v3.2",
    enable_thinking: Optional[bool] = False,
    reasoning_effort: Optional[str] = 'low',
    enable_context_manager: bool = True,
    agent_config: Optional[dict] = None,    
    trace: Optional[StatefulTraceClient] = None, # type: ignore
    is_agent_builder: Optional[bool] = False,
    target_agent_id: Optional[str] = None,
):
    # max_iterations - 外层循环（Agent级别）：每次迭代 = 一轮完整的"思考 → 调用工具 → 处理结果"，用于防止 Agent 陷入无限循环
    # native_max_auto_continues - 内层循环（LLM级别）：当 LLM 返回 finish_reason='length'（未完成）或其他原因导致的意外终止时，自动继续生成
    config = AgentConfig(
        thread_id=thread_id,
        project_id=project_id,
        stream=stream,
        native_max_auto_continues=native_max_auto_continues, # 控制 AI Agent 自动继续对话的最大次数
        max_iterations=max_iterations, # Agent 最大迭代次数
        model_name=model_name,
        enable_thinking=enable_thinking,  # 是否启用思考
        reasoning_effort=reasoning_effort,  # 思考力度
        enable_context_manager=enable_context_manager,
        agent_config=agent_config,  # Agent 配置
        trace=trace,
        is_agent_builder=is_agent_builder,  # 是否是 Agent 构建器（）
        target_agent_id=target_agent_id,  # 目标 Agent ID
    )

    # 创建 Runner 
    runner = AgentRunner(config)
    logger.info(f"AgentRunner created successfully: {runner}")
    
    try:
        logger.info(f"Starting to run runner.run()")
        async for chunk in runner.run():
            yield chunk
    except Exception as run_error:
        logger.error(f"runner.run() failed: {run_error}")
        logger.error(f"Error details: {traceback.format_exc()}")
        raise run_error
