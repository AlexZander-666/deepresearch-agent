import { useState, useEffect, useRef, useCallback, useLayoutEffect } from 'react';
import {
  streamAgent,
  getAgentStatus,
  stopAgent,
  AgentRun,
  getMessages,
} from '@/lib/api';
import { toast } from 'sonner';
import {
  isAgentRunNotRunningError,
  isProviderAccountStreamError,
  isRecoverableAgentStreamError,
  toDisplayAgentStreamError,
} from './agent-stream-error-utils';
import {
  UnifiedMessage,
  ParsedContent,
  ParsedMetadata,
} from '@/components/thread/types';
import { safeJsonParse } from '@/components/thread/utils';

interface ApiMessageType {
  message_id?: string;
  thread_id?: string;
  type: string;
  is_llm_message?: boolean;
  content: string;
  metadata?: string;
  created_at?: string;
  updated_at?: string;
  agent_id?: string;
  agents?: {
    name: string;
    avatar?: string;
    avatar_color?: string;
  };
}

// Define the structure returned by the hook
export interface UseAgentStreamResult {
  status: string;
  textContent: string;
  toolCall: ParsedContent | null;
  error: string | null;
  agentRunId: string | null; // Expose the currently managed agentRunId
  startStreaming: (runId: string) => void;
  stopStreaming: () => Promise<void>;
}

// Define the callbacks the hook consumer can provide
export interface AgentStreamCallbacks {
  onMessage: (message: UnifiedMessage) => void; // Callback for complete messages
  onStatusChange?: (status: string) => void; // Optional: Notify on internal status changes
  onError?: (error: string) => void; // Optional: Notify on errors
  onClose?: (finalStatus: string) => void; // Optional: Notify when streaming definitively ends
  onAssistantStart?: () => void; // Optional: Notify when assistant starts streaming
  onAssistantChunk?: (chunk: { content: string }) => void; // Optional: Notify on each assistant message chunk
}

// Helper function to map API messages to UnifiedMessages
const mapApiMessagesToUnified = (
  messagesData: ApiMessageType[] | null | undefined,
  currentThreadId: string,
): UnifiedMessage[] => {
  return (messagesData || [])
    .filter((msg) => msg.type !== 'status')
    .map((msg: ApiMessageType) => ({
      message_id: msg.message_id || null,
      thread_id: msg.thread_id || currentThreadId,
      type: (msg.type || 'system') as UnifiedMessage['type'],
      is_llm_message: Boolean(msg.is_llm_message),
      content: msg.content || '',
      metadata: msg.metadata || '{}',
      created_at: msg.created_at || new Date().toISOString(),
      updated_at: msg.updated_at || new Date().toISOString(),
      agent_id: (msg as any).agent_id,
      agents: (msg as any).agents,
    }));
};

