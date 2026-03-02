import json

import pytest

from agent.tools.task_list_tool import Section, Task, TaskListTool, TaskStatus


@pytest.mark.asyncio
async def test_create_tasks_skips_duplicate_entries_and_reports_counts():
    tool = TaskListTool(project_id="p1", thread_manager=None, thread_id="t1")

    existing_sections = [Section(id="sec-1", title="Research")]
    existing_tasks = [Task(id="task-1", content="Search trend report", section_id="sec-1")]
    saved = {}

    async def fake_load_data():
        return list(existing_sections), list(existing_tasks)

    async def fake_save_data(sections, tasks):
        saved["sections"] = sections
        saved["tasks"] = tasks

    tool._load_data = fake_load_data
    tool._save_data = fake_save_data

    result = await tool.create_tasks(
        sections=[
            {
                "title": "Research",
                "tasks": ["Search trend report", "Compare major platforms"],
            }
        ]
    )

    assert result.success is True

    payload = json.loads(result.output)
    assert payload["total_tasks"] == 2
    assert payload["task_creation"]["created_tasks"] == 1
    assert payload["task_creation"]["skipped_duplicate_tasks"] == 1
    assert payload["task_creation"]["plan_reused"] is False

    assert len(saved["tasks"]) == 2


@pytest.mark.asyncio
async def test_create_tasks_returns_reuse_hint_when_all_new_tasks_are_duplicates():
    tool = TaskListTool(project_id="p1", thread_manager=None, thread_id="t1")

    existing_sections = [Section(id="sec-1", title="Research")]
    existing_tasks = [Task(id="task-1", content="Search trend report", section_id="sec-1")]
    saved = {}

    async def fake_load_data():
        return list(existing_sections), list(existing_tasks)

    async def fake_save_data(sections, tasks):
        saved["sections"] = sections
        saved["tasks"] = tasks

    tool._load_data = fake_load_data
    tool._save_data = fake_save_data

    result = await tool.create_tasks(
        sections=[
            {
                "title": "Research",
                "tasks": ["Search trend report"],
            }
        ]
    )

    assert result.success is True

    payload = json.loads(result.output)
    assert payload["total_tasks"] == 1
    assert payload["task_creation"]["created_tasks"] == 0
    assert payload["task_creation"]["skipped_duplicate_tasks"] == 1
    assert payload["task_creation"]["plan_reused"] is True
    assert "view_tasks" in payload["task_creation"]["next_step_hint"]

    assert len(saved["tasks"]) == 1


@pytest.mark.asyncio
async def test_create_tasks_reuses_existing_plan_when_called_with_empty_payload():
    tool = TaskListTool(project_id="p1", thread_manager=None, thread_id="t1")

    existing_sections = [Section(id="sec-1", title="Research")]
    existing_tasks = [Task(id="task-1", content="Search trend report", section_id="sec-1")]
    saved = {"called": False}

    async def fake_load_data():
        return list(existing_sections), list(existing_tasks)

    async def fake_save_data(sections, tasks):
        saved["called"] = True

    tool._load_data = fake_load_data
    tool._save_data = fake_save_data

    result = await tool.create_tasks()

    assert result.success is True
    payload = json.loads(result.output)
    assert payload["total_tasks"] == 1
    assert payload["task_creation"]["plan_reused"] is True
    assert payload["task_creation"]["blocked_replan"] is True
    assert "view_tasks" in payload["task_creation"]["next_step_hint"]
    assert saved["called"] is False


@pytest.mark.asyncio
async def test_create_tasks_accepts_tasks_alias_payload_from_model_calls():
    tool = TaskListTool(project_id="p1", thread_manager=None, thread_id="t1")

    existing_sections = []
    existing_tasks = []
    saved = {}

    async def fake_load_data():
        return list(existing_sections), list(existing_tasks)

    async def fake_save_data(sections, tasks):
        saved["sections"] = sections
        saved["tasks"] = tasks

    tool._load_data = fake_load_data
    tool._save_data = fake_save_data

    result = await tool.create_tasks(
        tasks='[{"id":"task-1","content":"Define research scope"},{"id":"task-2","content":"Collect sources"}]'
    )

    assert result.success is True
    payload = json.loads(result.output)
    assert payload["total_tasks"] == 2
    assert payload["task_creation"]["created_tasks"] == 2
    assert len(saved["tasks"]) == 2


