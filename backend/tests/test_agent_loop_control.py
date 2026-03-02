from agent.run import (
    advance_required_research_chain_state,
    apply_deep_research_focus_gating,
    apply_high_frequency_tool_gating,
    apply_cumulative_tool_budget_gating,
    apply_failed_tool_budget_gating,
    apply_required_research_chain_gating,
    apply_task_list_tool_gating,
    build_stream_error_fallback_text,
    build_repeated_tool_recovery_hint,
    build_web_search_fallback_text,
    choose_recoverable_stream_fallback_model,
    decide_agent_iteration_continuation,
    is_low_value_no_tool_response,
    is_structured_research_summary_text,
    mark_required_research_chain_progress,
    is_provider_account_stream_error_message,
    is_recoverable_stream_error_message,
    merge_temporary_message_with_hint,
    should_force_tool_failed_fallback,
    should_force_structured_summary_without_fallback_notice,
    should_retry_after_blocked_tool_call,
    choose_direct_required_stage_compensation,
    should_force_direct_chain_convergence,
    is_balance_not_enough_error_message,
    build_environment_blocked_report_text,
    should_require_task_list_bootstrap,
    should_allow_path_cleanup_tools,
    should_allow_task_deletion_tools,
    should_allow_task_replan,
    should_require_scrape_stage,
    should_require_screenshot_stage,
    is_tool_blocked_by_current_run,
    choose_tool_execution_strategy,
    choose_max_xml_tool_calls_per_iteration,
)


def test_continue_after_first_non_terminating_tool_completion():
    should_continue, signature, streak, reason = decide_agent_iteration_continuation(
        agent_should_terminate=False,
        last_tool_call=None,
        terminating_tool_names={"ask", "complete", "web-browser-takeover"},
        completed_non_terminating_tools={"web_search"},
        failed_non_terminating_tools=set(),
        previous_completed_signature=None,
        repeated_signature_streak=0,
        max_repeated_tool_rounds=4,
    )

    assert should_continue is True
    assert signature == ("web_search",)
    assert streak == 1
    assert reason is None


def test_stop_when_same_tool_signature_repeats_too_many_rounds():
    signature = None
    streak = 0
    should_continue = True
    reason = None

    for _ in range(3):
        should_continue, signature, streak, reason = decide_agent_iteration_continuation(
            agent_should_terminate=False,
            last_tool_call=None,
            terminating_tool_names={"ask", "complete", "web-browser-takeover"},
            completed_non_terminating_tools={"web_search"},
            failed_non_terminating_tools=set(),
            previous_completed_signature=signature,
            repeated_signature_streak=streak,
            max_repeated_tool_rounds=3,
        )

    assert should_continue is False
    assert signature == ("web_search",)
    assert streak == 3
    assert reason == "repeated_tool_rounds"


def test_reset_repeat_streak_when_tool_signature_changes():
    should_continue, signature, streak, reason = decide_agent_iteration_continuation(
        agent_should_terminate=False,
        last_tool_call=None,
        terminating_tool_names={"ask", "complete", "web-browser-takeover"},
        completed_non_terminating_tools={"web_search"},
        failed_non_terminating_tools=set(),
        previous_completed_signature=("web_search",),
        repeated_signature_streak=2,
        max_repeated_tool_rounds=3,
    )

    assert should_continue is False
    assert reason == "repeated_tool_rounds"

    should_continue, signature, streak, reason = decide_agent_iteration_continuation(
        agent_should_terminate=False,
        last_tool_call=None,
        terminating_tool_names={"ask", "complete", "web-browser-takeover"},
        completed_non_terminating_tools={"scrape_webpage"},
        failed_non_terminating_tools=set(),
        previous_completed_signature=signature,
        repeated_signature_streak=streak,
        max_repeated_tool_rounds=3,
    )

    assert should_continue is True
    assert signature == ("scrape_webpage",)
    assert streak == 1
    assert reason is None


def test_allow_additional_retries_for_repeated_create_tasks_before_stopping():
    signature = None
    streak = 0
    should_continue = True
    reason = None

    for _ in range(2):
        should_continue, signature, streak, reason = decide_agent_iteration_continuation(
            agent_should_terminate=False,
            last_tool_call=None,
            terminating_tool_names={"ask", "complete", "web-browser-takeover"},
            completed_non_terminating_tools={"create_tasks"},
            failed_non_terminating_tools=set(),
            previous_completed_signature=signature,
            repeated_signature_streak=streak,
            max_repeated_tool_rounds=5,
        )
        assert should_continue is True
        assert reason is None

    should_continue, signature, streak, reason = decide_agent_iteration_continuation(
        agent_should_terminate=False,
        last_tool_call=None,
        terminating_tool_names={"ask", "complete", "web-browser-takeover"},
        completed_non_terminating_tools={"create_tasks"},
        failed_non_terminating_tools=set(),
        previous_completed_signature=signature,
        repeated_signature_streak=streak,
        max_repeated_tool_rounds=5,
    )

    assert should_continue is False
    assert signature == ("create_tasks",)
    assert streak == 3
    assert reason == "repeated_tool_rounds"


def test_continue_when_only_recoverable_tool_fails_without_completed_tools():
    should_continue, signature, streak, reason = decide_agent_iteration_continuation(
        agent_should_terminate=False,
        last_tool_call=None,
        terminating_tool_names={"ask", "complete", "web-browser-takeover"},
        completed_non_terminating_tools=set(),
        failed_non_terminating_tools={"browser_navigate_to"},
        previous_completed_signature=None,
        repeated_signature_streak=0,
        max_repeated_tool_rounds=5,
        recoverable_non_terminating_tools={"browser_navigate_to"},
    )

    assert should_continue is True
    assert signature == ("failed:browser_navigate_to",)
    assert streak == 1
    assert reason == "recoverable_tool_failed"


def test_stop_when_unrecoverable_tool_fails():
    should_continue, signature, streak, reason = decide_agent_iteration_continuation(
        agent_should_terminate=False,
        last_tool_call=None,
        terminating_tool_names={"ask", "complete", "web-browser-takeover"},
        completed_non_terminating_tools=set(),
        failed_non_terminating_tools={"unknown_tool"},
        previous_completed_signature=None,
        repeated_signature_streak=0,
        max_repeated_tool_rounds=5,
        recoverable_non_terminating_tools={"browser_navigate_to"},
    )

    assert should_continue is False
    assert signature is None
    assert streak == 0
    assert reason == "tool_failed"