const normalizeToolArguments = (value: unknown): string => {
  if (value === null || value === undefined) {
    return '';
  }
  if (typeof value === 'string') {
    return value;
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
};

const extractToolCallFromStatus = (parsedContent: ParsedContent) => {
  const chunk = parsedContent.tool_call_chunk;
  const chunkFunction = chunk?.function ?? {};

  const name =
    chunkFunction?.name ||
    parsedContent.function_name ||
    parsedContent.xml_tag_name;
  if (!name) {
    return null;
  }

  const toolCallId = chunk?.id || parsedContent.tool_call_id || parsedContent.id;
  const toolIndex =
    typeof chunk?.index === 'number' ? chunk.index : parsedContent.tool_index;
  const rawArguments =
    chunkFunction?.arguments ??
    parsedContent.arguments ??
    parsedContent.tool_args ??
    parsedContent.parameters;

  return {
    role: 'assistant' as const,
    status_type: 'tool_started' as const,
    id: toolCallId,
    name,
    arguments: normalizeToolArguments(rawArguments),
    xml_tag_name: parsedContent.xml_tag_name,
    tool_index: toolIndex,
  };
};

export function useAgentStream(
  callbacks: AgentStreamCallbacks,
  threadId: string,
  setMessages: (messages: UnifiedMessage[]) => void,
): UseAgentStreamResult {
  const [agentRunId, setAgentRunId] = useState<string | null>(null);
  const [status, setStatus] = useState<string>('idle');
  const [textContent, setTextContent] = useState<
    { content: string; sequence?: number }[]
  >([]);
  const [toolCall, setToolCall] = useState<ParsedContent | null>(null);
  const [error, setError] = useState<string | null>(null);

  const streamCleanupRef = useRef<(() => void) | null>(null);
  const isMountedRef = useRef<boolean>(true);
  const currentRunIdRef = useRef<string | null>(null); // Ref to track the run ID being processed
  const threadIdRef = useRef(threadId); // Ref to hold the current threadId
  const setMessagesRef = useRef(setMessages); // Ref to hold the setMessages function

  // Use useLayoutEffect to ensure sorting happens synchronously before paint
  const [orderedTextContent, setOrderedTextContent] = useState('');

  useLayoutEffect(() => {
    const sorted = textContent
      .sort((a, b) => (a.sequence ?? 0) - (b.sequence ?? 0))
      .reduce((acc, curr) => acc + curr.content, '');
    setOrderedTextContent(sorted);
  }, [textContent]);

  // Refs to capture current state for persistence
  const statusRef = useRef(status);
  const agentRunIdRef = useRef(agentRunId);
  const textContentRef = useRef(textContent);
  
  // Update refs whenever state changes
  useEffect(() => {
    statusRef.current = status;
  }, [status]);
  
  useEffect(() => {
    agentRunIdRef.current = agentRunId;
  }, [agentRunId]);
  
  useEffect(() => {
    textContentRef.current = textContent;
  }, [textContent]);

  // On thread change, ensure any existing stream is cleaned up to avoid stale subscriptions
  useEffect(() => {
    const previousThreadId = threadIdRef.current;
    if (previousThreadId && previousThreadId !== threadId && streamCleanupRef.current) {
      // Close the existing stream for the previous thread
      streamCleanupRef.current();
      streamCleanupRef.current = null;
      setStatus('idle');
      setTextContent([]);
      setToolCall(null);
      setAgentRunId(null);
      currentRunIdRef.current = null;
    }
    threadIdRef.current = threadId;
  }, [threadId]);

  useEffect(() => {
    setMessagesRef.current = setMessages;
  }, [setMessages]);

  // Helper function to map backend status to frontend status string
  const mapAgentStatus = (backendStatus: string): string => {
    switch (backendStatus) {
      case 'completed':
        return 'completed';
      case 'stopped':
        return 'stopped';
      case 'failed':
        return 'failed';
      default:
        return 'error';
    }
  };

  // Internal function to update status and notify consumer
  const updateStatus = useCallback(
    (newStatus: string) => {
      if (isMountedRef.current) {
        setStatus(newStatus);
        callbacks.onStatusChange?.(newStatus);
        if (newStatus === 'error' && error) {
          callbacks.onError?.(error);
        }
        if (
          [
            'completed',
            'stopped',
            'failed',
            'error',
            'agent_not_running',
          ].includes(newStatus)
        ) {
          callbacks.onClose?.(newStatus);
        }
      }
    },
    [callbacks, error],
  ); // Include error dependency

  // Function to handle finalization of a stream (completion, stop, error)
  const finalizeStream = useCallback(
    (finalStatus: string, runId: string | null = agentRunId) => {
      if (!isMountedRef.current) return;

      const currentThreadId = threadIdRef.current; // Get current threadId from ref
      const currentSetMessages = setMessagesRef.current; // Get current setMessages from ref

      if (streamCleanupRef.current) {
        streamCleanupRef.current();
        streamCleanupRef.current = null;
      }

      // Reset streaming-specific state
      setTextContent([]);
      setToolCall(null);

      // Update status and clear run ID
      updateStatus(finalStatus);
      setAgentRunId(null);
      currentRunIdRef.current = null;
      
      // Message refetch disabled - optimistic messages will handle updates

      // If the run was stopped or completed, try to get final status to update nonRunning set (keep this)
      if (
        runId &&
        (finalStatus === 'completed' ||
          finalStatus === 'stopped' ||
          finalStatus === 'agent_not_running')
      ) {
        getAgentStatus(runId).catch((err) => {
        });
      }
    },
    [agentRunId, updateStatus],
  );

  // --- Stream Callback Handlers ---

  const handleStreamMessage = useCallback(
    (rawData: string) => {
      if (!isMountedRef.current) return;
      (window as any).lastStreamMessage = Date.now(); // Keep track of last message time

      let processedData = rawData;
      if (processedData.startsWith('data: ')) {
        processedData = processedData.substring(6).trim();
      }
      if (!processedData) return;

      // --- Early exit for non-JSON completion messages ---
      if (
        processedData ===
        '{"type": "status", "status": "completed", "message": "Agent run completed successfully"}'
      ) {
        finalizeStream('completed', currentRunIdRef.current);
        return;
      }
      if (
        processedData.includes('Run data not available for streaming') ||
        processedData.includes('Stream ended with status: completed')
      ) {
        finalizeStream('completed', currentRunIdRef.current);
        return;
      }

      // --- Check for error messages first ---
      try {
        const jsonData = JSON.parse(processedData);
        if (jsonData.status === 'error') {
          const rawErrorMessage = jsonData.message || 'Unknown error occurred';
          const displayErrorMessage = toDisplayAgentStreamError(rawErrorMessage);
          const shouldWarnOnly = isProviderAccountStreamError(rawErrorMessage);
          if (shouldWarnOnly) {
            console.warn(
              '[useAgentStream] Received provider account error status message:',
              jsonData,
            );
          } else {
            console.error(
              '[useAgentStream] Received error status message:',
              jsonData,
            );
          }

          setError(displayErrorMessage);
          if (callbacks.onError) {
            callbacks.onError(rawErrorMessage);
          } else {
            toast.error(displayErrorMessage, { duration: 15000 });
          }
          return;
        }
      } catch (jsonError) {
        // Not JSON or could not parse as JSON, continue processing
      }

      // --- Process JSON messages ---
      const message = safeJsonParse(processedData, null) as UnifiedMessage | null;
      if (!message) {
        console.warn(
          '[useAgentStream] Failed to parse streamed message:',
          processedData,
        );
        return;
      }

      const parsedContent = safeJsonParse<ParsedContent>(message.content, {});
      const parsedMetadata = safeJsonParse<ParsedMetadata>(
        message.metadata,
        {},
      );

      // Update status to streaming if we receive a valid message
      if (status !== 'streaming') updateStatus('streaming');

      switch (message.type) {
        case 'assistant':
          if (
            parsedMetadata.stream_status === 'chunk' &&
            parsedContent.content
          ) {
            setTextContent((prev) => {
              // 🔧 检查是否是完整文本chunk（包含所有之前的内容）
              // 如果新chunk的长度 >> 之前累积的总长度，说明这是一个完整版本chunk
              const currentTotalLength = prev.reduce((sum, item) => sum + item.content.length, 0);
              const newContentLength = parsedContent.content.length;
              
              // 如果新chunk长度 >= 当前累积长度，且sequence较大，说明是完整版本chunk
              // 这种情况下，用新chunk替换掉所有之前的chunks
              if (message.sequence !== undefined && 
                  message.sequence > 10 && 
                  newContentLength >= currentTotalLength &&
                  newContentLength > 20) {
                console.log(`🔄 [useAgentStream] Detected complete chunk (seq: ${message.sequence}, new: ${newContentLength}, prev: ${currentTotalLength}), replacing`);
                return [{
                  sequence: message.sequence,
                  content: parsedContent.content,
                }];
              }
              
              // 否则正常追加
              return prev.concat({
                sequence: message.sequence,
                content: parsedContent.content,
              });
            });
            callbacks.onAssistantChunk?.({ content: parsedContent.content });
          } else if (parsedMetadata.stream_status === 'complete') {
            // 收到完整消息，清空 streaming chunks
            console.log('✅ [useAgentStream] Complete message received, clearing streaming chunks');
            setTextContent([]);
            setToolCall(null);
            if (message.message_id) callbacks.onMessage(message);
          } else if (!parsedMetadata.stream_status) {
            // Handle non-chunked assistant messages if needed
            callbacks.onAssistantStart?.();
            if (message.message_id) callbacks.onMessage(message);
          }
          break;
        case 'tool':
          setToolCall(null); // Clear any streaming tool call
          if (message.message_id) callbacks.onMessage(message);
          break;
        case 'status':
          switch (parsedContent.status_type) {
            case 'tool_call_chunk':
              // 🔧 检测到工具调用，立即清空 streaming text
              // 避免显示包含重复内容的 streaming chunks
              console.log('🔄 [useAgentStream] Tool call detected, clearing streaming text immediately');
              setTextContent([]);
              {
                const parsedToolCall = extractToolCallFromStatus(parsedContent);
                if (parsedToolCall) {
                  setToolCall(parsedToolCall);
                }
              }
              break;
            case 'tool_started':
              {
                const parsedToolCall = extractToolCallFromStatus(parsedContent);
                if (parsedToolCall) {
                  setToolCall(parsedToolCall);
                }
              }
              break;
            case 'tool_completed':
            case 'tool_failed':
            case 'tool_error':
              if (
                (toolCall?.tool_index !== undefined &&
                  toolCall?.tool_index === parsedContent.tool_index) ||
                (toolCall?.id &&
                  parsedContent.tool_call_id &&
                  toolCall.id === parsedContent.tool_call_id)
              ) {
                setToolCall(null);
              }
              break;
            case 'thread_run_end':
              break;
            case 'finish':
              // Optional: Handle finish reasons like 'xml_tool_limit_reached'
              // Don't finalize here, wait for thread_run_end or completion message
              break;
            case 'error':
              {
                const statusErrorMessage =
                  parsedContent.message || 'Agent run failed';
                if (isRecoverableAgentStreamError(statusErrorMessage)) {
                  console.warn(
                    '[useAgentStream] Ignoring recoverable stream status error and keeping stream open:',
                    statusErrorMessage,
                  );
                  break;
                }
                setError(statusErrorMessage);
                finalizeStream('error', currentRunIdRef.current);
              }
              break;
            // Ignore thread_run_start, assistant_response_start etc. for now
            default:
              // console.debug('[useAgentStream] Received unhandled status type:', parsedContent.status_type);
              break;
          }
          if (message.message_id) {
            callbacks.onMessage(message);
          }
          break;
        case 'user':
        case 'system':
          // Handle other message types if necessary, e.g., if backend sends historical context
          if (message.message_id) callbacks.onMessage(message);
          break;
        default:
          console.warn(
            '[useAgentStream] Unhandled message type:',
            message.type,
          );
      }
    },
    [status, toolCall, callbacks, finalizeStream, updateStatus],
  );

  const handleStreamError = useCallback(
    (err: Error | string | Event) => {
      if (!isMountedRef.current) return;

      // Extract error message
      let errorMessage = 'Unknown streaming error';
      if (typeof err === 'string') {
        errorMessage = err;
      } else if (err instanceof Error) {
        errorMessage = err.message;
      } else if (err instanceof Event && err.type === 'error') {
        // Standard EventSource errors don't have much detail, might need status check
        errorMessage = 'Stream connection error';
      }

      if (isAgentRunNotRunningError(errorMessage)) {
        console.warn(
          '[useAgentStream] Ignoring not-running stream error for terminal agent run.',
        );
        finalizeStream('agent_not_running', currentRunIdRef.current);
        return;
      }

      if (isRecoverableAgentStreamError(errorMessage)) {
        console.warn(
          '[useAgentStream] Recoverable stream transport error detected, waiting for backend retry:',
          errorMessage,
        );
        return;
      }

      const displayErrorMessage = toDisplayAgentStreamError(errorMessage);
      if (isProviderAccountStreamError(errorMessage)) {
        console.warn(
          '[useAgentStream] Provider account stream error:',
          errorMessage,
        );
      } else {
        console.error('[useAgentStream] Streaming error:', errorMessage, err);
      }
      setError(displayErrorMessage);
      if (callbacks.onError) {
        callbacks.onError(errorMessage);
      } else {
        toast.error(displayErrorMessage, { duration: 15000 });
      }

      const runId = currentRunIdRef.current;
      if (!runId) {
        console.warn(
          '[useAgentStream] Stream error occurred but no agentRunId is active.',
        );
        finalizeStream('error'); // Finalize with generic error if no runId
        return;
      }

    },
    [callbacks, finalizeStream],
  );

  const handleStreamClose = useCallback(() => {
    if (!isMountedRef.current) return;

    const runId = currentRunIdRef.current;
    if (!runId) {
      if (status === 'streaming' || status === 'connecting') {
        console.warn('[useAgentStream] Stream closed while still streaming but no active agentRunId.');
        finalizeStream('error');
      }
      return;
    }

    // Immediately check the agent status when the stream closes unexpectedly
    // This covers cases where the agent finished but the final message wasn't received,
    // or if the agent errored out on the backend.
    getAgentStatus(runId)
      .then((agentStatus) => {
        if (!isMountedRef.current) return; // Check mount status again

        if (agentStatus.status === 'running') {
          setError('Stream closed unexpectedly while agent was running.');
          finalizeStream('error', runId); // Finalize as error for now
          toast.warning('Stream disconnected. Agent might still be running.');
        } else {
          // Map backend terminal status to hook terminal status
          const finalStatus = mapAgentStatus(agentStatus.status);
          finalizeStream(finalStatus, runId);
        }
      })
      .catch((err) => {
        if (!isMountedRef.current) return;

        const errorMessage = err instanceof Error ? err.message : String(err);
        console.error(
          `[useAgentStream] Error checking agent status for ${runId} after stream close: ${errorMessage}`,
        );

        const isNotFoundError =
          errorMessage.includes('not found') ||
          errorMessage.includes('404') ||
          errorMessage.includes('does not exist');
        const isNotRunningError = isAgentRunNotRunningError(errorMessage);

        if (isNotFoundError || isNotRunningError) {
          // Revert to agent_not_running for this specific case
          finalizeStream('agent_not_running', runId);
        } else {
          // For other errors checking status, finalize with generic error
          finalizeStream('error', runId);
        }
      });
  }, [status, finalizeStream]); // Include status

  // --- Effect to manage the stream lifecycle ---
  useEffect(() => {
    isMountedRef.current = true;

    // Cleanup function - be more conservative about stream cleanup
    return () => {
      isMountedRef.current = false;
      
      // Don't automatically cleanup streams on navigation
      // Only set mounted flag to false to prevent new operations
      // Streams will be cleaned up when they naturally complete or on explicit stop
    };
  }, []); // Empty dependency array for mount/unmount effect

  // --- Public Functions ---

  const startStreaming = useCallback(
    async (runId: string) => {
      if (!isMountedRef.current) return;

      // Clean up any previous stream
      if (streamCleanupRef.current) {
        streamCleanupRef.current();
        streamCleanupRef.current = null;
      }

      // Reset state before starting
      setTextContent([]);
      setToolCall(null);
      setError(null);
      updateStatus('connecting');
      setAgentRunId(runId);
      currentRunIdRef.current = runId; // Set the ref immediately

      try {
        // *** Crucial check: Verify agent is running BEFORE connecting ***
        const agentStatus = await getAgentStatus(runId);
        if (!isMountedRef.current) return; // Check mount status after async call

        if (agentStatus.status !== 'running') {
          console.warn(
            `[useAgentStream] Agent run ${runId} is not in running state (status: ${agentStatus.status}). Cannot start stream.`,
          );
          finalizeStream(
            mapAgentStatus(agentStatus.status) || 'agent_not_running',
            runId,
          );
          return;
        }

        // Agent is running, proceed to create the stream
        const cleanup = streamAgent(runId, {
          onMessage: (data) => {
            // Ignore messages if threadId changed while the EventSource stayed open
            if (threadIdRef.current !== threadId) return;
            handleStreamMessage(data);
          },
          onError: (err) => {
            if (threadIdRef.current !== threadId) return;
            handleStreamError(err);
          },
          onClose: () => {
            if (threadIdRef.current !== threadId) return;
            handleStreamClose();
          },
        });
        streamCleanupRef.current = cleanup;
        // Status will be updated to 'streaming' by the first message received in handleStreamMessage
        // If for some reason no message arrives shortly, verify liveness again to avoid zombie state
        setTimeout(async () => {
          if (!isMountedRef.current) return;
          if (currentRunIdRef.current !== runId) return; // Another run started
          if (statusRef.current === 'streaming') return; // Already streaming
          try {
            const latest = await getAgentStatus(runId);
            if (!isMountedRef.current) return;
            if (currentRunIdRef.current !== runId) return;
            if (latest.status !== 'running') {
              finalizeStream(mapAgentStatus(latest.status) || 'agent_not_running', runId);
            }
          } catch {
            // ignore
          }
        }, 1500);
      } catch (err) {
        if (!isMountedRef.current) return; // Check mount status after async call

        const errorMessage = err instanceof Error ? err.message : String(err);
        console.error(
          `[useAgentStream] Error initiating stream for ${runId}: ${errorMessage}`,
        );

        const isNotFoundError =
          errorMessage.includes('not found') ||
          errorMessage.includes('404') ||
          errorMessage.includes('does not exist');
        const isNotRunningError = isAgentRunNotRunningError(errorMessage);

        if (!isNotRunningError) {
          setError(errorMessage);
        }

        finalizeStream(
          isNotFoundError || isNotRunningError ? 'agent_not_running' : 'error',
          runId,
        );
      }
    },
    [
      threadId,
      updateStatus,
      finalizeStream,
      handleStreamMessage,
      handleStreamError,
      handleStreamClose,
    ],
  ); // Add dependencies

  const stopStreaming = useCallback(async () => {
    if (!isMountedRef.current || !agentRunId) return;

    const runIdToStop = agentRunId;

    // Immediately update status and clean up stream
    finalizeStream('stopped', runIdToStop);

    try {
      await stopAgent(runIdToStop);
      toast.success('Agent stopped.');
      // finalizeStream already called getAgentStatus implicitly if needed
    } catch (err) {
      // Don't revert status here, as the user intended to stop. Just log error.
      const errorMessage = err instanceof Error ? err.message : String(err);
      console.error(
        `[useAgentStream] Error sending stop request for ${runIdToStop}: ${errorMessage}`,
      );
      toast.error(`Failed to stop agent: ${errorMessage}`);
    }
  }, [agentRunId, finalizeStream]); // Add dependencies

  return {
    status,
    textContent: orderedTextContent,
    toolCall,
    error,
    agentRunId,
    startStreaming,
    stopStreaming,
  };
}
