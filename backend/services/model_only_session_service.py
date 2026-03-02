"""
自定义ADK数据库会话服务 - 只存储模型响应，过滤用户消息
"""

import logging
import copy
from typing import Any, Optional
from google.adk.sessions.database_session_service import DatabaseSessionService # type: ignore
from google.adk.sessions.session import Session # type: ignore
from google.adk.events.event import Event # type: ignore

logger = logging.getLogger(__name__)

class ModelOnlyDBSessionService(DatabaseSessionService):
    """
    继承ADK的DatabaseSessionService，只存储模型响应事件
    过滤掉用户消息事件，避免与手动插入的用户消息重复
    """
    
    def __init__(self, db_url: str, **kwargs: Any):
        """初始化服务"""
        super().__init__(db_url, **kwargs)
        logger.info("ModelOnlyDBSessionService initialized - will filter user events")

    @staticmethod
    def _clone_event(event: Event) -> Event:
        """Create a deep copy of an ADK event without mutating the live stream object."""
        if hasattr(event, "model_copy"):
            return event.model_copy(deep=True)
        return copy.deepcopy(event)

    @staticmethod
    def _sanitize_event_parts(event: Event) -> Optional[Event]:
        """
        Strip function_call / function_response parts from persisted model events.

        DashScope/OpenAI-compatible endpoints may reject history that contains
        dangling tool_calls without matching tool responses. ADK may persist
        intermediate tool-call events, so we keep only plain text parts.
        """
        content = getattr(event, "content", None)
        parts = getattr(content, "parts", None)
        if not parts:
            return event

        safe_parts = []
        removed_part_count = 0
        for part in parts:
            if getattr(part, "function_call", None) is not None:
                removed_part_count += 1
                continue
            if getattr(part, "function_response", None) is not None:
                removed_part_count += 1
                continue
            safe_parts.append(part)

        if removed_part_count == 0:
            return event

        if not safe_parts:
            return None

        content.parts = safe_parts
        event.content = content
        return event

    async def get_session(
        self,
        app_name: str,
        user_id: str,
        session_id: str,
        config: Optional[dict[str, Any]] = None,
    ) -> Optional[Session]:
        """
        Return a sanitized session so malformed historical tool-call events
        do not poison subsequent model requests.
        """
        session = await super().get_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
            config=config,
        )
        if not session or not getattr(session, "events", None):
            return session

        sanitized_events = []
        removed_event_count = 0
        for event in session.events:
            sanitized_event = self._sanitize_event_parts(event)
            if sanitized_event is None:
                removed_event_count += 1
                continue
            sanitized_events.append(sanitized_event)

        if removed_event_count > 0:
            logger.warning(
                f"Sanitized ADK session {session_id}: removed {removed_event_count} event(s) with only tool call parts"
            )

        session.events = sanitized_events
        return session
    
    async def append_event(self, session: Session, event: Event) -> Event:
        """
        重写append_event方法，过滤用户事件
        只存储模型/助手的响应，避免用户消息重复
        """
        # 过滤用户事件，不存储到数据库，因为我们已经手动存储了
        if getattr(event, "author", None) == "user":
            logger.debug(f" Filtering user event: {event.id}")
            return event  # 直接返回，不调用父类存储方法

        # Never mutate the live event object used by the streaming pipeline.
        sanitized_event = self._sanitize_event_parts(self._clone_event(event))
        if sanitized_event is None:
            logger.info(f"Skipping model event with only tool-call parts: {getattr(event, 'id', 'unknown')}")
            return event

        # 存储非用户事件（模型响应等）
        logger.debug(f"Storing non-user event: {event.id} (author: {getattr(event, 'author', 'unknown')})")
        return await super().append_event(session, sanitized_event)