def test_stop_for_alternating_task_planning_loop_signatures():
    signature = None
    streak = 0
    should_continue = True
    reason = None

    for completed in ({"create_tasks"}, {"view_tasks"}, {"create_tasks"}):
        should_continue, signature, streak, reason = decide_agent_iteration_continuation(
            agent_should_terminate=False,
            last_tool_call=None,
            terminating_tool_names={"ask", "complete", "web-browser-takeover"},
            completed_non_terminating_tools=completed,
            failed_non_terminating_tools=set(),
            previous_completed_signature=signature,
            repeated_signature_streak=streak,
            max_repeated_tool_rounds=5,
        )

    assert should_continue is False
    assert signature == ("create_tasks",)
    assert streak == 3
    assert reason == "repeated_tool_rounds"


def test_allow_more_repeated_screenshot_rounds_before_stopping():
    signature = None
    streak = 0
    should_continue = True
    reason = None

    for _ in range(5):
        should_continue, signature, streak, reason = decide_agent_iteration_continuation(
            agent_should_terminate=False,
            last_tool_call=None,
            terminating_tool_names={"ask", "complete", "web-browser-takeover"},
            completed_non_terminating_tools={"screenshot"},
            failed_non_terminating_tools=set(),
            previous_completed_signature=signature,
            repeated_signature_streak=streak,
            max_repeated_tool_rounds=5,
        )
        assert should_continue is True
        assert reason is None

    should_continue, signature, streak, reason = decide_agent_iteration_continuation(
        agent_should_terminate=False,
        last_tool_call=None,
        terminating_tool_names={"ask", "complete", "web-browser-takeover"},
        completed_non_terminating_tools={"screenshot"},
        failed_non_terminating_tools=set(),
        previous_completed_signature=signature,
        repeated_signature_streak=streak,
        max_repeated_tool_rounds=5,
    )

    assert should_continue is False
    assert signature == ("screenshot",)
    assert streak == 6
    assert reason == "repeated_tool_rounds"


def test_build_repeated_tool_recovery_hint_for_create_tasks():
    hint = build_repeated_tool_recovery_hint(("create_tasks",))

    assert hint is not None
    assert "view_tasks" in hint
    assert "create_tasks" in hint


def test_build_repeated_tool_recovery_hint_for_screenshot():
    hint = build_repeated_tool_recovery_hint(("screenshot",))

    assert hint is not None
    assert "screenshot" in hint
    assert "final summary" in hint


def test_build_repeated_tool_recovery_hint_for_unrelated_signature_returns_none():
    assert build_repeated_tool_recovery_hint(("scrape_webpage",)) is None


def test_build_repeated_tool_recovery_hint_for_update_tasks():
    hint = build_repeated_tool_recovery_hint(("update_tasks",))

    assert hint is not None
    assert "update_tasks" in hint
    assert "view_tasks" in hint


def test_build_repeated_tool_recovery_hint_for_failed_tools_signature():
    hint = build_repeated_tool_recovery_hint(("failed:browser_navigate_to",))

    assert hint is not None
    assert "failed" in hint.lower()
    assert "browser_navigate_to" in hint


def test_merge_temporary_message_with_hint_creates_message_when_missing():
    merged = merge_temporary_message_with_hint(None, "Use view_tasks first.")

    assert merged is not None
    assert merged["role"] == "user"
    assert isinstance(merged["content"], list)
    assert merged["content"][-1]["type"] == "text"
    assert "Use view_tasks first." in merged["content"][-1]["text"]


def test_merge_temporary_message_with_hint_appends_to_existing_message():
    temporary_message = {
        "role": "user",
        "content": [
            {"type": "text", "text": "Existing context."},
        ],
    }

    merged = merge_temporary_message_with_hint(temporary_message, "New corrective hint.")

    assert merged is not None
    assert len(merged["content"]) == 2
    assert merged["content"][-1]["type"] == "text"
    assert "New corrective hint." in merged["content"][-1]["text"]


def test_build_web_search_fallback_text_returns_numbered_sources():
    text = build_web_search_fallback_text(
        [
            {"title": "Source A", "url": "https://a.example.com"},
            {"title": "Source B", "url": "https://b.example.com"},
        ],
        max_items=5,
    )

    assert "1. Source A - https://a.example.com" in text
    assert "2. Source B - https://b.example.com" in text


def test_build_web_search_fallback_text_contains_structured_sections():
    text = build_web_search_fallback_text(
        [
            {"title": "US market outlook", "url": "https://a.example.com"},
            {"title": "CN market outlook", "url": "https://b.example.com"},
        ],
        max_items=5,
    )

    assert "一、结论" in text
    assert "二、关键证据" in text
    assert "三、工具执行记录" in text
    assert "五、风险与不确定性" in text
    assert "六、下一步建议" in text


def test_build_web_search_fallback_text_without_notice_for_structured_summary_mode():
    text = build_web_search_fallback_text(
        [
            {"title": "US market outlook", "url": "https://a.example.com"},
        ],
        max_items=5,
        include_fallback_notice=False,
    )

    assert "已触发自动兜底收敛流程" not in text
    assert "基于当前已收集证据的结构化总结如下" in text


def test_build_web_search_fallback_text_does_not_include_screenshot_observation_by_default():
    text = build_web_search_fallback_text(
        [
            {"title": "US market outlook", "url": "https://a.example.com"},
        ],
        max_items=5,
        screenshot_summary={
            "url": "http://localhost:8000/api/screenshots/s1.png",
            "width": 1024,
            "height": 768,
            "timestamp": "2026-03-01T00:00:00Z",
        },
    )

    assert "computer-use/sandbox screenshot" not in text
    assert "http://localhost:8000/api/screenshots/s1.png" not in text
    assert "1024x768" not in text


def test_build_web_search_fallback_text_includes_screenshot_observation_when_enabled():
    text = build_web_search_fallback_text(
        [
            {"title": "US market outlook", "url": "https://a.example.com"},
        ],
        max_items=5,
        screenshot_summary={
            "url": "http://localhost:8000/api/screenshots/s1.png",
            "width": 1024,
            "height": 768,
            "timestamp": "2026-03-01T00:00:00Z",
        },
        include_screenshot_observation=True,
    )

    assert "computer-use/sandbox screenshot" in text
    assert "http://localhost:8000/api/screenshots/s1.png" in text
    assert "1024x768" in text


