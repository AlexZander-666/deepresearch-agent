import React, { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { ToolCallInput } from '@/components/thread/tool-call-side-panel';
import {
  UnifiedMessage,
  ParsedMetadata,
  StreamingToolCall,
  AgentStatus,
} from '../_types';
import { safeJsonParse } from '@/components/thread/utils';
import { ParsedContent } from '@/components/thread/types';
import { extractToolName } from '@/components/thread/tool-views/xml-parser';
import { useIsMobile } from '@/hooks/use-mobile';
import {
  hasExplicitNullToolCalls,
  parseAssistantToolCallInfo,
} from './tool-call-parsing';
import {
  sortToolCallsByExecutionOrder,
  upsertStreamingToolCall,
} from './tool-call-ordering';

interface UseToolCallsReturn {
  toolCalls: ToolCallInput[];
  setToolCalls: React.Dispatch<React.SetStateAction<ToolCallInput[]>>;
  currentToolIndex: number;
  setCurrentToolIndex: React.Dispatch<React.SetStateAction<number>>;
  isSidePanelOpen: boolean;
  setIsSidePanelOpen: React.Dispatch<React.SetStateAction<boolean>>;
  autoOpenedPanel: boolean;
  setAutoOpenedPanel: React.Dispatch<React.SetStateAction<boolean>>;
  externalNavIndex: number | undefined;
  setExternalNavIndex: React.Dispatch<React.SetStateAction<number | undefined>>;
  handleToolClick: (
    clickedAssistantMessageId: string | null,
    clickedToolName: string,
  ) => void;
  handleStreamingToolCall: (toolCall: StreamingToolCall | null) => void;
  toggleSidePanel: () => void;
  handleSidePanelNavigate: (newIndex: number) => void;
  userClosedPanelRef: React.MutableRefObject<boolean>;
}

function parseToolContent(content: unknown): {
  toolName: string;
  result: unknown;
} | null {
  try {
    const parsed = typeof content === 'string' ? safeJsonParse(content, content) : content;
    if (!parsed || typeof parsed !== 'object') {
      return null;
    }

    if ('tool_name' in parsed || 'xml_tag_name' in parsed) {
      return {
        toolName: ((parsed as any).tool_name || (parsed as any).xml_tag_name || 'unknown') as string,
        result: (parsed as any).result,
      };
    }

    if ('content' in parsed && typeof (parsed as any).content === 'object') {
      const inner = (parsed as any).content;
      if ('tool_name' in inner || 'xml_tag_name' in inner) {
        return {
          toolName: (inner.tool_name || inner.xml_tag_name || 'unknown') as string,
          result: inner.result,
        };
      }
    }
  } catch {
    return null;
  }

  return null;
}

const normalizeToolArguments = (argumentsValue: unknown): string => {
  if (argumentsValue === null || argumentsValue === undefined) {
    return '';
  }
  if (typeof argumentsValue === 'string') {
    return argumentsValue;
  }
  try {
    return JSON.stringify(argumentsValue);
  } catch {
    return String(argumentsValue);
  }
};

const findMatchingHistoricalItem = (
  streamingItem: ToolCallInput,
  completedItems: ToolCallInput[],
): ToolCallInput | undefined => {
  const streamingToolCallId = streamingItem.assistantCall.toolCallId;
  if (streamingToolCallId) {
    const byToolCallId = completedItems.find(
      (item) => item.assistantCall.toolCallId === streamingToolCallId,
    );
    if (byToolCallId) {
      return byToolCallId;
    }
  }

  const streamingToolIndex = streamingItem.assistantCall.toolIndex;
  if (streamingToolIndex !== undefined) {
    const byToolIndex = completedItems.find(
      (item) => item.assistantCall.toolIndex === streamingToolIndex,
    );
    if (byToolIndex) {
      return byToolIndex;
    }
  }

  return completedItems.find(
    (item) =>
      item.assistantCall.name === streamingItem.assistantCall.name &&
      item.assistantCall.content === streamingItem.assistantCall.content,
  );
};

export function useToolCalls(
  messages: UnifiedMessage[],
  setLeftSidebarOpen: (open: boolean) => void,
  agentStatus?: AgentStatus,
): UseToolCallsReturn {
  const [toolCalls, setToolCalls] = useState<ToolCallInput[]>([]);
  const [currentToolIndex, setCurrentToolIndex] = useState<number>(0);
  const [isSidePanelOpen, setIsSidePanelOpen] = useState(false);
  const [autoOpenedPanel, setAutoOpenedPanel] = useState(false);
  const [externalNavIndex, setExternalNavIndex] = useState<number | undefined>(undefined);
  const userClosedPanelRef = useRef(false);
  const userNavigatedRef = useRef(false);
  const isMobile = useIsMobile();

  const assistantMessageToToolIndex = useRef<Map<string, number>>(new Map());

  const toggleSidePanel = useCallback(() => {
    setIsSidePanelOpen((prev) => {
      const next = !prev;
      if (!next) {
        userClosedPanelRef.current = true;
      } else {
        setLeftSidebarOpen(false);
      }
      return next;
    });
  }, [setLeftSidebarOpen]);

  const handleSidePanelNavigate = useCallback((newIndex: number) => {
    setCurrentToolIndex(newIndex);
    userNavigatedRef.current = true;
  }, []);

  useEffect(() => {
    const historicalToolPairs: ToolCallInput[] = [];
    const messageIdToIndex = new Map<string, number>();
    const assistantMessages = messages.filter(
      (m) => m.type === 'assistant' && m.message_id,
    );

    assistantMessages.forEach((assistantMsg) => {
      const resultMessage = messages.find((toolMsg) => {
        if (toolMsg.type !== 'tool' || !toolMsg.metadata || !assistantMsg.message_id) {
          return false;
        }
        const metadata = safeJsonParse<ParsedMetadata>(toolMsg.metadata, {});
        return metadata.assistant_message_id === assistantMsg.message_id;
      });

      const assistantToolCallInfo = parseAssistantToolCallInfo(assistantMsg.content);

      if (resultMessage) {
        let toolName = 'unknown';
        let isSuccess = true;

        const toolContentParsed = parseToolContent(resultMessage.content);
        if (toolContentParsed) {
          toolName = toolContentParsed.toolName.replace(/_/g, '-').toLowerCase();
          if (toolContentParsed.result && typeof toolContentParsed.result === 'object') {
            isSuccess = (toolContentParsed.result as any).success !== false;
          }
        } else {
          const assistantContent = (() => {
            const parsed = safeJsonParse<ParsedContent>(assistantMsg.content, {});
            return parsed.content || assistantMsg.content;
          })();

          const extractedToolName = extractToolName(assistantContent);
          if (extractedToolName) {
            toolName = extractedToolName;
          } else {
            const assistantContentParsed = safeJsonParse<{
              tool_calls?: Array<{ function?: { name?: string }; name?: string }>;
            }>(assistantMsg.content, {});
            if (assistantContentParsed.tool_calls?.length) {
              const firstToolCall = assistantContentParsed.tool_calls[0];
              const rawName = firstToolCall.function?.name || firstToolCall.name || 'unknown';
              toolName = rawName.replace(/_/g, '-').toLowerCase();
            }
          }

          const toolResultContent = (() => {
            const parsed = safeJsonParse<ParsedContent>(resultMessage.content, {});
            return parsed.content || resultMessage.content;
          })();

          if (typeof toolResultContent === 'string') {
            const toolResultMatch = toolResultContent.match(
              /ToolResult\s*\(\s*success\s*=\s*(True|False|true|false)/i,
            );
            if (toolResultMatch) {
              isSuccess = toolResultMatch[1].toLowerCase() === 'true';
            } else {
              const normalizedResult = toolResultContent.toLowerCase();
              isSuccess = !(
                normalizedResult.includes('failed') ||
                normalizedResult.includes('error') ||
                normalizedResult.includes('failure')
              );
            }
          }
        }

        const resultMetadata = safeJsonParse<ParsedMetadata>(resultMessage.metadata, {});
        const assistantMetadata = safeJsonParse<ParsedMetadata>(assistantMsg.metadata, {});
        const matchedToolCallId =
          typeof resultMetadata.tool_call_id === 'string'
            ? resultMetadata.tool_call_id
            : assistantToolCallInfo?.toolCallId;
        const matchedToolIndex =
          typeof assistantMetadata.tool_index === 'number'
            ? assistantMetadata.tool_index
            : undefined;

        historicalToolPairs.push({
          assistantCall: {
            name: toolName,
            content: assistantMsg.content,
            timestamp: assistantMsg.created_at,
            toolCallId: matchedToolCallId,
            toolIndex: matchedToolIndex,
            statusType: isSuccess ? 'tool_completed' : 'tool_failed',
          },
          toolResult: {
            content: resultMessage.content,
            isSuccess,
            timestamp: resultMessage.created_at,
          },
        });

        if (assistantMsg.message_id) {
          messageIdToIndex.set(assistantMsg.message_id, historicalToolPairs.length - 1);
        }
        return;
      }

      if (assistantToolCallInfo) {
        const assistantMetadata = safeJsonParse<ParsedMetadata>(assistantMsg.metadata, {});
        const pendingToolIndex =
          typeof assistantMetadata.tool_index === 'number'
            ? assistantMetadata.tool_index
            : undefined;

        historicalToolPairs.push({
          assistantCall: {
            name: assistantToolCallInfo.toolName,
            content: assistantMsg.content,
            timestamp: assistantMsg.created_at,
            toolCallId: assistantToolCallInfo.toolCallId,
            toolIndex: pendingToolIndex,
            statusType: 'tool_started',
          },
          toolResult: {
            content: 'STREAMING',
            isSuccess: true,
            timestamp: assistantMsg.created_at,
          },
        });

        if (assistantMsg.message_id) {
          messageIdToIndex.set(assistantMsg.message_id, historicalToolPairs.length - 1);
        }
        return;
      }

      if (hasExplicitNullToolCalls(assistantMsg.content)) {
        return;
      }
    });

    const statusMessages = messages.filter((m) => m.type === 'status');
    const existingKeys = new Set(
      historicalToolPairs.map((pair) => {
        if (pair.assistantCall.toolCallId) {
          return `id:${pair.assistantCall.toolCallId}`;
        }
        return `idx:${pair.assistantCall.toolIndex ?? 'na'}:${pair.assistantCall.name ?? 'unknown'}`;
      }),
    );

    statusMessages.forEach((statusMsg) => {
      const statusContent = safeJsonParse<ParsedContent>(statusMsg.content, {});
      const statusType = statusContent.status_type;
      if (
        statusType !== 'tool_started' &&
        statusType !== 'tool_completed' &&
        statusType !== 'tool_failed' &&
        statusType !== 'tool_error'
      ) {
        return;
      }

      const statusMetadata = safeJsonParse<ParsedMetadata>(statusMsg.metadata, {});
      const rawToolName =
        (statusContent.function_name as string | undefined) ||
        (statusContent.xml_tag_name as string | undefined) ||
        (statusContent.tool_name as string | undefined);
      if (!rawToolName) {
        return;
      }

      const toolName = rawToolName.replace(/_/g, '-').toLowerCase();
      const toolCallId =
        (statusContent.tool_call_id as string | undefined) ||
        ((statusMetadata as any).tool_call_id as string | undefined);
      const toolIndex =
        typeof statusContent.tool_index === 'number'
          ? statusContent.tool_index
          : typeof statusMetadata.tool_index === 'number'
            ? statusMetadata.tool_index
            : undefined;
      const toolKey = toolCallId ? `id:${toolCallId}` : `idx:${toolIndex ?? 'na'}:${toolName}`;
      if (existingKeys.has(toolKey)) {
        return;
      }
      existingKeys.add(toolKey);

      const isTerminal =
        statusType === 'tool_completed' ||
        statusType === 'tool_failed' ||
        statusType === 'tool_error';
      const isSuccess = statusType === 'tool_completed';

      historicalToolPairs.push({
        assistantCall: {
          name: toolName,
          content: (statusContent.message as string | undefined) || statusMsg.content,
          timestamp: statusMsg.created_at,
          toolCallId,
          toolIndex,
          statusType,
        },
        toolResult: {
          content: isTerminal ? statusMsg.content : 'STREAMING',
          isSuccess,
          timestamp: statusMsg.created_at,
        },
      });

      const linkedAssistantId =
        statusMetadata.assistant_message_id ||
        (statusContent.assistant_message_id as string | undefined);
      if (linkedAssistantId && !messageIdToIndex.has(linkedAssistantId)) {
        messageIdToIndex.set(linkedAssistantId, historicalToolPairs.length - 1);
      }
    });

    assistantMessageToToolIndex.current = messageIdToIndex;

    setToolCalls((prev) => {
      const streamingItems = prev.filter((item) => item.toolResult?.content === 'STREAMING');
      const remainingStreamingItems = streamingItems.filter(
        (streamingItem) =>
          !findMatchingHistoricalItem(streamingItem, historicalToolPairs),
      );

      const merged = sortToolCallsByExecutionOrder([
        ...historicalToolPairs,
        ...remainingStreamingItems,
      ]);

      if (prev.length === merged.length) {
        const changed = prev.some((prevItem, index) => {
          const nextItem = merged[index];
          return (
            !nextItem ||
            prevItem.assistantCall.name !== nextItem.assistantCall.name ||
            prevItem.assistantCall.content !== nextItem.assistantCall.content ||
            prevItem.toolResult?.content !== nextItem.toolResult?.content
          );
        });
        if (!changed) {
          return prev;
        }
      }

      return merged;
    });

    if (historicalToolPairs.length > 0) {
      if (agentStatus === 'running' && !userNavigatedRef.current) {
        setCurrentToolIndex(historicalToolPairs.length - 1);
      } else if (
        isSidePanelOpen &&
        !userClosedPanelRef.current &&
        !userNavigatedRef.current
      ) {
        setCurrentToolIndex(historicalToolPairs.length - 1);
      } else if (
        !isSidePanelOpen &&
        !autoOpenedPanel &&
        !userClosedPanelRef.current &&
        !isMobile
      ) {
        setCurrentToolIndex(historicalToolPairs.length - 1);
        setIsSidePanelOpen(true);
        setAutoOpenedPanel(true);
      }
    }
  }, [messages, agentStatus, isMobile, isSidePanelOpen, autoOpenedPanel]);

  useEffect(() => {
    if (agentStatus === 'idle') {
      userNavigatedRef.current = false;
    }
  }, [agentStatus]);

  useEffect(() => {
    if (!isSidePanelOpen) {
      setAutoOpenedPanel(false);
    }
  }, [isSidePanelOpen]);

  const handleToolClick = useCallback(
    (clickedAssistantMessageId: string | null, clickedToolName: string) => {
      if (!clickedAssistantMessageId) {
        toast.warning('Cannot view details: Assistant message ID is missing.');
        return;
      }
      void clickedToolName;

      userClosedPanelRef.current = false;
      userNavigatedRef.current = true;

      const toolIndex = assistantMessageToToolIndex.current.get(clickedAssistantMessageId);
      if (toolIndex !== undefined) {
        setExternalNavIndex(toolIndex);
        setCurrentToolIndex(toolIndex);
        setIsSidePanelOpen(true);
        setTimeout(() => setExternalNavIndex(undefined), 100);
        return;
      }

      const assistantMessages = messages.filter(
        (m) => m.type === 'assistant' && m.message_id,
      );
      const fallbackIndex = assistantMessages.findIndex(
        (m) => m.message_id === clickedAssistantMessageId,
      );
      if (fallbackIndex !== -1 && fallbackIndex < toolCalls.length) {
        setExternalNavIndex(fallbackIndex);
        setCurrentToolIndex(fallbackIndex);
        setIsSidePanelOpen(true);
        setTimeout(() => setExternalNavIndex(undefined), 100);
        return;
      }

      toast.info('Could not find details for this tool call.');
    },
    [messages, toolCalls],
  );

  const handleStreamingToolCall = useCallback((toolCall: StreamingToolCall | null) => {
    if (!toolCall || userClosedPanelRef.current) {
      return;
    }

    const rawToolName = toolCall.name || toolCall.xml_tag_name || 'unknown-tool';
    const toolName = rawToolName.replace(/_/g, '-').toLowerCase();

    const toolArguments = normalizeToolArguments(toolCall.arguments);
    let formattedContent = toolArguments;

    if (toolName.includes('command') && !toolArguments.includes('<execute-command>')) {
      formattedContent = `<execute-command>${toolArguments}</execute-command>`;
    } else if (
      toolName === 'create-file' ||
      toolName === 'delete-file' ||
      toolName === 'full-file-rewrite' ||
      toolName === 'edit-file'
    ) {
      const tag = toolName;
      if (
        !toolArguments.includes(`<${tag}>`) &&
        !toolArguments.includes('file_path=') &&
        !toolArguments.includes('target_file=')
      ) {
        const filePath = toolArguments.trim();
        if (filePath && !filePath.startsWith('<')) {
          formattedContent =
            tag === 'edit-file'
              ? `<${tag} target_file="${filePath}">`
              : `<${tag} file_path="${filePath}">`;
        } else {
          formattedContent = `<${tag}>${toolArguments}</${tag}>`;
        }
      }
    }

    const now = new Date().toISOString();
    const newToolCall: ToolCallInput = {
      assistantCall: {
        name: toolName,
        content: formattedContent,
        timestamp: now,
        toolCallId: toolCall.id,
        toolIndex: toolCall.index,
        statusType: toolCall.status_type || 'tool_started',
      },
      toolResult: {
        content: 'STREAMING',
        isSuccess: true,
        timestamp: now,
      },
    };

    setToolCalls((prev) => {
      const next = sortToolCallsByExecutionOrder(
        upsertStreamingToolCall(prev, newToolCall),
      );

      if (!userNavigatedRef.current) {
        const preferredIndex = next.findIndex((item) => {
          if (newToolCall.assistantCall.toolCallId && item.assistantCall.toolCallId) {
            return (
              item.assistantCall.toolCallId ===
              newToolCall.assistantCall.toolCallId
            );
          }
          if (
            typeof newToolCall.assistantCall.toolIndex === 'number' &&
            typeof item.assistantCall.toolIndex === 'number'
          ) {
            return (
              item.assistantCall.toolIndex ===
              newToolCall.assistantCall.toolIndex
            );
          }
          return item.assistantCall.name === newToolCall.assistantCall.name;
        });
        setCurrentToolIndex(preferredIndex >= 0 ? preferredIndex : next.length - 1);
      }

      return next;
    });

    setIsSidePanelOpen(true);
  }, []);

  return {
    toolCalls,
    setToolCalls,
    currentToolIndex,
    setCurrentToolIndex,
    isSidePanelOpen,
    setIsSidePanelOpen,
    autoOpenedPanel,
    setAutoOpenedPanel,
    externalNavIndex,
    setExternalNavIndex,
    handleToolClick,
    handleStreamingToolCall,
    toggleSidePanel,
    handleSidePanelNavigate,
    userClosedPanelRef,
  };
}