@pytest.mark.asyncio
async def test_create_tasks_accepts_section_container_tasks_alias_payload():
    tool = TaskListTool(project_id="p1", thread_manager=None, thread_id="t1")

    existing_sections = []
    existing_tasks = []
    saved = {}

    async def fake_load_data():
        return list(existing_sections), list(existing_tasks)

    async def fake_save_data(sections, tasks):
        saved["sections"] = sections
        saved["tasks"] = tasks

    tool._load_data = fake_load_data
    tool._save_data = fake_save_data

    payload = (
        '[{"section_name":"Research & Setup","tasks":[{"content":"Define scope","status":"pending"},'
        '{"content":"Plan search","status":"pending"}]},'
        '{"section_name":"Analysis","tasks":[{"content":"Cross-check sources","status":"pending"}]}]'
    )

    result = await tool.create_tasks(tasks=payload)

    assert result.success is True
    data = json.loads(result.output)
    assert data["total_tasks"] == 3
    assert data["task_creation"]["created_tasks"] == 3
    assert len(saved["sections"]) == 2
    assert len(saved["tasks"]) == 3


@pytest.mark.asyncio
async def test_create_tasks_accepts_flat_task_object_alias_with_title_description():
    tool = TaskListTool(project_id="p1", thread_manager=None, thread_id="t1")

    existing_sections = []
    existing_tasks = []
    saved = {}

    async def fake_load_data():
        return list(existing_sections), list(existing_tasks)

    async def fake_save_data(sections, tasks):
        saved["sections"] = sections
        saved["tasks"] = tasks

    tool._load_data = fake_load_data
    tool._save_data = fake_save_data

    payload = (
        '[{"title":"Initialize workflow","description":"Setup research validation","status":"pending"},'
        '{"title":"Run web search","description":"Gather evidence","status":"pending"}]'
    )

    result = await tool.create_tasks(tasks=payload)

    assert result.success is True
    data = json.loads(result.output)
    assert data["total_tasks"] == 2
    assert data["task_creation"]["created_tasks"] == 2
    assert len(saved["sections"]) == 1
    assert len(saved["tasks"]) == 2


@pytest.mark.asyncio
async def test_create_tasks_accepts_section_tasks_mapping_payload():
    tool = TaskListTool(project_id="p1", thread_manager=None, thread_id="t1")

    existing_sections = []
    existing_tasks = []
    saved = {}

    async def fake_load_data():
        return list(existing_sections), list(existing_tasks)

    async def fake_save_data(sections, tasks):
        saved["sections"] = sections
        saved["tasks"] = tasks

    tool._load_data = fake_load_data
    tool._save_data = fake_save_data

    tasks_payload = (
        '[{"id":"task-1","content":"Define scope","status":"pending"},'
        '{"id":"task-2","content":"Run web search","status":"pending"}]'
    )
    sections_payload = (
        '[{"id":"section-1","name":"Research & Setup"},'
        '{"id":"section-2","name":"Information Gathering"}]'
    )
    section_tasks_payload = '{"section-1":["task-1"],"section-2":["task-2"]}'

    result = await tool.create_tasks(
        tasks=tasks_payload,
        sections=sections_payload,
        section_tasks=section_tasks_payload,
    )

    assert result.success is True
    data = json.loads(result.output)
    assert data["total_tasks"] == 2
    assert data["task_creation"]["created_tasks"] == 2
    assert len(saved["sections"]) == 2
    assert len(saved["tasks"]) == 2