def test_build_web_search_fallback_text_empty_when_no_results():
    assert build_web_search_fallback_text([], max_items=5) == ""


def test_build_web_search_fallback_text_skips_screenshot_line_when_missing():
    text = build_web_search_fallback_text(
        [
            {"title": "US market outlook", "url": "https://a.example.com"},
        ],
        max_items=5,
    )

    assert "computer-use/sandbox screenshot" not in text


def test_should_require_scrape_stage_only_when_explicitly_requested():
    assert should_require_scrape_stage("请做深度搜索并给出结论") is False
    assert should_require_scrape_stage("请抓取目标网页并提取正文") is True


def test_should_require_screenshot_stage_only_when_explicitly_requested():
    assert should_require_screenshot_stage("请做深度搜索并总结") is False
    assert should_require_screenshot_stage("请附上截图证据") is True


def test_is_recoverable_stream_error_message_for_connection_markers():
    assert is_recoverable_stream_error_message(
        "litellm.APIConnectionError: Ollama_chatException - Server disconnected"
    ) is True
    assert is_recoverable_stream_error_message("connection timed out while streaming") is True


def test_is_recoverable_stream_error_message_ignores_non_connection_errors():
    assert is_recoverable_stream_error_message("Function create_tasks is not found in tools_dict") is False
    assert is_recoverable_stream_error_message("invalid request payload") is False


def test_is_provider_account_stream_error_message_for_billing_markers():
    assert is_provider_account_stream_error_message(
        "Model provider rejected request: overdue-payment"
    ) is True
    assert is_provider_account_stream_error_message(
        "OpenAIException - Access denied by model-studio/error-code"
    ) is True
    assert is_provider_account_stream_error_message("connection timed out while streaming") is False


def test_is_low_value_no_tool_response_detects_generic_greeting():
    assert is_low_value_no_tool_response(
        "Hello! I'm AlexManus, an autonomous AI Worker. I'm here to help you with many tasks."
    ) is True
    assert is_low_value_no_tool_response("How can I assist you today?") is True
    assert is_low_value_no_tool_response(
        "I understand you want me to continue processing. However, looking at the tools available, I only have access to browser tools."
    ) is True
    assert is_low_value_no_tool_response(
        "I understand you want me to create a structured approach before execution."
    ) is True
    assert is_low_value_no_tool_response(
        "当前的工具集中没有screenshot工具，无法完成这个具体请求。"
    ) is True
    assert is_low_value_no_tool_response(
        "我理解您的意思。您是指让我继续处理之前的请求，但并没有\"screenshot\"这个工具。"
    ) is True
    assert is_low_value_no_tool_response(
        "I will continue processing the previous request, but I don't have the browser_navigate_to tool."
    ) is True
    assert is_low_value_no_tool_response(
        "Based on our conversation history, I haven't created a task list yet. Let me restart the whole flow."
    ) is True
    assert is_low_value_no_tool_response(
        "基于我们的对话历史，我还没有创建任务列表。让我重新开始整个流程。"
    ) is True


def test_is_low_value_no_tool_response_allows_substantive_report_text():
    substantive = (
        "一、结论：2026年全球AI Agent市场预计保持高速增长。"
        "二、关键证据：基于多来源对比，企业级部署和垂直场景将成为主要增长驱动。"
        "三、风险：不同来源统计口径差异较大，需要二次校验。"
    )
    assert is_low_value_no_tool_response(substantive) is False


def test_is_low_value_no_tool_response_allows_output_with_url_even_if_prefix_matches():
    response_text = (
        "我理解您的意思。您是指让我继续处理之前的请求。"
        "截图链接：https://example.com/screenshot.png。"
        "状态说明：截图已成功生成。"
    )
    assert is_low_value_no_tool_response(response_text) is False


def test_is_structured_research_summary_text_detects_structured_sections():
    text = (
        "一、结论：市场持续增长。\n"
        "二、关键证据：来自多来源交叉验证。\n"
        "四、参考来源：来源A、来源B。\n"
        "五、风险：统计口径存在差异。\n"
        "六、下一步建议：继续补充官方数据。"
    )
    assert is_structured_research_summary_text(text) is True


def test_is_structured_research_summary_text_rejects_long_unstructured_chatter():
    text = (
        "我现在需要继续处理之前的请求。让我先创建任务列表，然后再继续。"
        * 12
    )
    assert is_structured_research_summary_text(text) is False


def test_should_force_structured_summary_without_fallback_notice_for_tool_failed():
    assert should_force_structured_summary_without_fallback_notice(
        stop_reason="tool_failed",
        low_value_final_response=True,
        has_evidence=True,
    ) is True


def test_should_force_structured_summary_without_fallback_notice_for_repeated_rounds():
    assert should_force_structured_summary_without_fallback_notice(
        stop_reason="repeated_tool_rounds",
        low_value_final_response=True,
        has_evidence=True,
    ) is True


def test_should_not_force_structured_summary_without_fallback_notice_without_evidence():
    assert should_force_structured_summary_without_fallback_notice(
        stop_reason="tool_failed",
        low_value_final_response=True,
        has_evidence=False,
    ) is False


def test_is_tool_blocked_by_current_run_detects_allowlist_error_text():
    assert is_tool_blocked_by_current_run("Tool function 'create_tasks' is not available in current run") is True
    assert is_tool_blocked_by_current_run(
        {"error": "Tool function 'web_search' is not available in current run"}
    ) is True
    assert is_tool_blocked_by_current_run("Failed to move mouse: timeout") is False


def test_should_retry_after_blocked_tool_call_for_single_recovery_attempt():
    assert should_retry_after_blocked_tool_call(
        stop_reason="tool_failed",
        blocked_non_terminating_tools={"create_tasks"},
        completed_non_terminating_tools=set(),
        blocked_retry_count=0,
        max_blocked_retries=1,
    ) is True

    assert should_retry_after_blocked_tool_call(
        stop_reason="tool_failed",
        blocked_non_terminating_tools={"create_tasks"},
        completed_non_terminating_tools=set(),
        blocked_retry_count=1,
        max_blocked_retries=1,
    ) is False


def test_should_not_retry_after_blocked_tool_call_when_completed_tools_exist():
    assert should_retry_after_blocked_tool_call(
        stop_reason="tool_failed",
        blocked_non_terminating_tools={"create_tasks"},
        completed_non_terminating_tools={"view_tasks"},
        blocked_retry_count=0,
        max_blocked_retries=1,
    ) is False


