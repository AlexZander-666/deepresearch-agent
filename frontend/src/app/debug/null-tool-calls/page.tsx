"use client";

import React from "react";
import { useToolCalls } from "@/app/(dashboard)/projects/[projectId]/thread/_hooks/useToolCalls";
import { ToolCallSidePanel } from "@/components/thread/tool-call-side-panel";
import { UnifiedMessage } from "@/components/thread/types";

export default function NullToolCallsDebugPage() {
  const [leftSidebarOpen, setLeftSidebarOpen] = React.useState(false);

  const messages = React.useMemo<UnifiedMessage[]>(
    () => [
      {
        message_id: "user-1",
        thread_id: "thread-1",
        type: "user",
        role: "user",
        is_llm_message: false,
        content: "请深度分析阿里巴巴财务信息",
        metadata: "{}",
        created_at: "2026-02-28T10:00:00.000Z",
        updated_at: "2026-02-28T10:00:00.000Z",
      },
      {
        message_id: "assistant-1",
        thread_id: "thread-1",
        type: "assistant",
        role: "assistant",
        is_llm_message: true,
        content:
          '{"role":"assistant","content":"我将帮您分析阿里巴巴财务信息，请确认范围。","tool_calls":null}',
        metadata: "{}",
        created_at: "2026-02-28T10:00:01.000Z",
        updated_at: "2026-02-28T10:00:01.000Z",
      },
      {
        message_id: "user-2",
        thread_id: "thread-1",
        type: "user",
        role: "user",
        is_llm_message: false,
        content: "重点关注现金流和利润率",
        metadata: "{}",
        created_at: "2026-02-28T10:00:02.000Z",
        updated_at: "2026-02-28T10:00:02.000Z",
      },
      {
        message_id: "assistant-2",
        thread_id: "thread-1",
        type: "assistant",
        role: "assistant",
        is_llm_message: true,
        content:
          '{"role":"assistant","content":"好的，我将继续。\\n```json\\n{\\n  \"action\": \"view_tasks\"\\n}\\n```","tool_calls":null}',
        metadata: "{}",
        created_at: "2026-02-28T10:00:03.000Z",
        updated_at: "2026-02-28T10:00:03.000Z",
      },
    ],
    [],
  );

  const {
    toolCalls,
    currentToolIndex,
    isSidePanelOpen,
    setIsSidePanelOpen,
    handleSidePanelNavigate,
  } = useToolCalls(messages, setLeftSidebarOpen, "idle");

  return (
    <div className="h-screen">
      <div className="p-4 bg-gray-100 dark:bg-gray-900">
        <h1 className="text-xl font-bold mb-2">Null Tool Calls Regression Test</h1>
        <p className="text-sm text-muted-foreground">leftSidebarOpen: {String(leftSidebarOpen)}</p>
        <p className="text-sm text-muted-foreground">toolCalls: {toolCalls.length}</p>
        <button
          onClick={() => setIsSidePanelOpen(true)}
          className="mt-3 px-4 py-2 rounded bg-blue-600 text-white"
        >
          Open Tool Panel
        </button>
      </div>

      <ToolCallSidePanel
        isOpen={isSidePanelOpen}
        onClose={() => setIsSidePanelOpen(false)}
        toolCalls={toolCalls}
        currentIndex={currentToolIndex}
        onNavigate={handleSidePanelNavigate}
        messages={messages as any}
        agentStatus="idle"
      />
    </div>
  );
}
