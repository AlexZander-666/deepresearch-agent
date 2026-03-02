'use client';

import React from 'react';
import { ToolCallSidePanel, type ToolCallInput } from '@/components/thread/tool-call-side-panel';

export default function AlexManusPrivacyDebugPage() {
  const [open, setOpen] = React.useState(true);

  const toolCalls = React.useMemo<ToolCallInput[]>(
    () => [
      {
        assistantCall: {
          name: 'browser_navigate_to',
          timestamp: '2026-03-02T00:00:00.000Z',
          content: JSON.stringify({
            role: 'assistant',
            content: '',
            tool_calls: [
              {
                id: 'call_1',
                type: 'function',
                function: {
                  name: 'browser_navigate_to',
                  arguments: { url: 'https://example.com' },
                },
              },
            ],
          }),
          toolCallId: 'call_1',
          toolIndex: 0,
          statusType: 'tool_completed',
        },
        toolResult: {
          timestamp: '2026-03-02T00:00:01.000Z',
          isSuccess: true,
          content: JSON.stringify({
            result: {
              image_url:
                'https://upload.wikimedia.org/wikipedia/commons/3/3f/Fronalpstock_big.jpg',
            },
            tool_name: 'browser_navigate_to',
          }),
        },
      },
    ],
    [],
  );

  return (
    <div className="h-screen">
      <div className="p-4 bg-gray-100 dark:bg-gray-900">
        <h1 className="text-xl font-bold">AlexManus Privacy Mode Debug</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Browser tool data intentionally includes screenshot URL; UI should still hide sandbox visuals.
        </p>
        <button
          onClick={() => setOpen(true)}
          className="mt-3 rounded bg-blue-600 px-4 py-2 text-white"
        >
          Open Tool Panel
        </button>
      </div>

      <ToolCallSidePanel
        isOpen={open}
        onClose={() => setOpen(false)}
        toolCalls={toolCalls}
        currentIndex={0}
        onNavigate={() => {}}
        agentStatus="idle"
        agentName="AlexManus"
      />
    </div>
  );
}