def test_choose_direct_required_stage_compensation_for_web_search_stage():
    assert (
        choose_direct_required_stage_compensation(
            stop_reason="tool_failed",
            required_chain_stage_index=2,
            required_chain_progress={"has_web_search": False, "has_updated_tasks": False},
            blocked_non_terminating_tools={"create_tasks"},
        )
        == "web_search"
    )


def test_choose_direct_required_stage_compensation_for_create_tasks_stage():
    assert (
        choose_direct_required_stage_compensation(
            stop_reason="no_tools_completed",
            required_chain_stage_index=0,
            required_chain_progress={"has_created_tasks": False, "has_viewed_tasks": False},
            blocked_non_terminating_tools=set(),
        )
        == "create_tasks"
    )


def test_choose_direct_required_stage_compensation_for_view_tasks_stage():
    assert (
        choose_direct_required_stage_compensation(
            stop_reason="tool_failed",
            required_chain_stage_index=1,
            required_chain_progress={"has_created_tasks": True, "has_viewed_tasks": False},
            blocked_non_terminating_tools={"create_tasks"},
        )
        == "view_tasks"
    )


def test_choose_direct_required_stage_compensation_for_update_tasks_stage():
    assert (
        choose_direct_required_stage_compensation(
            stop_reason="no_tools_completed",
            required_chain_stage_index=5,
            required_chain_progress={"has_web_search": True, "has_updated_tasks": False},
            blocked_non_terminating_tools=set(),
        )
        == "update_tasks"
    )


def test_choose_direct_required_stage_compensation_for_recoverable_blocked_stage():
    assert (
        choose_direct_required_stage_compensation(
            stop_reason="recoverable_tool_failed",
            required_chain_stage_index=2,
            required_chain_progress={"has_web_search": False, "has_updated_tasks": False},
            blocked_non_terminating_tools={"create_tasks"},
        )
        == "web_search"
    )


def test_choose_direct_required_stage_compensation_for_terminated_stage():
    assert (
        choose_direct_required_stage_compensation(
            stop_reason="terminated",
            required_chain_stage_index=2,
            required_chain_progress={"has_web_search": False, "has_updated_tasks": False},
            blocked_non_terminating_tools=set(),
        )
        == "web_search"
    )


def test_choose_direct_required_stage_compensation_returns_none_for_other_stages():
    assert (
        choose_direct_required_stage_compensation(
            stop_reason="tool_failed",
            required_chain_stage_index=3,
            required_chain_progress={"has_web_search": False, "has_updated_tasks": False},
            blocked_non_terminating_tools={"create_tasks"},
        )
        is None
    )


def test_should_force_direct_chain_convergence_after_no_real_tool_rounds():
    assert (
        should_force_direct_chain_convergence(
            prefer_task_bootstrap_when_missing=True,
            stop_reason="no_tools_completed",
            consecutive_no_real_tool_rounds=3,
            max_no_real_tool_rounds=3,
            has_substantive_final_response=False,
        )
        is True
    )


def test_should_not_force_direct_chain_convergence_for_non_deep_mode():
    assert (
        should_force_direct_chain_convergence(
            prefer_task_bootstrap_when_missing=False,
            stop_reason="no_tools_completed",
            consecutive_no_real_tool_rounds=5,
            max_no_real_tool_rounds=3,
            has_substantive_final_response=False,
        )
        is False
    )


def test_should_not_force_direct_chain_convergence_with_substantive_response():
    assert (
        should_force_direct_chain_convergence(
            prefer_task_bootstrap_when_missing=True,
            stop_reason="tool_failed",
            consecutive_no_real_tool_rounds=4,
            max_no_real_tool_rounds=3,
            has_substantive_final_response=True,
        )
        is False
    )


def test_is_balance_not_enough_error_message_detects_marker():
    assert is_balance_not_enough_error_message("provider rejected request: BALANCE_NOT_ENOUGH") is True
    assert is_balance_not_enough_error_message("balance_not_enough from upstream provider") is True
    assert is_balance_not_enough_error_message("connection timed out") is False


def test_build_environment_blocked_report_text_for_balance_not_enough():
    text = build_environment_blocked_report_text(
        error_message="BALANCE_NOT_ENOUGH",
        current_model_name="deepseek-v3.2",
    )

    assert "环境阻塞报告" in text
    assert "BALANCE_NOT_ENOUGH" in text
    assert "不输出伪造研究结论" in text


def test_choose_recoverable_stream_fallback_model_prefers_non_ollama_default():
    assert (
        choose_recoverable_stream_fallback_model(
            current_model_name="ollama_chat/qwen3:14b",
            configured_fallback_model="deepseek-v3.2",
        )
        == "deepseek-v3.2"
    )


def test_choose_recoverable_stream_fallback_model_returns_none_when_already_on_fallback():
    assert (
        choose_recoverable_stream_fallback_model(
            current_model_name="deepseek-v3.2",
            configured_fallback_model="deepseek-v3.2",
        )
        is None
    )


def test_choose_recoverable_stream_fallback_model_switches_dashscope_to_siliconflow_on_provider_error():
    assert (
        choose_recoverable_stream_fallback_model(
            current_model_name="deepseek-v3.2",
            configured_fallback_model="deepseek-v3.2",
            error_message="overdue-payment",
            siliconflow_available=True,
            dashscope_available=True,
        )
        == "deepseek-siliconflow"
    )


def test_choose_recoverable_stream_fallback_model_switches_siliconflow_to_dashscope_on_provider_error():
    assert (
        choose_recoverable_stream_fallback_model(
            current_model_name="deepseek-siliconflow",
            configured_fallback_model="deepseek-v3.2",
            error_message="model-studio/error-code",
            siliconflow_available=True,
            dashscope_available=True,
        )
        == "deepseek-v3.2"
    )


def test_should_force_tool_failed_fallback_requires_no_evidence_and_no_substantive_response():
    assert (
        should_force_tool_failed_fallback(
            stop_reason="tool_failed",
            failed_non_terminating_tools={"browser_navigate_to"},
            completed_non_terminating_tools=set(),
            has_substantive_final_response=False,
            has_evidence=False,
        )
        is True
    )


def test_should_force_tool_failed_fallback_is_false_when_evidence_exists():
    assert (
        should_force_tool_failed_fallback(
            stop_reason="tool_failed",
            failed_non_terminating_tools={"browser_navigate_to"},
            completed_non_terminating_tools=set(),
            has_substantive_final_response=False,
            has_evidence=True,
        )
        is False
    )