@pytest.mark.asyncio
async def test_create_tasks_blocks_bulk_replan_when_existing_plan_not_started():
    tool = TaskListTool(project_id="p1", thread_manager=None, thread_id="t1")

    existing_sections = [
        Section(id="sec-1", title="Research"),
        Section(id="sec-2", title="Analysis"),
    ]
    existing_tasks = [
        Task(id="task-1", content="Search trend report", section_id="sec-1"),
        Task(id="task-2", content="Summarize findings", section_id="sec-2"),
    ]
    saved = {"called": False}

    async def fake_load_data():
        return list(existing_sections), list(existing_tasks)

    async def fake_save_data(sections, tasks):
        saved["called"] = True

    tool._load_data = fake_load_data
    tool._save_data = fake_save_data

    result = await tool.create_tasks(
        sections=[
            {"title": "Plan A", "tasks": ["Task A1", "Task A2"]},
            {"title": "Plan B", "tasks": ["Task B1"]},
        ]
    )

    assert result.success is True
    payload = json.loads(result.output)

    assert payload["total_tasks"] == 2
    assert payload["task_creation"]["created_tasks"] == 0
    assert payload["task_creation"]["created_sections"] == 0
    assert payload["task_creation"]["plan_reused"] is True
    assert payload["task_creation"]["blocked_replan"] is True
    assert payload["task_creation"]["next_pending_task"]["id"] == "task-1"
    assert "execute" in payload["task_creation"]["next_step_hint"].lower()
    assert saved["called"] is False


@pytest.mark.asyncio
async def test_update_tasks_accepts_json_stringified_task_ids():
    tool = TaskListTool(project_id="p1", thread_manager=None, thread_id="t1")

    existing_sections = [Section(id="sec-1", title="Research")]
    existing_tasks = [Task(id="task-1", content="Search trend report", section_id="sec-1")]
    saved = {}

    async def fake_load_data():
        return list(existing_sections), list(existing_tasks)

    async def fake_save_data(sections, tasks):
        saved["sections"] = sections
        saved["tasks"] = tasks

    tool._load_data = fake_load_data
    tool._save_data = fake_save_data

    result = await tool.update_tasks(task_ids='["task-1"]', status="completed")

    assert result.success is True
    payload = json.loads(result.output)
    assert payload["total_tasks"] == 1
    assert saved["tasks"][0].status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_update_tasks_maps_task_index_alias_to_real_id():
    tool = TaskListTool(project_id="p1", thread_manager=None, thread_id="t1")

    existing_sections = [Section(id="sec-1", title="Research")]
    existing_tasks = [
        Task(id="uuid-1", content="Task one", section_id="sec-1"),
        Task(id="uuid-2", content="Task two", section_id="sec-1"),
    ]
    saved = {}

    async def fake_load_data():
        return list(existing_sections), list(existing_tasks)

    async def fake_save_data(sections, tasks):
        saved["sections"] = sections
        saved["tasks"] = tasks

    tool._load_data = fake_load_data
    tool._save_data = fake_save_data

    result = await tool.update_tasks(task_ids='["task-2"]', status="completed")

    assert result.success is True
    assert saved["tasks"][0].status == TaskStatus.PENDING
    assert saved["tasks"][1].status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_update_tasks_falls_back_to_next_pending_for_unresolved_synthetic_id():
    tool = TaskListTool(project_id="p1", thread_manager=None, thread_id="t1")

    existing_sections = [Section(id="sec-1", title="Research")]
    existing_tasks = [
        Task(id="uuid-1", content="Task one", section_id="sec-1"),
        Task(id="uuid-2", content="Task two", section_id="sec-1"),
    ]
    saved = {}

    async def fake_load_data():
        return list(existing_sections), list(existing_tasks)

    async def fake_save_data(sections, tasks):
        saved["sections"] = sections
        saved["tasks"] = tasks

    tool._load_data = fake_load_data
    tool._save_data = fake_save_data

    result = await tool.update_tasks(task_ids='["task-does-not-exist"]', status="completed")

    assert result.success is True
    assert saved["tasks"][0].status == TaskStatus.COMPLETED
    assert saved["tasks"][1].status == TaskStatus.PENDING


