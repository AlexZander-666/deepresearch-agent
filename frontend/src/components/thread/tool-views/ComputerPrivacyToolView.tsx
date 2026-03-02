import React from 'react';
import { CircleDashed, MonitorPlay, Shield } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ToolViewProps } from './types';
import { formatTimestamp, getToolTitle } from './utils';

export function ComputerPrivacyToolView({
  name = 'computer-use',
  assistantTimestamp,
  toolTimestamp,
  isSuccess = true,
  isStreaming = false,
  agentStatus = 'idle',
}: ToolViewProps) {
  const isRunning = isStreaming || agentStatus === 'running';
  const timestamp = toolTimestamp || assistantTimestamp;
  const title = getToolTitle(name) || 'Computer Action';

  return (
    <Card className="gap-0 flex border shadow-none border-t border-b-0 border-x-0 p-0 rounded-none flex-col h-full overflow-hidden bg-card">
      <CardHeader className="h-14 bg-zinc-50/80 dark:bg-zinc-900/80 backdrop-blur-sm border-b p-2 px-4 space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="relative p-2 rounded-xl bg-gradient-to-br from-zinc-500/20 to-zinc-600/10 border border-zinc-500/20">
              <MonitorPlay className="w-5 h-5 text-zinc-600 dark:text-zinc-300" />
            </div>
            <CardTitle className="text-base font-medium text-zinc-900 dark:text-zinc-100">
              {title}
            </CardTitle>
          </div>
          <Badge variant="outline" className="text-xs font-normal">
            {isRunning ? (
              <>
                <CircleDashed className="h-3.5 w-3.5 animate-spin" />
                Running
              </>
            ) : (
              <>
                <Shield className="h-3.5 w-3.5" />
                {isSuccess ? 'Completed' : 'Failed'}
              </>
            )}
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="h-full flex-1 p-8 flex items-center justify-center bg-gradient-to-b from-white to-zinc-50 dark:from-zinc-950 dark:to-zinc-900">
        <div className="max-w-sm text-center text-zinc-600 dark:text-zinc-300">
          <div className="w-20 h-20 rounded-full mx-auto mb-6 flex items-center justify-center bg-gradient-to-b from-zinc-200 to-zinc-100 shadow-inner dark:from-zinc-800 dark:to-zinc-900">
            <Shield className="h-10 w-10 text-zinc-600 dark:text-zinc-400" />
          </div>
          <h3 className="text-xl font-semibold mb-2 text-zinc-900 dark:text-zinc-100">
            Privacy Mode
          </h3>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            AlexManus 不展示 sandbox 操作画面或截图，仅保留工具执行状态与结果摘要。
          </p>
        </div>
      </CardContent>

      <div className="px-4 py-2 h-10 bg-gradient-to-r from-zinc-50/90 to-zinc-100/90 dark:from-zinc-900/90 dark:to-zinc-800/90 backdrop-blur-sm border-t border-zinc-200 dark:border-zinc-800 flex justify-end items-center">
        <span className="text-xs text-zinc-500 dark:text-zinc-400">
          {formatTimestamp(timestamp)}
        </span>
      </div>
    </Card>
  );
}