def test_should_not_force_tool_failed_fallback_when_response_is_substantive():
    assert (
        should_force_tool_failed_fallback(
            stop_reason="tool_failed",
            failed_non_terminating_tools={"create_tasks"},
            completed_non_terminating_tools=set(),
            has_substantive_final_response=True,
            has_evidence=False,
        )
        is False
    )


def test_build_stream_error_fallback_text_includes_error_and_recovery_attempts():
    text = build_stream_error_fallback_text(
        error_message="litellm.APIConnectionError: Ollama_chatException - Server disconnected",
        current_model_name="ollama_chat/qwen3:14b",
        retry_count=2,
        max_retries=2,
    )

    assert "连接中断" in text
    assert "ollama_chat/qwen3:14b" in text
    assert "2/2" in text
    assert "Server disconnected" in text


def test_build_stream_error_fallback_text_for_provider_account_error():
    text = build_stream_error_fallback_text(
        error_message="overdue-payment",
        current_model_name="deepseek-v3.2",
        retry_count=1,
        max_retries=2,
    )

    assert "账户状态校验阶段被拒绝" in text
    assert "不输出伪造研究结论" in text
    assert "deepseek-v3.2" in text


def test_should_allow_task_replan_when_user_explicitly_requests_it():
    assert should_allow_task_replan("请重新规划任务并重置任务清单") is True
    assert should_allow_task_replan("please replan the task list") is True


def test_should_not_allow_task_replan_for_regular_requests():
    assert should_allow_task_replan("请继续完成深度搜索") is False
    assert should_allow_task_replan("") is False


def test_should_require_task_list_bootstrap_for_deep_research_requests():
    assert (
        should_require_task_list_bootstrap(
            "Deep research workflow with create_tasks and web_search"
        )
        is True
    )
    assert should_require_task_list_bootstrap("请执行深度搜索并输出结构化报告") is True


def test_should_not_require_task_list_bootstrap_for_general_chat():
    assert should_require_task_list_bootstrap("hello there") is False
    assert should_require_task_list_bootstrap("") is False


def test_should_allow_task_deletion_tools_only_on_explicit_requests():
    assert should_allow_task_deletion_tools("please delete task list and recreate") is True
    assert should_allow_task_deletion_tools("请删除任务清单后重建") is True
    assert should_allow_task_deletion_tools("continue deep research") is False


def test_should_allow_path_cleanup_tools_only_on_explicit_requests():
    assert should_allow_path_cleanup_tools("clean path for this file") is True
    assert should_allow_path_cleanup_tools("请规范路径格式") is True
    assert should_allow_path_cleanup_tools("run web search") is False


def test_deep_research_focus_gating_disables_noisy_and_destructive_tools():
    available = {
        "test_calculator": object(),
        "test_echo": object(),
        "clear_all": object(),
        "delete_tasks": object(),
        "clean_path": object(),
        "create_tasks": object(),
        "view_tasks": object(),
        "web_search": object(),
    }

    gated = apply_deep_research_focus_gating(
        available_functions=available,
        user_request="Deep research workflow with create_tasks and web_search",
        allow_task_replan=False,
    )

    assert "test_calculator" not in gated
    assert "test_echo" not in gated
    assert "clear_all" not in gated
    assert "delete_tasks" not in gated
    assert "clean_path" not in gated
    assert "create_tasks" in gated
    assert "web_search" in gated


def test_deep_research_focus_gating_keeps_delete_and_clean_when_explicitly_requested():
    available = {
        "delete_tasks": object(),
        "clean_path": object(),
        "create_tasks": object(),
        "web_search": object(),
    }

    gated = apply_deep_research_focus_gating(
        available_functions=available,
        user_request="Deep research and please delete task list and clean path first",
        allow_task_replan=False,
    )

    assert "delete_tasks" in gated
    assert "clean_path" in gated
    assert "create_tasks" in gated


def test_deep_research_focus_gating_filters_unrelated_tools_via_allowlist():
    available = {
        "create_tasks": object(),
        "view_tasks": object(),
        "web_search": object(),
        "edit_file": object(),
        "read_file": object(),
    }

    gated = apply_deep_research_focus_gating(
        available_functions=available,
        user_request="请执行深度搜索并输出结构化报告",
        allow_task_replan=False,
    )

    assert "create_tasks" in gated
    assert "view_tasks" in gated
    assert "web_search" in gated
    assert "edit_file" not in gated
    assert "read_file" not in gated


def test_non_research_sandbox_prompt_gating_hides_task_list_tools():
    available = {
        "create_tasks": object(),
        "view_tasks": object(),
        "update_tasks": object(),
        "clean_path": object(),
        "screenshot": object(),
        "click": object(),
    }

    gated = apply_deep_research_focus_gating(
        available_functions=available,
        user_request="请在sandbox里截图并点击一个按钮",
        allow_task_replan=False,
    )

    assert "create_tasks" not in gated
    assert "view_tasks" not in gated
    assert "update_tasks" not in gated
    assert "clean_path" not in gated
    assert "screenshot" in gated
    assert "click" in gated


def test_gating_disables_create_tasks_when_plan_exists_and_replan_not_allowed():
    available = {
        "create_tasks": object(),
        "view_tasks": object(),
        "web_search": object(),
    }
    task_list_state = {
        "exists": True,
        "pending_tasks": 4,
        "completed_tasks": 0,
        "total_tasks": 4,
        "next_pending_task_content": "Research market size",
    }

    gated = apply_task_list_tool_gating(
        available_functions=available,
        task_list_state=task_list_state,
        allow_task_replan=False,
        previous_completed_signature=None,
        repeated_signature_streak=0,
    )

    assert "create_tasks" not in gated
    assert "view_tasks" in gated


def test_gating_disables_view_tasks_until_create_tasks_when_bootstrap_required():
    available = {
        "create_tasks": object(),
        "view_tasks": object(),
        "web_search": object(),
    }
    task_list_state = {
        "exists": False,
        "pending_tasks": 0,
        "completed_tasks": 0,
        "total_tasks": 0,
        "next_pending_task_content": "",
    }

    gated = apply_task_list_tool_gating(
        available_functions=available,
        task_list_state=task_list_state,
        allow_task_replan=False,
        previous_completed_signature=None,
        repeated_signature_streak=0,
        prefer_task_bootstrap_when_missing=True,
    )

    assert "create_tasks" in gated
    assert "view_tasks" not in gated
    assert "web_search" not in gated
    assert set(gated.keys()) == {"create_tasks"}


