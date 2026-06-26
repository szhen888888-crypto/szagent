export type ServerStatus = {
  api_url: string;
  online: boolean;
  managed: boolean;
  pid: number | null;
  started_at: number | null;
  uptime_seconds: number | null;
  message?: string;
};

export type ThreadSummary = {
  product_id?: string;
  platform?: string;
  product_status?: string;
  product_title?: string;
  next?: string[];
  current_node_label?: string;
  generated_image_path?: string;
  wearing_image_status?: string;
  wearing_image_status_label?: string;
  interrupt_count?: number;
  interrupts?: Array<Record<string, unknown>>;
  can_resume?: boolean;
  needs_manual_review?: boolean;
  stop_reason_code?: string;
  stop_reason?: string;
  stop_reason_detail?: string;
};

export type ThreadProgress = {
  phase?: string;
  phase_label?: string;
  status?: string;
  status_label?: string;
  message?: string;
  active_run?: Record<string, unknown>;
  running?: boolean;
  started_at?: string;
  updated_at?: string;
  elapsed_seconds?: number | null;
  elapsed_label?: string;
  tasks?: Array<Record<string, unknown>>;
};

export type WorkflowThread = {
  thread_id: string;
  status: string;
  created_at?: string;
  updated_at?: string;
  metadata: Record<string, unknown>;
  state_url: string;
  studio_url: string;
  summary: ThreadSummary;
  progress?: ThreadProgress;
  state_error?: string;
};

export type ThreadsResponse = {
  api_url: string;
  assistant_id: string;
  online: boolean;
  error?: string;
  threads: WorkflowThread[];
};

export type ThreadStateResponse = {
  thread_id: string;
  api_url: string;
  state: unknown;
  runs?: Array<Record<string, unknown>>;
  progress?: ThreadProgress;
};

const CONTROL_API_BASE =
  import.meta.env.VITE_CONTROL_API_BASE ?? "http://127.0.0.1:8765";

export { CONTROL_API_BASE };

async function requestJson<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${CONTROL_API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export function getServerStatus(apiUrl: string) {
  return requestJson<ServerStatus>(
    `/api/server/status?api_url=${encodeURIComponent(apiUrl)}`,
  );
}

export function startServer(port = 2024) {
  return requestJson<ServerStatus>("/api/server/start", {
    method: "POST",
    body: JSON.stringify({ port }),
  });
}

export function stopServer() {
  return requestJson<{ stopped: boolean; message: string }>("/api/server/stop", {
    method: "POST",
  });
}

export function restartServer(port = 2024) {
  return requestJson<ServerStatus>("/api/server/restart", {
    method: "POST",
    body: JSON.stringify({ port }),
  });
}

export function listThreads(
  apiUrl: string,
  assistantId: string,
  limit = 20,
) {
  return requestJson<ThreadsResponse>(
    `/api/threads?api_url=${encodeURIComponent(apiUrl)}&assistant_id=${encodeURIComponent(
      assistantId,
    )}&limit=${limit}`,
  );
}

export function getThreadState(apiUrl: string, threadId: string) {
  return requestJson<ThreadStateResponse>(
    `/api/threads/${threadId}/state?api_url=${encodeURIComponent(apiUrl)}`,
  );
}

export function startWorkflow(apiUrl: string, assistantId: string) {
  return requestJson<Record<string, unknown>>("/api/workflows/start", {
    method: "POST",
    body: JSON.stringify({ api_url: apiUrl, assistant_id: assistantId }),
  });
}

export function restartWorkflow(apiUrl: string, assistantId: string, threadId = "") {
  return requestJson<Record<string, unknown>>("/api/workflows/restart", {
    method: "POST",
    body: JSON.stringify({
      api_url: apiUrl,
      assistant_id: assistantId,
      thread_id: threadId,
    }),
  });
}

export function resumeThread(
  apiUrl: string,
  assistantId: string,
  threadId: string,
  resume: unknown,
) {
  return requestJson<Record<string, unknown>>(`/api/threads/${threadId}/resume`, {
    method: "POST",
    body: JSON.stringify({ api_url: apiUrl, assistant_id: assistantId, resume }),
  });
}
