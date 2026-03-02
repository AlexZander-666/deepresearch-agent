from agentpress.tool import Tool, ToolResult
from utils.logger import logger
from typing import List, Dict, Any, Optional, Tuple
import json
import re
from pydantic import BaseModel, Field # type: ignore
from enum import Enum
import uuid
import asyncio

"""
为什么复杂任务需要任务清单？

&emsp;&emsp;假设用户提出一个复杂需求：\"帮我分析 OpenAI 在 2025年10月份发布会的主要技术突破，并与竞争对手对比\"。如果 AI 直接开始执行：

1. **无序执行**：可能先搜索 OpenAI，又突然跳去搜索 Google
2. **重复操作**：可能多次搜索同一个关键词
3. **遗漏步骤**：忘记对比竞争对手
4. **缺乏可控性**：用户无法了解执行进度


如果采用任务清单驱动后：

```
用户提出需求
    ↓
AI 生成结构化任务清单
    ↓
┌─────────────────────────────────┐
│    任务清单                      │
├─────────────────────────────────┤
│ 第一阶段：数据收集               │
│   □ 搜索 OpenAI 2025 技术突破    │
│   □ 搜索 Google AI 2025 进展     │
│   □ 搜索 Anthropic 2025 发布     │
│                                  │
│ 第二阶段：信息整理               │
│   □ 提取 OpenAI 关键技术点       │
│   □ 提取竞争对手技术点           │
│                                  │
│ 第三阶段：对比分析               │
│   □ 对比技术路线                 │
│   □ 撰写分析报告                 │
└─────────────────────────────────┘
    ↓
按顺序逐个执行任务
    ↓
实时更新任务状态 
    ↓
所有任务完成 → 总结输出

TASK_list:
以 JSON 格式存储：

```json
{
  "sections": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "title": "数据收集阶段"
    },
    {
      "id": "6fa459ea-ee8a-3ca4-894e-db77e160355e",
      "title": "信息整理阶段"
    }
  ],
  "tasks": [
    {
      "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
      "content": "搜索 OpenAI 2025 技术突破",
      "status": "completed",
      "section_id": "550e8400-e29b-41d4-a716-446655440000"
    },
    {
      "id": "8f14e45f-ceea-467a-9538-1fa21e57bb8e",
      "content": "搜索 Google AI 2025 进展",
      "status": "pending",
      "section_id": "550e8400-e29b-41d4-a716-446655440000"
    }
  ]
}


用户发送复杂问题
    ↓
┌─────────────────────────────────────────┐
│ Step 1: 生成任务清单                     │
│ 工具：create_tasks                       │
│ 输入：问题分析                           │
│ 输出：结构化的 sections + tasks           │
└──────────────┬──────────────────────────┘
               ↓
┌─────────────────────────────────────────┐
│ Step 2: 查看下一个任务                   │
│ 工具：view_tasks                         │
│ 输出：状态为 pending 的第一个任务         │
└──────────────┬──────────────────────────┘
               ↓
┌─────────────────────────────────────────┐
│ Step 3: 执行当前任务                     │
│ 调用相应工具：                           │
│ - web_search（网络搜索）                 │
│ - file_read（读取文件）                  │
│ - browser_navigate（浏览网页）           │
│ - ...                                    │
└──────────────┬──────────────────────────┘
               ↓
┌─────────────────────────────────────────┐
│ Step 4: 更新任务状态                     │
│ 工具：update_tasks                       │
│ 操作：将任务 status 改为 "completed"      │
└──────────────┬──────────────────────────┘
               ↓
┌─────────────────────────────────────────┐
│ Step 5: 检查是否还有待执行任务           │
└──────────────┬──────────────────────────┘
               ↓
        ┌──────┴──────┐
        │ 还有任务？   │
        └──┬─────┬────┘
       YES ↓     ↓ NO
    返回 Step 2  ↓
               ↓
┌─────────────────────────────────────────┐
│ Step 6: 所有任务完成                     │
│ 发送完成信号：'complete'                 │
│ 生成最终总结报告                         │
└─────────────────────────────────────────┘
"""
class TaskStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class Section(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    
class Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content: str
    status: TaskStatus = TaskStatus.PENDING
    section_id: str  # Reference to section ID instead of section name

class TaskListTool(Tool):
    """Simplified task management system - no extra class definitions."""
    
    def __init__(self, project_id: str, thread_manager, thread_id: str):
        super().__init__()
        self.project_id = project_id
        self.thread_manager = thread_manager
        self.thread_id = thread_id
        self.task_list_message_type = "task_list"
    
    async def _load_data(self) -> Tuple[List[Section], List[Task]]:
        """Load sections and tasks from storage"""
        try:
            client = await self.thread_manager.db.client
            result = await client.table('messages').select('*')\
                .eq('thread_id', self.thread_id)\
                .eq('type', self.task_list_message_type)\
                .order('created_at', desc=True).limit(1).execute()
            
            if result.data and result.data[0].get('content'):
                content = result.data[0]['content']
                if isinstance(content, str):
                    content = json.loads(content)
                
                # 提取 sections 和 tasks
                sections_data = content.get('sections', [])
                tasks_data = content.get('tasks', [])
                
                sections = []
                for i, s in enumerate(sections_data):
                    try:
                        section = Section(**s)
                        sections.append(section)
                        logger.debug(f"Created section {i}: {section.id}")
                    except Exception as e:
                        logger.error(f"Error creating section {i}: {e}, data: {s}")
                        raise
                        
                tasks = []
                for i, t in enumerate(tasks_data):
                    try:
                        # 检查 在创建 Task 对象之前，检查 raw task data 中的 coroutines
                        if 'status' in t and asyncio.iscoroutine(t['status']):
                            t['status'] = 'pending'  # Fix it
                        
                        task = Task(**t)
                        
                        # 再次检查创建的 task 中的 coroutines
                        if asyncio.iscoroutine(task.status):
                            task.status = TaskStatus.PENDING

                        tasks.append(task)
                        logger.debug(f"Created task {i}: {task.id}, status: {repr(task.status)}")
                    except Exception as e:
                        logger.error(f"Error creating task {i}: {e}, data: {t}")
                        raise
                
                # 处理旧格式迁移
                if not sections and 'sections' in content:
                    # 从旧的嵌套格式创建 sections
                    for old_section in content['sections']:
                        section = Section(title=old_section['title'])
                        sections.append(section)
                        
                        # 更新 tasks 以引用 section ID
                        for old_task in old_section.get('tasks', []):
                            task = Task(
                                content=old_task['content'],
                                status=TaskStatus(old_task.get('status', 'pending')),
                                section_id=section.id
                            )
                            if 'id' in old_task:
                                task.id = old_task['id']
                            tasks.append(task)
                
                return sections, tasks
            
            # 返回空列表 - 没有默认 section
            return [], []
            
        except Exception as e:
            logger.error(f"Error loading data: {e}")
            return [], []
    
    async def _save_data(self, sections: List[Section], tasks: List[Task]):
        """Save sections and tasks to storage"""
        try:
            client = await self.thread_manager.db.client
            logger.info("Saving task list payload (sections=%s, tasks=%s)", len(sections), len(tasks))

            normalized_sections = [section.model_dump() for section in sections]
            normalized_tasks = []
            for task in tasks:
                if asyncio.iscoroutine(task.status):
                    task.status = TaskStatus.PENDING
                if asyncio.iscoroutine(task.content):
                    task.content = ""
                if asyncio.iscoroutine(task.section_id):
                    task.section_id = ""
                normalized_tasks.append(task.model_dump())

            content = {
                'sections': normalized_sections,
                'tasks': normalized_tasks
            }

            # 找到已经存在的 message
            result = await client.table('messages').select('message_id')\
                .eq('thread_id', self.thread_id)\
                .eq('type', self.task_list_message_type)\
                .order('created_at', desc=True).limit(1).execute()

            json_content = json.dumps(content)

            if result.data:
                message_id_for_update = result.data[0]['message_id']
                await client.table('messages')\
                    .eq('message_id', message_id_for_update)\
                    .update({'content': json_content})
            else:
                # 创建新的
                await client.table('messages').insert({
                    'thread_id': self.thread_id,
                    'project_id': self.project_id,
                    'type': self.task_list_message_type,
                    'role': 'assistant',
                    'content': json_content,
                    'is_llm_message': False,
                    'metadata': json.dumps({})
                })
            
        except Exception as e:
            logger.error(f"Error saving data: {e}")
            raise

    def _format_response(self, sections: List[Section], tasks: List[Task]) -> Dict[str, Any]:
        """Format data for response"""
        # 展示任务时，按照section分组
        section_map = {s.id: s for s in sections}
        grouped_tasks = {}
        
        # 遍历
        for task in tasks:
            section_id = task.section_id
            if section_id not in grouped_tasks:
                grouped_tasks[section_id] = []
            grouped_tasks[section_id].append(task.model_dump())
        
        formatted_sections = []
        for section in sections:
            section_tasks = grouped_tasks.get(section.id, [])
            # 只展示有任务的section
            if section_tasks:
                formatted_sections.append({
                    "id": section.id,
                    "title": section.title,
                    "tasks": section_tasks
                })
        
        response = {
            "sections": formatted_sections,
            "total_tasks": len(tasks),  # 总是使用原始任务数量
            "total_sections": len(sections)
        }
        
        return response

    def _normalize_id_list(self, raw_ids: Any) -> List[str]:
        """Normalize IDs to a deduplicated string list.

        Accepts direct strings, arrays, nested arrays, and JSON-stringified arrays
        such as '["task-1","task-2"]'.
        """
        if raw_ids is None:
            return []

        if isinstance(raw_ids, str):
            text = raw_ids.strip()
            if not text:
                return []

            if text.startswith("[") and text.endswith("]"):
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    return [text]
                return self._normalize_id_list(parsed)

            return [text]

        if isinstance(raw_ids, (list, tuple, set)):
            normalized: List[str] = []
            for item in raw_ids:
                normalized.extend(self._normalize_id_list(item))

            # Keep stable order while removing duplicates.
            seen = set()
            deduped: List[str] = []
            for item in normalized:
                if item in seen:
                    continue
                seen.add(item)
                deduped.append(item)
            return deduped

        text = str(raw_ids).strip()
        return [text] if text else []

    def _slugify_task_reference(self, value: Any) -> str:
        """Normalize free-form task references to a slug for fuzzy matching."""
        text = str(value).strip().lower()
        if not text:
            return ""
        slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
        return slug

    def _resolve_task_ids(self, requested_ids: List[str], tasks: List[Task], status: Optional[str] = None) -> Tuple[List[str], List[str]]:
        """Resolve task id aliases to concrete IDs.

        Supported aliases:
        - `task-2` / `2`: maps to the second task in current task order (1-based).
        - `task-<uuid>`: maps to `<uuid>` when the prefixed form is used.
        - single unresolved synthetic `task-*` while completing: falls back to first pending task.
        """
        task_map = {task.id: task for task in tasks}
        ordered_task_ids = [task.id for task in tasks]
        task_slug_pairs: List[Tuple[str, str]] = []
        for task in tasks:
            task_slug = self._slugify_task_reference(task.content)
            if task_slug:
                task_slug_pairs.append((task_slug, task.id))

        resolved: List[str] = []
        unresolved: List[str] = []

        for requested in requested_ids:
            candidate = str(requested).strip()
            if not candidate:
                continue

            if candidate in task_map:
                resolved.append(candidate)
                continue

            mapped_id: Optional[str] = None
            alias_source = candidate

            if candidate.startswith("task-"):
                alias_source = candidate[5:]
                if alias_source in task_map:
                    mapped_id = alias_source
                elif alias_source.isdigit():
                    index = int(alias_source) - 1
                    if 0 <= index < len(ordered_task_ids):
                        mapped_id = ordered_task_ids[index]
            elif candidate.isdigit():
                index = int(candidate) - 1
                if 0 <= index < len(ordered_task_ids):
                    mapped_id = ordered_task_ids[index]

            if mapped_id:
                resolved.append(mapped_id)
                continue

            slug_candidate = self._slugify_task_reference(alias_source)
            if slug_candidate and len(slug_candidate) >= 6:
                for task_slug, task_id in task_slug_pairs:
                    if slug_candidate == task_slug:
                        mapped_id = task_id
                        break
                if not mapped_id:
                    for task_slug, task_id in task_slug_pairs:
                        if slug_candidate in task_slug or task_slug in slug_candidate:
                            mapped_id = task_id
                            break

            if mapped_id:
                resolved.append(mapped_id)
            else:
                unresolved.append(candidate)

        status_value = str(status).strip().lower() if status is not None else None
        if (
            not resolved
            and len(unresolved) == 1
            and status_value == TaskStatus.COMPLETED.value
            and unresolved[0].startswith("task-")
        ):
            # Model sometimes invents synthetic task-* IDs. Prefer continuing the workflow.
            for task in tasks:
                current_status = task.status.value if isinstance(task.status, TaskStatus) else str(task.status).strip().lower()
                if current_status == TaskStatus.PENDING.value:
                    logger.warning(
                        "Falling back unresolved synthetic task id '%s' to next pending task '%s'",
                        unresolved[0],
                        task.id,
                    )
                    resolved.append(task.id)
                    unresolved = []
                    break

        if unresolved and status_value == TaskStatus.COMPLETED.value:
            pending_ids = [
                task.id
                for task in tasks
                if (
                    task.status.value
                    if isinstance(task.status, TaskStatus)
                    else str(task.status).strip().lower()
                ) == TaskStatus.PENDING.value
                and task.id not in resolved
            ]
            if pending_ids:
                unresolved_copy = list(unresolved)
                unresolved = []
                for unresolved_task_id in unresolved_copy:
                    if not pending_ids:
                        unresolved.append(unresolved_task_id)
                        continue
                    fallback_task_id = pending_ids.pop(0)
                    logger.warning(
                        "Falling back unresolved task id '%s' to next pending task '%s'",
                        unresolved_task_id,
                        fallback_task_id,
                    )
                    resolved.append(fallback_task_id)

        deduped_resolved: List[str] = []
        seen = set()
        for task_id in resolved:
            if task_id in seen:
                continue
            seen.add(task_id)
            deduped_resolved.append(task_id)

        return deduped_resolved, unresolved

    async def create_tasks(self, sections: Optional[List[Dict[str, Any]]] = None,
                           section_title: Optional[str] = None, section_id: Optional[str] = None,
                           task_contents: Optional[List[str]] = None,
                           tasks: Optional[str] = None,
                           section_tasks: Optional[str] = None,
                           force_replan: bool = False,
                           **kwargs) -> ToolResult:
        """Create tasks organized by sections for project management.
        
        This function creates a structured task list organized into sections, supporting both 
        single section and multi-section batch creation. Creates sections automatically if they don't exist.
        Tasks should be created in the exact order they will be executed for sequential workflow.
        
        Usage Examples:
            # Batch creation across multiple sections:
            {
                "name": "create_tasks",
                "parameters": {
                    "sections": [
                        {
                            "title": "Setup & Planning", 
                            "tasks": ["Research requirements", "Create project plan"]
                        },
                        {
                            "title": "Development", 
                            "tasks": ["Setup environment", "Write code", "Add tests"]
                        },
                        {
                            "title": "Deployment", 
                            "tasks": ["Deploy to staging", "Run tests", "Deploy to production"]
                        }
                    ]
                }
            }
            
            # Simple single section creation:
            {
                "name": "create_tasks",
                "parameters": {
                    "section_title": "Bug Fixes",
                    "task_contents": ["Fix login issue", "Update error handling"]
                }
            }
        
        Args:
            sections: List of sections with their tasks for batch creation. Each section should have 'title' and 'tasks' fields.
                     Example: [{"title": "Setup & Planning", "tasks": ["Research requirements", "Create project plan"]}]
            section_title: Single section title (creates if doesn't exist - use this OR sections array)
            section_id: Existing section ID (use this OR sections array OR section_title)  
            task_contents: Task contents for single section creation (use with section_title or section_id)
                          Example: ["Fix login issue", "Update error handling"]
            tasks: Compatibility alias used by some model function-calls. Can be a JSON string or list.
            section_tasks: Optional mapping of section IDs to task IDs for compatibility payloads.
            force_replan: Set true only when intentionally replacing/expanding an existing unstarted plan.
        
        Returns:
            ToolResult: Success with JSON string of created task structure, or failure with error message.
        """
        try:
            def _parse_json_like(value: Any) -> Any:
                if not isinstance(value, str):
                    return value
                stripped = value.strip()
                if not stripped:
                    return None
                try:
                    return json.loads(stripped)
                except json.JSONDecodeError:
                    return value

            if kwargs:
                logger.info("create_tasks received extra compatibility args: %s", sorted(kwargs.keys()))

            sections = _parse_json_like(sections)
            tasks = _parse_json_like(tasks)
            section_tasks = _parse_json_like(section_tasks)
            parsed_task_contents = _parse_json_like(task_contents)
            if isinstance(parsed_task_contents, list):
                task_contents = [str(item).strip() for item in parsed_task_contents if str(item).strip()]
            elif isinstance(parsed_task_contents, str):
                task_contents = [parsed_task_contents.strip()] if parsed_task_contents.strip() else None

            existing_sections, existing_tasks = await self._load_data()
    
            section_map = {s.id: s for s in existing_sections}
            title_map = {s.title.lower(): s for s in existing_sections}

            def _task_status_str(task: Task) -> str:
                status_value = task.status
                if isinstance(status_value, TaskStatus):
                    return status_value.value
                return str(status_value).strip().lower()

            def _next_pending_task_payload() -> Optional[Dict[str, str]]:
                for task in existing_tasks:
                    if _task_status_str(task) == TaskStatus.PENDING.value:
                        section = section_map.get(task.section_id)
                        return {
                            "id": str(task.id),
                            "content": str(task.content),
                            "section_id": str(task.section_id),
                            "section_title": str(section.title) if section else "",
                        }
                return None

            completed_tasks_count = sum(
                1 for task in existing_tasks if _task_status_str(task) == TaskStatus.COMPLETED.value
            )
            has_unstarted_plan = bool(existing_tasks) and completed_tasks_count == 0
            is_bulk_replan_attempt = isinstance(sections, list) and len(sections) > 1

            if has_unstarted_plan and is_bulk_replan_attempt and not force_replan:
                response_data = self._format_response(existing_sections, existing_tasks)
                response_data["task_creation"] = {
                    "created_sections": 0,
                    "created_tasks": 0,
                    "skipped_duplicate_tasks": 0,
                    "plan_reused": True,
                    "blocked_replan": True,
                    "next_step_hint": (
                        "Task list already exists and has not started. "
                        "Use view_tasks to inspect the next pending task, execute it, "
                        "then call update_tasks instead of creating a new bulk plan."
                    ),
                }
                next_pending_task = _next_pending_task_payload()
                if next_pending_task:
                    response_data["task_creation"]["next_pending_task"] = next_pending_task

                return ToolResult(success=True, output=json.dumps(response_data, indent=2))

            existing_task_keys = {
                (str(task.section_id), str(task.content).strip().lower())
                for task in existing_tasks
                if str(task.content).strip()
            }
        
            created_tasks = 0
            created_sections = 0
            skipped_duplicate_tasks = 0

            if isinstance(section_tasks, dict) and isinstance(tasks, list):
                section_name_by_id: Dict[str, str] = {}
                if isinstance(sections, list):
                    for section_item in sections:
                        if not isinstance(section_item, dict):
                            continue
                        section_key = str(
                            section_item.get("id")
                            or section_item.get("section_id")
                            or ""
                        ).strip()
                        section_title_value = str(
                            section_item.get("title")
                            or section_item.get("name")
                            or section_item.get("section_name")
                            or section_key
                        ).strip()
                        if section_key and section_title_value:
                            section_name_by_id[section_key] = section_title_value

                task_content_by_id: Dict[str, str] = {}
                for task_item in tasks:
                    if not isinstance(task_item, dict):
                        continue
                    task_key = str(task_item.get("id") or task_item.get("task_id") or "").strip()
                    task_content = str(
                        task_item.get("content")
                        or task_item.get("title")
                        or task_item.get("task")
                        or task_item.get("description")
                        or ""
                    ).strip()
                    if task_key and task_content:
                        task_content_by_id[task_key] = task_content

                normalized_sections_from_mapping: List[Dict[str, Any]] = []
                for raw_section_id, raw_task_ids in section_tasks.items():
                    section_id_value = str(raw_section_id).strip()
                    section_title_value = section_name_by_id.get(section_id_value) or section_id_value or "Tasks"
                    resolved_task_ids = self._normalize_id_list(raw_task_ids)
                    resolved_task_contents = [
                        task_content_by_id[task_id]
                        for task_id in resolved_task_ids
                        if task_id in task_content_by_id
                    ]
                    if resolved_task_contents:
                        normalized_sections_from_mapping.append(
                            {"title": section_title_value, "tasks": resolved_task_contents}
                        )

                if normalized_sections_from_mapping:
                    sections = normalized_sections_from_mapping

            if not sections and not task_contents and tasks is not None:
                normalized_tasks_input: Any = tasks

                if isinstance(normalized_tasks_input, dict):
                    dict_sections = normalized_tasks_input.get("sections")
                    if isinstance(dict_sections, list):
                        sections = dict_sections
                    else:
                        dict_tasks = normalized_tasks_input.get("tasks")
                        if isinstance(dict_tasks, str):
                            try:
                                normalized_tasks_input = json.loads(dict_tasks)
                            except json.JSONDecodeError:
                                normalized_tasks_input = [dict_tasks]
                        elif isinstance(dict_tasks, list):
                            normalized_tasks_input = dict_tasks

                if isinstance(normalized_tasks_input, list) and not sections:
                    if all(isinstance(item, str) for item in normalized_tasks_input):
                        task_contents = [
                            str(item).strip()
                            for item in normalized_tasks_input
                            if str(item).strip()
                        ]
                    elif all(isinstance(item, dict) for item in normalized_tasks_input):
                        has_section_container_shape = any(
                            isinstance(item.get("tasks"), list) for item in normalized_tasks_input
                        )
                        if has_section_container_shape:
                            normalized_sections: List[Dict[str, Any]] = []
                            for section_item in normalized_tasks_input:
                                if not isinstance(section_item, dict):
                                    continue

                                section_title_value = str(
                                    section_item.get("title")
                                    or section_item.get("section_title")
                                    or section_item.get("section_name")
                                    or section_item.get("name")
                                    or section_title
                                    or "Tasks"
                                ).strip()
                                if not section_title_value:
                                    section_title_value = "Tasks"

                                raw_section_tasks = section_item.get("tasks")
                                if not isinstance(raw_section_tasks, list):
                                    continue

                                normalized_task_contents: List[str] = []
                                for raw_task in raw_section_tasks:
                                    if isinstance(raw_task, dict):
                                        content_value = str(
                                            raw_task.get("content")
                                            or raw_task.get("task")
                                            or raw_task.get("title")
                                            or ""
                                        ).strip()
                                    else:
                                        content_value = str(raw_task).strip()
                                    if content_value:
                                        normalized_task_contents.append(content_value)

                                if normalized_task_contents:
                                    normalized_sections.append(
                                        {
                                            "title": section_title_value,
                                            "tasks": normalized_task_contents,
                                        }
                                    )

                            sections = normalized_sections
                        else:
                            section_task_groups: Dict[str, List[str]] = {}
                            for task_item in normalized_tasks_input:
                                content_value = str(
                                    task_item.get("content")
                                    or task_item.get("title")
                                    or task_item.get("task")
                                    or task_item.get("description")
                                    or ""
                                ).strip()
                                if not content_value:
                                    continue

                                section_id_value = str(task_item.get("section_id", "")).strip()
                                section_title_value = ""
                                if section_id_value and section_id_value in section_map:
                                    section_title_value = str(section_map[section_id_value].title).strip()
                                if not section_title_value:
                                    section_title_value = str(
                                        task_item.get("section_title")
                                        or task_item.get("section")
                                        or task_item.get("section_name")
                                        or section_title
                                        or "Tasks"
                                    ).strip()
                                if not section_title_value:
                                    section_title_value = "Tasks"

                                section_task_groups.setdefault(section_title_value, []).append(content_value)

                            sections = [
                                {"title": title, "tasks": grouped_tasks}
                                for title, grouped_tasks in section_task_groups.items()
                                if grouped_tasks
                            ]

            def _add_task_if_needed(target_section: Section, raw_content: Any) -> None:
                nonlocal created_tasks, skipped_duplicate_tasks
                content = str(raw_content).strip()
                if not content:
                    return

                key = (str(target_section.id), content.lower())
                if key in existing_task_keys:
                    skipped_duplicate_tasks += 1
                    return

                existing_tasks.append(Task(content=content, section_id=target_section.id))
                existing_task_keys.add(key)
                created_tasks += 1
      
            if sections:
                # Batch creation across multiple sections
                for section_data in sections:
                    if not isinstance(section_data, dict):
                        continue

                    section_title_input = str(
                        section_data.get("title")
                        or section_data.get("section_title")
                        or section_data.get("section_name")
                        or section_data.get("name")
                        or ""
                    ).strip()
                    if not section_title_input:
                        continue

                    task_list = section_data.get("tasks", [])
                    if not isinstance(task_list, list):
                        continue
                    
                    # Find or create section
                    title_lower = section_title_input.lower()
                    if title_lower in title_map:
                        target_section = title_map[title_lower]
                    else:
                        target_section = Section(title=section_title_input)
                        existing_sections.append(target_section)
                        section_map[target_section.id] = target_section
                        title_map[title_lower] = target_section
                        created_sections += 1
                    
                    # Create tasks in this section
                    for task_content in task_list:
                        normalized_task_content = task_content
                        if isinstance(task_content, dict):
                            normalized_task_content = (
                                task_content.get("content")
                                or task_content.get("title")
                                or task_content.get("task")
                                or task_content.get("description")
                            )
                        _add_task_if_needed(target_section, normalized_task_content)
                        
            else:
                # 单个section创建 - 需要显式指定section
                if not task_contents:
                    if existing_tasks:
                        response_data = self._format_response(existing_sections, existing_tasks)
                        response_data["task_creation"] = {
                            "created_sections": 0,
                            "created_tasks": 0,
                            "skipped_duplicate_tasks": 0,
                            "plan_reused": True,
                            "blocked_replan": True,
                            "next_step_hint": (
                                "Task list already exists. Use view_tasks to inspect pending tasks, "
                                "then execute and call update_tasks. Do not call create_tasks with empty payload."
                            ),
                        }
                        next_pending_task = _next_pending_task_payload()
                        if next_pending_task:
                            response_data["task_creation"]["next_pending_task"] = next_pending_task
                        return ToolResult(success=True, output=json.dumps(response_data, indent=2))

                    return ToolResult(success=False, output="必须提供 'sections' 数组或 'task_contents' 与 section 信息")
                
                # 如果没有指定section信息，创建默认section
                if not section_id and not section_title:
                    section_title = "Tasks"  # 设置默认section标题
                
                target_section = None
                
                if section_id:
                    # Use existing section ID
                    if section_id not in section_map:
                        return ToolResult(success=False, output=f"Section ID '{section_id}' not found")
                    target_section = section_map[section_id]
                    
                elif section_title:
                    # Find or create section by title
                    title_lower = section_title.lower()
                    if title_lower in title_map:
                        target_section = title_map[title_lower]
                    else:
                        target_section = Section(title=section_title)
                        existing_sections.append(target_section)
                        section_map[target_section.id] = target_section
                        title_map[title_lower] = target_section
                        created_sections += 1
                
                # Create tasks
                for content in task_contents:
                    _add_task_if_needed(target_section, content)
            
            await self._save_data(existing_sections, existing_tasks)
            
            response_data = self._format_response(existing_sections, existing_tasks)
            response_data["task_creation"] = {
                "created_sections": created_sections,
                "created_tasks": created_tasks,
                "skipped_duplicate_tasks": skipped_duplicate_tasks,
                "plan_reused": created_tasks == 0 and skipped_duplicate_tasks > 0,
            }
            if created_tasks == 0 and skipped_duplicate_tasks > 0:
                response_data["task_creation"]["next_step_hint"] = (
                    "Task list already exists. Use view_tasks to read pending tasks, "
                    "then execute and update_tasks instead of calling create_tasks again."
                )
            
            return ToolResult(success=True, output=json.dumps(response_data, indent=2))
            
        except Exception as e:
            logger.error(f"Error creating tasks: {e}")
            return ToolResult(success=False, output=f"Error creating tasks: {str(e)}")
        
    async def view_tasks(self) -> ToolResult:
        """View all current tasks and sections for project management.

        This function retrieves and displays the complete task structure organized by sections,
        helping agents track progress, identify next actions, and review completed work.
        Essential for sequential workflow execution - always check current state before proceeding.
        
        Usage Example:
            {
                "name": "view_tasks",
                "parameters": {}
            }
                
        Returns:
            ToolResult: Success with JSON string of complete task structure, or failure with error message.
        """
        try:
            sections, tasks = await self._load_data()
            
            response_data = self._format_response(sections, tasks)
            
            return ToolResult(success=True, output=json.dumps(response_data, indent=2))
            
        except Exception as e:
            logger.error(f"Error viewing tasks: {e}")
            return ToolResult(success=False, output=f"Error viewing tasks: {str(e)}")

    async def update_tasks(self, task_ids: Optional[str] = None, content: Optional[str] = None,
                          status: Optional[str] = None, section_id: Optional[str] = None) -> ToolResult:
        """Update one or more tasks for project management.

        This function updates task properties such as status, content, or section assignment.
        EFFICIENT BATCHING: Consider batching multiple completed tasks into a single update call
        rather than making multiple consecutive update calls for better performance.
        
        Usage Examples:
            # Update single task (when only one task is completed):
            {
                "name": "update_tasks",
                "parameters": {
                    "task_ids": "task-uuid-here",
                    "status": "completed"
                }
            }
            
            # Update multiple tasks (EFFICIENT: batch multiple completed tasks):
            {
                "name": "update_tasks",
                "parameters": {
                    "task_ids": ["task-id-1", "task-id-2", "task-id-3"],
                    "status": "completed"
                }
            }
        
        Args:
            task_ids: Task ID (string) or array of task IDs to update. 
                     Example: "task-uuid-here" or ["task-id-1", "task-id-2", "task-id-3"]
            content: New content for the task(s) (optional)
            status: New status for the task(s) (optional). Valid values: "pending", "completed", "cancelled"
            section_id: Section ID to move task(s) to (optional)
        
        Returns:
            ToolResult: Success with JSON string of updated task structure, or failure with error message.
        """
        try:
            target_task_ids = self._normalize_id_list(task_ids)
            sections, tasks = await self._load_data()
            if not target_task_ids:
                status_value = str(status).strip().lower() if status is not None else None
                if status_value == TaskStatus.COMPLETED.value:
                    for task in tasks:
                        current_status = (
                            task.status.value
                            if isinstance(task.status, TaskStatus)
                            else str(task.status).strip().lower()
                        )
                        if current_status == TaskStatus.PENDING.value:
                            target_task_ids = [task.id]
                            logger.warning(
                                "update_tasks received empty task_ids; falling back to next pending task '%s'",
                                task.id,
                            )
                            break

            if not target_task_ids:
                return ToolResult(success=False, output="Must provide at least one task ID to update")

            section_map = {s.id: s for s in sections}
            task_map = {t.id: t for t in tasks}

            target_task_ids, unresolved_task_ids = self._resolve_task_ids(target_task_ids, tasks, status)
            
            # 验证所有 task IDs 是否存在
            missing_tasks = unresolved_task_ids or [tid for tid in target_task_ids if tid not in task_map]
            if missing_tasks:
                return ToolResult(success=False, output=f"Task IDs not found: {missing_tasks}")
            
            # 验证 section ID 是否提供
            if section_id and section_id not in section_map:
                return ToolResult(success=False, output=f"Section ID '{section_id}' not found")
            
            # 应用更新
            updated_count = 0
            for tid in target_task_ids:
                try:
                    task = task_map[tid]
                    logger.debug(f"Updating task {tid}, current type: {type(task)}")
                    
                    if content is not None:
                        task.content = content
                        logger.debug(f"Updated content for task {tid}")
                        
                    if status is not None:
                        # 添加调试日志和更安全的 status 转换
                        logger.debug(f"Updating status for task {tid}, status type: {type(status)}, value: {repr(status)}")
                        try:
                            # 确保 status 是一个字符串 - 处理潜在的 coroutine 对象
                            if asyncio.iscoroutine(status):
                                logger.error(f"ERROR: status parameter is a coroutine object: {status}")
                                status_str = "pending"  # Default fallback
                            else:
                                status_str = str(status) if status is not None else "pending"
                            
                            # 创建新的 status enum
                            new_status = TaskStatus(status_str)
                            
                            # 额外安全检查 before assignment
                            if asyncio.iscoroutine(new_status):
                                logger.error(f"ERROR: new_status is still a coroutine: {new_status}")
                                new_status = TaskStatus.PENDING
                            
                            # Use Pydantic's validation by creating a new Task object instead of direct assignment
                            # This ensures validation is triggered
                            try:
                                updated_task = Task(
                                    id=task.id,
                                    content=task.content,
                                    status=new_status,
                                    section_id=task.section_id
                                )
                                # 复制验证后的值 back
                                task.status = updated_task.status
                            except Exception as validation_error:
                                logger.error(f"Pydantic validation failed for task {tid}: {validation_error}")
                                task.status = TaskStatus.PENDING  # Safe fallback
                            
                            logger.debug(f"Successfully updated status for task {tid} to {repr(task.status)}")
                        except Exception as status_error:
                            logger.error(f"Error updating status for task {tid}: {status_error}")
                            raise
                            
                    if section_id is not None:
                        task.section_id = section_id
                        logger.debug(f"Updated section_id for task {tid}")
                    
                    updated_count += 1
                    
                except Exception as task_error:
                    logger.error(f"Error processing task {tid}: {task_error}")
                    logger.error(f"Task object type: {type(task_map.get(tid))}")
                    raise
            
            await self._save_data(sections, tasks)
            
            response_data = self._format_response(sections, tasks)
            
            return ToolResult(success=True, output=json.dumps(response_data, indent=2))
            
        except Exception as e:
            logger.error(f"Error updating tasks: {e}")
            return ToolResult(success=False, output=f"Error updating tasks: {str(e)}")
    
    async def delete_tasks(self, task_ids: Optional[str] = None, section_ids: Optional[str] = None, confirm: bool = False) -> ToolResult:
        """Delete one or more tasks and/or sections for project management.

        This function removes tasks by their IDs and/or sections by their IDs. 
        When deleting sections, all tasks within those sections are also deleted.
        Section deletion requires explicit confirmation for safety.
        
        Usage Examples:
            # Delete single task:
            {
                "name": "delete_tasks",
                "parameters": {
                    "task_ids": "task-uuid-here"
                }
            }
            
            # Delete multiple tasks:
            {
                "name": "delete_tasks",
                "parameters": {
                    "task_ids": ["task-id-1", "task-id-2"]
                }
            }
            
            # Delete single section (and all its tasks):
            {
                "name": "delete_tasks",
                "parameters": {
                    "section_ids": "section-uuid-here",
                    "confirm": true
                }
            }
            
            # Delete multiple sections (and all their tasks):
            {
                "name": "delete_tasks",
                "parameters": {
                    "section_ids": ["section-id-1", "section-id-2"],
                    "confirm": true
                }
            }
            
            # Delete both tasks and sections:
            {
                "name": "delete_tasks",
                "parameters": {
                    "task_ids": ["task-id-1", "task-id-2"],
                    "section_ids": ["section-id-1"],
                    "confirm": true
                }
            }
        
        Args:
            task_ids: Task ID (string) or array of task IDs to delete (optional). 
                     Example: "task-uuid-here" or ["task-id-1", "task-id-2"]
            section_ids: Section ID (string) or array of section IDs to delete (optional).
                        Example: "section-uuid-here" or ["section-id-1", "section-id-2"]  
            confirm: Must be true to confirm deletion of sections (required when deleting sections)
        
        Returns:
            ToolResult: Success with JSON string of remaining task structure, or failure with error message.
        """
        try:
            target_task_ids = self._normalize_id_list(task_ids)
            target_section_ids = self._normalize_id_list(section_ids)

            # Validate that at least one of task_ids or section_ids is provided
            if not target_task_ids and not target_section_ids:
                return ToolResult(success=False, output="Must provide either task_ids or section_ids")
            
            # Validate confirm parameter for section deletion
            if target_section_ids and not confirm:
                return ToolResult(success=False, output="Must set confirm=true to delete sections")
            
            sections, tasks = await self._load_data()
            section_map = {s.id: s for s in sections}
            task_map = {t.id: t for t in tasks}
            
            # Process task deletions
            deleted_tasks = 0
            remaining_tasks = tasks.copy()
            if target_task_ids:
                # Validate all task IDs exist
                missing_tasks = [tid for tid in target_task_ids if tid not in task_map]
                if missing_tasks:
                    return ToolResult(success=False, output=f"Task IDs not found: {missing_tasks}")
                
                # Remove tasks
                task_id_set = set(target_task_ids)
                remaining_tasks = [task for task in tasks if task.id not in task_id_set]
                deleted_tasks = len(tasks) - len(remaining_tasks)
            
            # Process section deletions
            deleted_sections = 0
            remaining_sections = sections.copy()
            if target_section_ids:
                # Validate all section IDs exist
                missing_sections = [sid for sid in target_section_ids if sid not in section_map]
                if missing_sections:
                    return ToolResult(success=False, output=f"Section IDs not found: {missing_sections}")
                
                # Remove sections and their tasks
                section_id_set = set(target_section_ids)
                remaining_sections = [s for s in sections if s.id not in section_id_set]
                remaining_tasks = [t for t in remaining_tasks if t.section_id not in section_id_set]
                deleted_sections = len(sections) - len(remaining_sections)
            
            await self._save_data(remaining_sections, remaining_tasks)
            
            response_data = self._format_response(remaining_sections, remaining_tasks)
            
            return ToolResult(success=True, output=json.dumps(response_data, indent=2))
            
        except Exception as e:
            logger.error(f"Error deleting tasks/sections: {e}")
            return ToolResult(success=False, output=f"Error deleting tasks/sections: {str(e)}")

    async def clear_all(self, confirm: bool) -> ToolResult:
        """Clear all tasks and sections for project management.

        This function removes all tasks and sections from the project, creating a completely clean slate.
        This is a destructive operation that requires explicit confirmation for safety.
        
        Usage Example:
            {
                "name": "clear_all",
                "parameters": {
                    "confirm": true
                }
            }
        
        Args:
            confirm: Must be true to confirm clearing everything
        
        Returns:
            ToolResult: Success with JSON string showing empty task structure, or failure with error message.
        """
        try:
            if not confirm:
                return ToolResult(success=False, output=" Must set confirm=true to clear all data")
            
            # Create completely empty state - no default section
            sections = []
            tasks = []
            
            await self._save_data(sections, tasks)
            
            response_data = self._format_response(sections, tasks)
            
            return ToolResult(success=True, output=json.dumps(response_data, indent=2))
            
        except Exception as e:
            logger.error(f"Error clearing all data: {e}")
            return ToolResult(success=False, output=f"Error clearing all data: {str(e)}")
   
if __name__ == "__main__":
    pass