def test_gating_disables_view_tasks_for_bootstrap_when_existing_task_list_is_empty():
    available = {
        "create_tasks": object(),
        "view_tasks": object(),
        "web_search": object(),
    }
    task_list_state = {
        "exists": True,
        "pending_tasks": 0,
        "completed_tasks": 0,
        "total_tasks": 0,
        "next_pending_task_content": "",
    }

    gated = apply_task_list_tool_gating(
        available_functions=available,
        task_list_state=task_list_state,
        allow_task_replan=False,
        previous_completed_signature=None,
        repeated_signature_streak=0,
        prefer_task_bootstrap_when_missing=True,
    )

    assert "create_tasks" in gated
    assert "view_tasks" not in gated
    assert "web_search" not in gated
    assert set(gated.keys()) == {"create_tasks"}


def test_gating_forces_view_tasks_after_create_tasks_round():
    available = {
        "create_tasks": object(),
        "view_tasks": object(),
        "update_tasks": object(),
        "web_search": object(),
        "scrape_webpage": object(),
    }
    task_list_state = {
        "exists": True,
        "pending_tasks": 5,
        "completed_tasks": 0,
        "total_tasks": 5,
        "next_pending_task_content": "Collect primary sources",
    }

    gated = apply_task_list_tool_gating(
        available_functions=available,
        task_list_state=task_list_state,
        allow_task_replan=False,
        previous_completed_signature=("create_tasks",),
        repeated_signature_streak=1,
    )

    assert set(gated.keys()) == {"view_tasks"}


def test_gating_delays_update_tasks_until_execution_round():
    available = {
        "create_tasks": object(),
        "view_tasks": object(),
        "update_tasks": object(),
        "web_search": object(),
    }
    task_list_state = {
        "exists": True,
        "pending_tasks": 3,
        "completed_tasks": 0,
        "total_tasks": 3,
        "next_pending_task_content": "Research market size",
    }

    gated = apply_task_list_tool_gating(
        available_functions=available,
        task_list_state=task_list_state,
        allow_task_replan=False,
        previous_completed_signature=("view_tasks",),
        repeated_signature_streak=1,
    )

    assert "update_tasks" not in gated
    assert "web_search" in gated

    gated_after_execution = apply_task_list_tool_gating(
        available_functions=available,
        task_list_state=task_list_state,
        allow_task_replan=False,
        previous_completed_signature=("web_search",),
        repeated_signature_streak=1,
    )

    assert "update_tasks" in gated_after_execution


def test_gating_forces_view_tasks_before_execution_when_refresh_required():
    available = {
        "create_tasks": object(),
        "view_tasks": object(),
        "update_tasks": object(),
        "web_search": object(),
        "scrape_webpage": object(),
    }
    task_list_state = {
        "exists": True,
        "pending_tasks": 3,
        "completed_tasks": 1,
        "total_tasks": 4,
        "next_pending_task_content": "Research competitor pricing",
    }

    gated = apply_task_list_tool_gating(
        available_functions=available,
        task_list_state=task_list_state,
        allow_task_replan=False,
        previous_completed_signature=("update_tasks",),
        repeated_signature_streak=1,
        require_view_tasks_refresh_before_execution=True,
    )

    assert set(gated.keys()) == {"view_tasks"}


def test_gating_does_not_force_view_tasks_without_pending_tasks():
    available = {
        "create_tasks": object(),
        "view_tasks": object(),
        "update_tasks": object(),
        "web_search": object(),
    }
    task_list_state = {
        "exists": True,
        "pending_tasks": 0,
        "completed_tasks": 2,
        "total_tasks": 2,
        "next_pending_task_content": "",
    }

    gated = apply_task_list_tool_gating(
        available_functions=available,
        task_list_state=task_list_state,
        allow_task_replan=False,
        previous_completed_signature=("update_tasks",),
        repeated_signature_streak=1,
        require_view_tasks_refresh_before_execution=True,
    )

    assert "view_tasks" in gated
    assert "web_search" in gated
    assert len(gated) > 1


def test_gating_temporarily_disables_view_tasks_after_repeat_view_only_rounds():
    available = {
        "create_tasks": object(),
        "view_tasks": object(),
        "web_search": object(),
    }
    task_list_state = {
        "exists": True,
        "pending_tasks": 2,
        "completed_tasks": 1,
        "total_tasks": 3,
        "next_pending_task_content": "Collect source links",
    }

    gated = apply_task_list_tool_gating(
        available_functions=available,
        task_list_state=task_list_state,
        allow_task_replan=False,
        previous_completed_signature=("view_tasks",),
        repeated_signature_streak=2,
    )

    assert "view_tasks" not in gated
    assert "create_tasks" not in gated


def test_gating_temporarily_disables_update_tasks_after_repeat_update_only_rounds():
    available = {
        "create_tasks": object(),
        "view_tasks": object(),
        "update_tasks": object(),
        "web_search": object(),
    }
    task_list_state = {
        "exists": True,
        "pending_tasks": 2,
        "completed_tasks": 1,
        "total_tasks": 3,
        "next_pending_task_content": "Collect source links",
    }

    gated = apply_task_list_tool_gating(
        available_functions=available,
        task_list_state=task_list_state,
        allow_task_replan=False,
        previous_completed_signature=("update_tasks",),
        repeated_signature_streak=2,
    )

    assert "update_tasks" not in gated
    assert "view_tasks" in gated


def test_gating_keeps_create_tasks_when_user_explicitly_requests_replan():
    available = {
        "create_tasks": object(),
        "view_tasks": object(),
        "web_search": object(),
    }
    task_list_state = {
        "exists": True,
        "pending_tasks": 2,
        "completed_tasks": 1,
        "total_tasks": 3,
        "next_pending_task_content": "Collect source links",
    }

    gated = apply_task_list_tool_gating(
        available_functions=available,
        task_list_state=task_list_state,
        allow_task_replan=True,
        previous_completed_signature=("create_tasks",),
        repeated_signature_streak=2,
    )

    assert "create_tasks" in gated
    assert "view_tasks" in gated


