/* eslint-disable @next/next/no-img-element -- Component renders dynamic/external image URLs where native <img> is currently intentional. */
import React, { useMemo, useState } from 'react';
import {
  Globe,
  MonitorPlay,
  ExternalLink,
  CheckCircle,
  AlertTriangle,
  CircleDashed,
} from 'lucide-react';
import { ToolViewProps } from './types';
import {
  extractBrowserUrl,
  extractBrowserOperation,
  formatTimestamp,
  getToolTitle,
  extractToolData,
} from './utils';
import { safeJsonParse } from '@/components/thread/utils';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ImageLoader } from './shared/ImageLoader';
import { ComputerPrivacyToolView } from './ComputerPrivacyToolView';

type PreviewData = {
  screenshotUrl: string | null;
  screenshotBase64: string | null;
  browserStateMessageId?: string;
  baseUrl: string | null;
};

const DESKTOP_TOOL_NAMES = new Set([
  'move_to',
  'move-to',
  'click',
  'scroll',
  'typing',
  'press',
  'wait',
  'mouse_down',
  'mouse-down',
  'mouse_up',
  'mouse-up',
  'drag_to',
  'drag-to',
  'screenshot',
  'hotkey',
  'key',
  'type',
]);

const readObject = (value: unknown): Record<string, any> | null => {
  if (!value) {
    return null;
  }
  if (typeof value === 'object') {
    return value as Record<string, any>;
  }
  if (typeof value !== 'string') {
    return null;
  }
  const trimmed = value.trim();
  if (!trimmed || (!trimmed.startsWith('{') && !trimmed.startsWith('['))) {
    return null;
  }
  try {
    const parsed = JSON.parse(trimmed);
    return parsed && typeof parsed === 'object'
      ? (parsed as Record<string, any>)
      : null;
  } catch {
    return null;
  }
};

const pickPreviewFields = (obj: Record<string, any> | null): Partial<PreviewData> => {
  if (!obj) {
    return {};
  }

  const screenshot = obj.screenshot || {};
  return {
    screenshotUrl:
      obj.image_url ||
      screenshot.url ||
      screenshot.image_url ||
      (typeof obj.base64_data === 'string' && obj.base64_data.startsWith('http')
        ? obj.base64_data
        : null),
    screenshotBase64: screenshot.base64 || null,
    browserStateMessageId: obj.message_id,
    baseUrl: obj.base_url || obj.baseUrl || null,
  };
};

const parseToolResultOutput = (
  toolContent?: string,
): Partial<PreviewData> => {
  if (!toolContent) {
    return {};
  }

  const topLevel = safeJsonParse<{ content?: unknown }>(toolContent, {});
  const inner = topLevel?.content ?? toolContent;

  if (typeof inner === 'object' && inner) {
    const output = (inner as any).tool_execution?.result?.output;
    return pickPreviewFields(readObject(output));
  }

  if (typeof inner !== 'string') {
    return {};
  }

  const toolResultMatch = inner.match(
    /ToolResult\([^)]*output='([\s\S]*?)'(?:\s*,|\s*\))/,
  );
  if (toolResultMatch) {
    const cleaned = toolResultMatch[1]
      .replace(/\\n/g, '\n')
      .replace(/\\"/g, '"')
      .replace(/\\u([0-9a-fA-F]{4})/g, (_m, g) =>
        String.fromCharCode(parseInt(g, 16)),
      );
    return pickPreviewFields(readObject(cleaned));
  }

  const direct = pickPreviewFields(readObject(inner));
  if (direct.screenshotUrl || direct.screenshotBase64) {
    return direct;
  }

  const imageUrlMatch = inner.match(/"image_url":\s*"([^"]+)"/);
  const screenshotUrlMatch = inner.match(
    /"screenshot":\s*{[^}]*"url":\s*"([^"]+)"/,
  );
  const base64DataUrlMatch = inner.match(/"base64_data":\s*"(https?:\/\/[^"]+)"/);
  const baseUrlMatch = inner.match(/"(?:base_url|baseUrl)":\s*"([^"]+)"/);
  const messageIdMatch = inner.match(/"message_id":\s*"([^"]+)"/);

  return {
    screenshotUrl:
      imageUrlMatch?.[1] || screenshotUrlMatch?.[1] || base64DataUrlMatch?.[1] || null,
    browserStateMessageId: messageIdMatch?.[1],
    baseUrl: baseUrlMatch?.[1] || null,
  };
};