@pytest.mark.asyncio
async def test_update_tasks_falls_back_to_next_pending_when_task_ids_missing_for_completed_status():
    tool = TaskListTool(project_id="p1", thread_manager=None, thread_id="t1")

    existing_sections = [Section(id="sec-1", title="Research")]
    existing_tasks = [
        Task(id="uuid-1", content="Task one", section_id="sec-1"),
        Task(id="uuid-2", content="Task two", section_id="sec-1"),
    ]
    saved = {}

    async def fake_load_data():
        return list(existing_sections), list(existing_tasks)

    async def fake_save_data(sections, tasks):
        saved["sections"] = sections
        saved["tasks"] = tasks

    tool._load_data = fake_load_data
    tool._save_data = fake_save_data

    result = await tool.update_tasks(task_ids=None, status="completed")

    assert result.success is True
    assert saved["tasks"][0].status == TaskStatus.COMPLETED
    assert saved["tasks"][1].status == TaskStatus.PENDING


@pytest.mark.asyncio
async def test_update_tasks_maps_slug_task_reference_to_real_id():
    tool = TaskListTool(project_id="p1", thread_manager=None, thread_id="t1")

    existing_sections = [Section(id="sec-1", title="Research")]
    existing_tasks = [
        Task(
            id="uuid-1",
            content="Research OpenAI deep research API capabilities and features",
            section_id="sec-1",
        ),
        Task(
            id="uuid-2",
            content="Compare competitors and summarize differences",
            section_id="sec-1",
        ),
    ]
    saved = {}

    async def fake_load_data():
        return list(existing_sections), list(existing_tasks)

    async def fake_save_data(sections, tasks):
        saved["sections"] = sections
        saved["tasks"] = tasks

    tool._load_data = fake_load_data
    tool._save_data = fake_save_data

    result = await tool.update_tasks(
        task_ids='["research-openai-deep-research-api-capabilities-and-features"]',
        status="completed",
    )

    assert result.success is True
    assert saved["tasks"][0].status == TaskStatus.COMPLETED
    assert saved["tasks"][1].status == TaskStatus.PENDING


@pytest.mark.asyncio
async def test_update_tasks_falls_back_to_next_pending_for_unresolved_slug_like_id():
    tool = TaskListTool(project_id="p1", thread_manager=None, thread_id="t1")

    existing_sections = [Section(id="sec-1", title="Research")]
    existing_tasks = [
        Task(id="uuid-1", content="Collect OpenAI docs", section_id="sec-1"),
        Task(id="uuid-2", content="Compare with competitors", section_id="sec-1"),
    ]
    saved = {}

    async def fake_load_data():
        return list(existing_sections), list(existing_tasks)

    async def fake_save_data(sections, tasks):
        saved["sections"] = sections
        saved["tasks"] = tasks

    tool._load_data = fake_load_data
    tool._save_data = fake_save_data

    result = await tool.update_tasks(task_ids='["research-acceptance-test-v3"]', status="completed")

    assert result.success is True
    assert saved["tasks"][0].status == TaskStatus.COMPLETED
    assert saved["tasks"][1].status == TaskStatus.PENDING


@pytest.mark.asyncio
async def test_delete_tasks_accepts_json_stringified_section_ids():
    tool = TaskListTool(project_id="p1", thread_manager=None, thread_id="t1")

    existing_sections = [Section(id="sec-1", title="Research")]
    existing_tasks = [Task(id="task-1", content="Search trend report", section_id="sec-1")]
    saved = {}

    async def fake_load_data():
        return list(existing_sections), list(existing_tasks)

    async def fake_save_data(sections, tasks):
        saved["sections"] = sections
        saved["tasks"] = tasks

    tool._load_data = fake_load_data
    tool._save_data = fake_save_data

    result = await tool.delete_tasks(section_ids='["sec-1"]', confirm=True)

    assert result.success is True
    payload = json.loads(result.output)
    assert payload["total_sections"] == 0
    assert payload["total_tasks"] == 0
    assert saved["sections"] == []
    assert saved["tasks"] == []