def test_gating_keeps_create_tasks_before_any_plan_exists():
    available = {
        "create_tasks": object(),
        "view_tasks": object(),
        "web_search": object(),
    }
    task_list_state = {
        "exists": False,
        "pending_tasks": 0,
        "completed_tasks": 0,
        "total_tasks": 0,
        "next_pending_task_content": "",
    }

    gated = apply_task_list_tool_gating(
        available_functions=available,
        task_list_state=task_list_state,
        allow_task_replan=False,
        previous_completed_signature=None,
        repeated_signature_streak=0,
    )

    assert "create_tasks" in gated
    assert "view_tasks" in gated


def test_high_frequency_gating_disables_web_search_after_repeated_search_rounds():
    available = {
        "web_search": object(),
        "view_tasks": object(),
        "scrape_webpage": object(),
    }

    gated = apply_high_frequency_tool_gating(
        available_functions=available,
        previous_completed_signature=("web_search",),
        repeated_signature_streak=3,
    )

    assert "web_search" not in gated
    assert "view_tasks" in gated
    assert "scrape_webpage" in gated


def test_high_frequency_gating_keeps_web_search_before_threshold():
    available = {
        "web_search": object(),
        "view_tasks": object(),
    }

    gated = apply_high_frequency_tool_gating(
        available_functions=available,
        previous_completed_signature=("web_search",),
        repeated_signature_streak=1,
    )

    assert "web_search" in gated
    assert "view_tasks" in gated


def test_high_frequency_gating_lowers_web_search_threshold_with_pending_tasks():
    available = {
        "web_search": object(),
        "update_tasks": object(),
        "scrape_webpage": object(),
    }
    task_list_state = {
        "exists": True,
        "pending_tasks": 4,
        "completed_tasks": 1,
        "total_tasks": 5,
        "next_pending_task_content": "Cross-check sources",
    }

    gated = apply_high_frequency_tool_gating(
        available_functions=available,
        previous_completed_signature=("web_search",),
        repeated_signature_streak=2,
        task_list_state=task_list_state,
    )

    assert "web_search" not in gated
    assert "update_tasks" in gated


def test_high_frequency_gating_disables_screenshot_after_repeated_screenshot_rounds():
    available = {
        "screenshot": object(),
        "browser_navigate": object(),
    }

    gated = apply_high_frequency_tool_gating(
        available_functions=available,
        previous_completed_signature=("screenshot",),
        repeated_signature_streak=4,
    )

    assert "screenshot" not in gated
    assert "browser_navigate" in gated


def test_high_frequency_gating_keeps_screenshot_before_threshold():
    available = {
        "screenshot": object(),
        "browser_navigate": object(),
    }

    gated = apply_high_frequency_tool_gating(
        available_functions=available,
        previous_completed_signature=("screenshot",),
        repeated_signature_streak=3,
    )

    assert "screenshot" in gated
    assert "browser_navigate" in gated


def test_cumulative_budget_gating_disables_create_tasks_after_first_completion():
    available = {
        "create_tasks": object(),
        "view_tasks": object(),
    }

    gated = apply_cumulative_tool_budget_gating(
        available_functions=available,
        cumulative_completed_tool_counts={"create_tasks": 1},
        allow_task_replan=False,
    )

    assert "create_tasks" not in gated
    assert "view_tasks" in gated


def test_cumulative_budget_gating_disables_web_search_after_budget_reached():
    available = {
        "web_search": object(),
        "update_tasks": object(),
    }

    gated = apply_cumulative_tool_budget_gating(
        available_functions=available,
        cumulative_completed_tool_counts={"web_search": 3},
        allow_task_replan=False,
    )

    assert "web_search" not in gated
    assert "update_tasks" in gated


def test_cumulative_budget_gating_disables_screenshot_after_budget_reached():
    available = {
        "screenshot": object(),
        "update_tasks": object(),
    }

    gated = apply_cumulative_tool_budget_gating(
        available_functions=available,
        cumulative_completed_tool_counts={"screenshot": 3},
        allow_task_replan=False,
    )

    assert "screenshot" not in gated
    assert "update_tasks" in gated


def test_failed_budget_gating_disables_browser_navigate_after_threshold():
    available = {
        "browser_navigate_to": object(),
        "view_tasks": object(),
    }

    gated = apply_failed_tool_budget_gating(
        available_functions=available,
        cumulative_failed_tool_counts={"browser_navigate_to": 2},
    )

    assert "browser_navigate_to" not in gated
    assert "view_tasks" in gated


def test_failed_budget_gating_keeps_tool_before_threshold():
    available = {
        "scrape_webpage": object(),
        "web_search": object(),
    }

    gated = apply_failed_tool_budget_gating(
        available_functions=available,
        cumulative_failed_tool_counts={"scrape_webpage": 1},
    )

    assert "scrape_webpage" in gated
    assert "web_search" in gated


def test_required_research_chain_gating_enforces_create_tasks_first():
    available = {
        "create_tasks": object(),
        "view_tasks": object(),
        "web_search": object(),
    }
    chain_progress = {
        "has_created_tasks": False,
        "has_viewed_tasks": False,
        "has_web_search": False,
        "has_scrape_webpage": False,
        "has_screenshot": False,
        "has_updated_tasks": False,
    }

    gated = apply_required_research_chain_gating(
        available_functions=available,
        enforce_chain=True,
        chain_progress=chain_progress,
    )

    assert set(gated.keys()) == {"create_tasks"}


def test_required_research_chain_gating_moves_to_view_tasks_after_create():
    available = {
        "create_tasks": object(),
        "view_tasks": object(),
        "web_search": object(),
    }
    chain_progress = {
        "has_created_tasks": True,
        "has_viewed_tasks": False,
        "has_web_search": False,
        "has_scrape_webpage": False,
        "has_screenshot": False,
        "has_updated_tasks": False,
    }

    gated = apply_required_research_chain_gating(
        available_functions=available,
        enforce_chain=True,
        chain_progress=chain_progress,
    )

    assert set(gated.keys()) == {"view_tasks"}


def test_required_research_chain_gating_skips_missing_scrape_stage_and_uses_screenshot():
    available = {
        "screenshot": object(),
        "update_tasks": object(),
    }
    chain_progress = {
        "has_created_tasks": True,
        "has_viewed_tasks": True,
        "has_web_search": True,
        "has_scrape_webpage": False,
        "has_screenshot": False,
        "has_updated_tasks": False,
    }

    gated = apply_required_research_chain_gating(
        available_functions=available,
        enforce_chain=True,
        chain_progress=chain_progress,
    )

    assert set(gated.keys()) == {"screenshot"}