const extractPreviewDataFromMessages = (
  messages: ToolViewProps['messages'],
  toolName: string,
): Partial<PreviewData> => {
  if (!messages?.length) {
    return {};
  }

  const toolMessages = messages
    .filter((msg) => msg.type === 'tool')
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));

  const matching = toolMessages.find((msg) => {
    if (!msg.metadata) {
      return false;
    }
    const metadata = readObject(msg.metadata);
    return metadata?.tool_name === toolName;
  });

  const preferred = matching ? [matching] : [];
  const candidates = [...preferred, ...toolMessages.slice(0, 5)];

  for (const candidate of candidates) {
    const content = readObject(candidate.content);
    const resultObj = readObject(content?.result) || (content?.result as any);
    const parsed = pickPreviewFields(readObject(resultObj) || readObject(content));
    if (parsed.screenshotUrl || parsed.screenshotBase64) {
      return parsed;
    }
  }

  return {};
};

export function BrowserToolView(props: ToolViewProps) {
  const normalizedAgentName = (props.agentName || '').trim().toLowerCase();
  const isAlexManusComputerView = normalizedAgentName.includes('alexmanus');

  if (isAlexManusComputerView) {
    return <ComputerPrivacyToolView {...props} />;
  }

  return <BrowserToolViewInternal {...props} />;
}

