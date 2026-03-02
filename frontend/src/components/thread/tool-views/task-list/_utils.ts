export interface Task {
  id: string;
  content: string;
  status: 'pending' | 'completed' | 'cancelled';
  section_id: string;
}

export interface Section {
  id: string;
  title: string;
  tasks: Task[];
}

export interface TaskListData {
  sections: Section[];
  total_tasks?: number;
  total_sections?: number;
  message?: string;
}

function parseContent(content: unknown): any {
  if (typeof content !== 'string') {
    return content;
  }
  try {
    return JSON.parse(content);
  } catch {
    return content;
  }
}

function normalizeTask(rawTask: any, sectionId: string, index: number): Task {
  if (typeof rawTask === 'string') {
    return {
      id: `task-${sectionId}-${index}`,
      content: rawTask,
      status: 'pending',
      section_id: sectionId,
    };
  }

  return {
    id: rawTask?.id || `task-${sectionId}-${index}`,
    content: rawTask?.content || rawTask?.title || String(rawTask ?? ''),
    status: rawTask?.status || 'pending',
    section_id: rawTask?.section_id || sectionId,
  };
}

function normalizeSections(rawSections: any[]): Section[] {
  return rawSections.map((rawSection: any, sectionIndex: number) => {
    const sectionId = rawSection?.id || `section-${sectionIndex}`;
    const rawTasks = Array.isArray(rawSection?.tasks) ? rawSection.tasks : [];

    return {
      id: sectionId,
      title: rawSection?.title || 'Untitled Section',
      tasks: rawTasks.map((rawTask: any, taskIndex: number) =>
        normalizeTask(rawTask, sectionId, taskIndex),
      ),
    };
  });
}

function buildFromSections(
  rawSections: any[],
  totalTasks?: number,
  totalSections?: number,
): TaskListData {
  const sections = normalizeSections(rawSections);
  const computedTaskCount = sections.reduce((sum, section) => sum + section.tasks.length, 0);
  return {
    sections,
    total_tasks: typeof totalTasks === 'number' ? totalTasks : computedTaskCount,
    total_sections: typeof totalSections === 'number' ? totalSections : sections.length,
  };
}

function buildFromTasks(rawTasks: any[]): TaskListData {
  const sectionId = 'section-inbox';
  const tasks = rawTasks.map((rawTask: any, index: number) =>
    normalizeTask(rawTask, sectionId, index),
  );
  return {
    sections: [{ id: sectionId, title: 'Tasks', tasks }],
    total_tasks: tasks.length,
    total_sections: 1,
  };
}

function extractFromAnyFormat(content: any): TaskListData | null {
  const parsedContent = parseContent(content);
  if (!parsedContent || typeof parsedContent !== 'object') {
    return null;
  }

  if (Array.isArray(parsedContent.sections)) {
    return buildFromSections(
      parsedContent.sections,
      parsedContent.total_tasks,
      parsedContent.total_sections,
    );
  }

  if (Array.isArray(parsedContent.tasks)) {
    return buildFromTasks(parsedContent.tasks);
  }

  if (
    parsedContent.status_type === 'tool_call_chunk' &&
    parsedContent.tool_call_chunk?.function?.arguments
  ) {
    const args = parseContent(parsedContent.tool_call_chunk.function.arguments);
    if (args && typeof args === 'object') {
      if (Array.isArray(args.sections)) {
        return buildFromSections(args.sections);
      }
      if (Array.isArray(args.tasks)) {
        return buildFromTasks(args.tasks);
      }
    }
  }

  const taskToolNames = new Set([
    'create_tasks',
    'create-tasks',
    'update_tasks',
    'update-tasks',
    'view_tasks',
    'view-tasks',
    'delete_tasks',
    'delete-tasks',
  ]);

  if (
    parsedContent.result &&
    typeof parsedContent.tool_name === 'string' &&
    taskToolNames.has(parsedContent.tool_name)
  ) {
    const resultData = parseContent(parsedContent.result);
    if (resultData && typeof resultData === 'object') {
      if (Array.isArray(resultData.sections)) {
        return buildFromSections(
          resultData.sections,
          resultData.total_tasks,
          resultData.total_sections,
        );
      }
      if (Array.isArray(resultData.tasks)) {
        return buildFromTasks(resultData.tasks);
      }
    }
  }

  const toolExecutionOutput = parsedContent.tool_execution?.result?.output;
  if (toolExecutionOutput) {
    const outputData = parseContent(toolExecutionOutput);
    if (outputData && typeof outputData === 'object') {
      if (Array.isArray(outputData.sections)) {
        return buildFromSections(
          outputData.sections,
          outputData.total_tasks,
          outputData.total_sections,
        );
      }
      if (Array.isArray(outputData.tasks)) {
        return buildFromTasks(outputData.tasks);
      }
    }
  }

  if (parsedContent.content) {
    return extractFromAnyFormat(parsedContent.content);
  }

  return null;
}

export function extractTaskListData(
  assistantContent?: string,
  toolContent?: string,
): TaskListData | null {
  return extractFromAnyFormat(toolContent) || extractFromAnyFormat(assistantContent);
}