def test_required_research_chain_gating_uses_fallback_toolset_for_update_stage():
    available = {
        "web_search": object(),
    }
    fallback_available = {
        "update_tasks": object(),
        "web_search": object(),
    }
    chain_progress = {
        "has_created_tasks": True,
        "has_viewed_tasks": True,
        "has_web_search": True,
        "has_scrape_webpage": True,
        "has_screenshot": True,
        "has_updated_tasks": False,
    }

    gated = apply_required_research_chain_gating(
        available_functions=available,
        enforce_chain=True,
        chain_progress=chain_progress,
        stage_index=5,
        fallback_functions=fallback_available,
    )

    assert set(gated.keys()) == {"update_tasks"}


def test_required_research_chain_gating_does_not_skip_missing_create_stage():
    available = {
        "view_tasks": object(),
        "web_search": object(),
    }
    chain_progress = {
        "has_created_tasks": False,
        "has_viewed_tasks": False,
        "has_web_search": False,
        "has_scrape_webpage": False,
        "has_screenshot": False,
        "has_updated_tasks": False,
    }

    gated = apply_required_research_chain_gating(
        available_functions=available,
        enforce_chain=True,
        chain_progress=chain_progress,
    )

    assert gated == {}


def test_required_research_chain_gating_does_not_skip_missing_update_stage():
    available = {
        "web_search": object(),
        "screenshot": object(),
    }
    chain_progress = {
        "has_created_tasks": True,
        "has_viewed_tasks": True,
        "has_web_search": True,
        "has_scrape_webpage": True,
        "has_screenshot": True,
        "has_updated_tasks": False,
    }

    gated = apply_required_research_chain_gating(
        available_functions=available,
        enforce_chain=True,
        chain_progress=chain_progress,
        stage_index=5,
    )

    assert gated == {}


def test_task_list_bootstrap_gating_is_not_reapplied_after_bootstrap_completed():
    available = {
        "create_tasks": object(),
        "view_tasks": object(),
        "web_search": object(),
    }
    task_list_state = {
        "exists": False,
        "pending_tasks": 0,
        "completed_tasks": 0,
        "total_tasks": 0,
        "next_pending_task_content": "",
    }

    gated = apply_task_list_tool_gating(
        available_functions=available,
        task_list_state=task_list_state,
        allow_task_replan=False,
        previous_completed_signature=("create_tasks",),
        repeated_signature_streak=1,
        prefer_task_bootstrap_when_missing=True,
        bootstrap_completed=True,
    )

    assert "create_tasks" in gated
    assert "view_tasks" in gated
    assert "web_search" in gated


def test_gating_disables_create_tasks_after_bootstrap_completed_when_task_list_exists():
    available = {
        "create_tasks": object(),
        "view_tasks": object(),
        "web_search": object(),
    }
    task_list_state = {
        "exists": True,
        "pending_tasks": 0,
        "completed_tasks": 3,
        "total_tasks": 3,
        "next_pending_task_content": "",
    }

    gated = apply_task_list_tool_gating(
        available_functions=available,
        task_list_state=task_list_state,
        allow_task_replan=False,
        previous_completed_signature=("update_tasks",),
        repeated_signature_streak=1,
        prefer_task_bootstrap_when_missing=True,
        bootstrap_completed=True,
    )

    assert "create_tasks" not in gated
    assert "view_tasks" in gated


def test_advance_required_research_chain_state_skips_scrape_after_failure_without_regressing():
    chain_progress = {
        "has_created_tasks": True,
        "has_viewed_tasks": True,
        "has_web_search": True,
        "has_scrape_webpage": False,
        "has_screenshot": False,
        "has_updated_tasks": False,
    }
    stage_index = advance_required_research_chain_state(
        chain_progress=chain_progress,
        current_stage_index=3,
        task_list_state={
            "exists": True,
            "pending_tasks": 3,
            "completed_tasks": 0,
            "total_tasks": 3,
            "next_pending_task_content": "Collect source URLs",
        },
        available_functions={"screenshot": object(), "update_tasks": object()},
        scrape_stage_failed=True,
    )

    assert chain_progress["has_scrape_webpage"] is True
    assert stage_index == 4

    # Stage index should never move backwards even if an external state read is temporarily empty.
    stage_index_after_transient_empty_state = advance_required_research_chain_state(
        chain_progress=chain_progress,
        current_stage_index=stage_index,
        task_list_state={
            "exists": False,
            "pending_tasks": 0,
            "completed_tasks": 0,
            "total_tasks": 0,
            "next_pending_task_content": "",
        },
        available_functions={"screenshot": object(), "update_tasks": object()},
        scrape_stage_failed=False,
    )
    assert stage_index_after_transient_empty_state == 4


def test_mark_required_research_chain_progress_maps_tool_to_stage_key():
    chain_progress = {
        "has_created_tasks": False,
        "has_viewed_tasks": False,
        "has_web_search": False,
        "has_scrape_webpage": False,
        "has_screenshot": False,
        "has_updated_tasks": False,
    }

    stage_key = mark_required_research_chain_progress(chain_progress, "screenshot")

    assert stage_key == "has_screenshot"
    assert chain_progress["has_screenshot"] is True


def test_choose_tool_execution_strategy_enforces_sequential_for_deep_research():
    assert choose_tool_execution_strategy(enforce_task_chain=True) == "sequential"


def test_choose_tool_execution_strategy_keeps_parallel_for_non_deep_runs():
    assert choose_tool_execution_strategy(enforce_task_chain=False) == "parallel"


def test_choose_max_xml_tool_calls_per_iteration_strict_for_planning_stages():
    assert (
        choose_max_xml_tool_calls_per_iteration(
            configured_max_calls=8,
            enforce_task_chain=True,
            required_chain_stage_index=0,
        )
        == 1
    )
    assert (
        choose_max_xml_tool_calls_per_iteration(
            configured_max_calls=8,
            enforce_task_chain=True,
            required_chain_stage_index=5,
        )
        == 1
    )


def test_choose_max_xml_tool_calls_per_iteration_caps_execution_stage_for_deep_research():
    assert (
        choose_max_xml_tool_calls_per_iteration(
            configured_max_calls=8,
            enforce_task_chain=True,
            required_chain_stage_index=2,
        )
        == 2
    )


def test_choose_max_xml_tool_calls_per_iteration_uses_configured_value_for_non_deep_runs():
    assert (
        choose_max_xml_tool_calls_per_iteration(
            configured_max_calls=8,
            enforce_task_chain=False,
            required_chain_stage_index=0,
        )
        == 8
    )