function BrowserToolViewInternal({
  name = 'browser-operation',
  assistantContent,
  toolContent,
  assistantTimestamp,
  toolTimestamp,
  isSuccess = true,
  isStreaming = false,
  project,
  agentStatus = 'idle',
  messages = [],
}: ToolViewProps) {
  const assistantToolData = extractToolData(assistantContent);
  const toolToolData = extractToolData(toolContent);
  let url: string | null = null;

  if (assistantToolData.toolResult) {
    url = assistantToolData.url;
  } else if (toolToolData.toolResult) {
    url = toolToolData.url;
  }
  if (!url) {
    url = extractBrowserUrl(assistantContent);
  }

  const toolTitle = getToolTitle(name);
  const operation = extractBrowserOperation(name);
  const isRunning = isStreaming || agentStatus === 'running';
  const isDesktopTool = DESKTOP_TOOL_NAMES.has(name);
  const isBrowserTool = name.startsWith('browser_') || name.startsWith('browser-');

  const [imageLoading, setImageLoading] = useState(true);
  const [imageError, setImageError] = useState(false);

  const preview = useMemo(() => {
    const fromToolData = pickPreviewFields(
      readObject(toolToolData.toolResult?.toolOutput),
    );
    const fromToolResult = parseToolResultOutput(toolContent);
    const fromMessages = extractPreviewDataFromMessages(messages, name);

    let screenshotUrl =
      fromToolData.screenshotUrl ||
      fromToolResult.screenshotUrl ||
      fromMessages.screenshotUrl ||
      null;
    let screenshotBase64 =
      fromToolData.screenshotBase64 ||
      fromToolResult.screenshotBase64 ||
      fromMessages.screenshotBase64 ||
      null;
    const browserStateMessageId =
      fromToolData.browserStateMessageId ||
      fromToolResult.browserStateMessageId ||
      fromMessages.browserStateMessageId;
    const baseUrl =
      fromToolData.baseUrl ||
      fromToolResult.baseUrl ||
      fromMessages.baseUrl ||
      null;

    if (baseUrl && screenshotUrl && !screenshotUrl.startsWith('http')) {
      screenshotUrl = `${baseUrl.replace(/\/$/, '')}/${screenshotUrl.replace(/^\//, '')}`;
    }

    if (!screenshotUrl && !screenshotBase64 && browserStateMessageId && messages.length) {
      const browserStateMessage = messages.find(
        (msg) =>
          (msg.type as string) === 'browser_state' &&
          msg.message_id === browserStateMessageId,
      );
      if (browserStateMessage) {
        const browserStateContent = safeJsonParse<{
          screenshot_base64?: string;
          image_url?: string;
        }>(browserStateMessage.content, {});
        screenshotBase64 = browserStateContent?.screenshot_base64 || null;
        screenshotUrl = browserStateContent?.image_url || null;
      }
    }

    return {
      screenshotUrl,
      screenshotBase64,
      browserStateMessageId,
      baseUrl,
    };
  }, [toolToolData.toolResult?.toolOutput, toolContent, messages, name]);

  const screenshotSrc = preview.screenshotUrl
    ? preview.screenshotUrl
    : preview.screenshotBase64
      ? `data:image/jpeg;base64,${preview.screenshotBase64}`
      : null;

  const vncPreviewUrl =
    project?.sandbox?.vnc_preview && project?.sandbox?.pass
      ? `${project.sandbox.vnc_preview}/vnc_lite.html?password=${project.sandbox.pass}&autoconnect=true&scale=remote&resize=scale&show_dot=true`
      : undefined;

  const showVnc = Boolean(vncPreviewUrl && (isDesktopTool || !screenshotSrc));
  const showScreenshot = Boolean(screenshotSrc && (isBrowserTool || !showVnc));

  const renderPreview = () => {
    if (showVnc && vncPreviewUrl) {
      return (
        <iframe
          src={vncPreviewUrl}
          title="VNC Desktop Preview"
          className="w-full h-full border-0"
          allow="fullscreen"
          sandbox="allow-scripts allow-same-origin allow-forms allow-pointer-lock allow-top-navigation"
          loading="lazy"
        />
      );
    }

    if (showScreenshot && screenshotSrc) {
      return (
        <div className="relative flex h-full w-full items-center justify-center bg-black p-3">
          {imageLoading && <ImageLoader />}
          <img
            src={screenshotSrc}
            alt="Browser Screenshot"
            className={`max-h-full max-w-full object-contain ${imageLoading ? 'hidden' : 'block'}`}
            onLoad={() => {
              setImageLoading(false);
              setImageError(false);
            }}
            onError={() => {
              setImageLoading(false);
              setImageError(true);
            }}
          />
          {imageError && !imageLoading && (
            <div className="absolute inset-0 flex items-center justify-center bg-zinc-50 dark:bg-zinc-900">
              <div className="text-center text-zinc-500 dark:text-zinc-400">
                <AlertTriangle className="mx-auto mb-2 h-8 w-8" />
                <p>Failed to load screenshot</p>
              </div>
            </div>
          )}
        </div>
      );
    }

    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-3 bg-gradient-to-b from-white to-zinc-50 p-8 text-zinc-600 dark:from-zinc-950 dark:to-zinc-900 dark:text-zinc-400">
        <div className="rounded-full bg-zinc-100 p-4 dark:bg-zinc-800">
          <MonitorPlay className="h-7 w-7" />
        </div>
        <div className="text-center">
          <p className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
            Preview not available
          </p>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            {isRunning
              ? 'Tool is still running. Preview will appear when data is ready.'
              : 'No screenshot or VNC stream was returned for this step.'}
          </p>
        </div>
      </div>
    );
  };

  return (
    <Card className="flex h-full flex-col overflow-hidden rounded-none border-x-0 border-b-0 border-t bg-card p-0 shadow-none gap-0">
      <CardHeader className="h-14 border-b bg-zinc-50/80 p-2 px-4 backdrop-blur-sm dark:bg-zinc-900/80">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="rounded-lg border border-blue-500/20 bg-blue-500/10 p-2">
              <MonitorPlay className="h-5 w-5 text-blue-500 dark:text-blue-400" />
            </div>
            <CardTitle className="text-base font-medium text-zinc-900 dark:text-zinc-100">
              {toolTitle}
            </CardTitle>
          </div>

          {isRunning ? (
            <Badge className="bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300">
              <CircleDashed className="h-3.5 w-3.5 animate-spin" />
              Running
            </Badge>
          ) : (
            <Badge
              variant="secondary"
              className={
                isSuccess
                  ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300'
                  : 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300'
              }
            >
              {isSuccess ? (
                <CheckCircle className="mr-1 h-3.5 w-3.5" />
              ) : (
                <AlertTriangle className="mr-1 h-3.5 w-3.5" />
              )}
              {isSuccess ? 'Completed' : 'Failed'}
            </Badge>
          )}
        </div>
      </CardHeader>

      <CardContent className="relative flex-1 overflow-hidden p-0 min-h-[420px]">
        {renderPreview()}
      </CardContent>

      <div className="flex h-10 items-center justify-between gap-4 border-t border-zinc-200 bg-zinc-50/90 px-4 py-2 text-xs text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900/90 dark:text-zinc-400">
        <div className="flex items-center gap-2 overflow-hidden">
          {!isRunning && (
            <Badge className="h-6 py-0.5">
              <Globe className="h-3 w-3" />
              {operation}
            </Badge>
          )}
          {url && (
            <span className="hidden max-w-[220px] truncate sm:inline-block">
              {url}
            </span>
          )}
          {url && (
            <Button variant="ghost" size="icon" className="h-6 w-6" asChild>
              <a href={url} target="_blank" rel="noopener noreferrer" title="Open URL">
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            </Button>
          )}
        </div>

        <span>
          {toolTimestamp && !isRunning
            ? formatTimestamp(toolTimestamp)
            : assistantTimestamp
              ? formatTimestamp(assistantTimestamp)
              : ''}
        </span>
      </div>
    </Card>
  );
}
