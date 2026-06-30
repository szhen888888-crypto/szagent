import {
  type Dispatch,
  type ReactNode,
  type SetStateAction,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  BookOpenCheck,
  Activity,
  AlertCircle,
  Check,
  CheckCircle2,
  Clock,
  Copy,
  Cpu,
  ExternalLink,
  FileText,
  GalleryHorizontalEnd,
  Image as ImageIcon,
  Images,
  Maximize2,
  Minus,
  Loader2,
  PauseCircle,
  Play,
  Power,
  RefreshCcw,
  RotateCcw,
  Sparkles,
  Square,
  Trash2,
  X,
} from "lucide-react";
import Zoom from "react-medium-image-zoom";
import {
  clearEnrouteLearning,
  clearWorkflowFlows,
  deleteWorkflowFlow,
  getServerStatus,
  getThreadState,
  listEnrouteLearning,
  listModelProfiles,
  listPrompts,
  listThreads,
  EnrouteLearningItem,
  EnrouteLearningResponse,
  ModelProfile,
  ModelProfilesResponse,
  PromptInfo,
  PromptsResponse,
  createPromptVersion,
  savePromptContent,
  setPromptOverride,
  restartServer,
  restartWorkflow,
  resumeThread,
  ServerStatus,
  startServer,
  startWorkflow,
  stopWorkflowFlow,
  stopServer,
  AiCallSummary,
  ThreadStateResponse,
  ThreadsResponse,
  ThreadProgress,
  WorkflowThread,
  CONTROL_API_BASE,
} from "./api";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./components/ui/card";
import { Dialog } from "./components/ui/dialog";
import { Input } from "./components/ui/input";
import { Textarea } from "./components/ui/textarea";

const DEFAULT_API_URL = "http://127.0.0.1:2024";
const DEFAULT_ASSISTANT_ID = "product_listing";
type PageId = "tasks" | "models" | "learning" | "prompts";
type ActionKey =
  | "refresh"
  | "server-start"
  | "server-stop"
  | "server-restart"
  | "workflow-start"
  | "workflow-restart"
  | "clear-flows"
  | "flow-stop"
  | "flow-delete"
  | "clear-enroute"
  | "resume-approve"
  | "resume-regenerate"
  | "resume-reject"
  | "resume-custom";

export default function App() {
  const [page, setPage] = useState<PageId>("tasks");
  const [apiUrl, setApiUrl] = useState(DEFAULT_API_URL);
  const [assistantId, setAssistantId] = useState(DEFAULT_ASSISTANT_ID);
  const [server, setServer] = useState<ServerStatus | null>(null);
  const [threads, setThreads] = useState<ThreadsResponse | null>(null);
  const [modelProfiles, setModelProfiles] = useState<ModelProfilesResponse | null>(
    null,
  );
  const [enrouteLearning, setEnrouteLearning] =
    useState<EnrouteLearningResponse | null>(null);
  const [prompts, setPrompts] = useState<PromptsResponse | null>(null);
  const [selectedThreadId, setSelectedThreadId] = useState("");
  const [threadState, setThreadState] = useState<ThreadStateResponse | null>(null);
  const [resumeJson, setResumeJson] = useState('{"action":"approve"}');
  const [lastResult, setLastResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const [activeAction, setActiveAction] = useState<ActionKey | null>(null);
  const [activeThreadActionId, setActiveThreadActionId] = useState("");
  const selectedThreadIdRef = useRef(selectedThreadId);

  const selectedThread = useMemo(
    () => threads?.threads.find((thread) => thread.thread_id === selectedThreadId),
    [selectedThreadId, threads],
  );

  useEffect(() => {
    selectedThreadIdRef.current = selectedThreadId;
  }, [selectedThreadId]);

  async function refreshAll(
    options: { silent?: boolean; autoSelectThread?: boolean } = {},
  ) {
    if (!options.silent) {
      setLoading(true);
      setError("");
    }
    try {
      const [serverStatus, threadList] = await Promise.all([
        getServerStatus(apiUrl),
        listThreads(apiUrl, assistantId),
      ]);
      setStableJsonState(setServer, serverStatus);
      setStableJsonState(setThreads, threadList);
      if (
        options.autoSelectThread !== false &&
        !selectedThreadIdRef.current &&
        threadList.threads.length > 0
      ) {
        setSelectedThreadId(threadList.threads[0].thread_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (!options.silent) {
        setLoading(false);
      }
    }
  }

  async function refreshThreadState(
    threadId = selectedThreadIdRef.current,
    options: { silent?: boolean } = {},
  ) {
    if (!threadId) {
      setThreadState(null);
      return;
    }
    if (!options.silent) {
      setError("");
    }
    try {
      const nextState = await getThreadState(apiUrl, threadId);
      if (threadId === selectedThreadIdRef.current) {
        setStableJsonState(setThreadState, nextState);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function refreshModelProfiles(options: { silent?: boolean } = {}) {
    if (!options.silent) {
      setLoading(true);
      setError("");
    }
    try {
      const profiles = await listModelProfiles();
      setStableJsonState(setModelProfiles, profiles);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (!options.silent) {
        setLoading(false);
      }
    }
  }

  async function refreshEnrouteLearning(options: { silent?: boolean } = {}) {
    if (!options.silent) {
      setLoading(true);
      setError("");
    }
    try {
      const learning = await listEnrouteLearning();
      setStableJsonState(setEnrouteLearning, learning);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (!options.silent) {
        setLoading(false);
      }
    }
  }

  async function refreshPrompts(options: { silent?: boolean } = {}) {
    if (!options.silent) {
      setLoading(true);
      setError("");
    }
    try {
      const promptList = await listPrompts();
      setStableJsonState(setPrompts, promptList);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (!options.silent) {
        setLoading(false);
      }
    }
  }

  async function refreshCurrentPage() {
    setActiveAction("refresh");
    try {
      if (page === "tasks") {
        await refreshAll();
      } else if (page === "models") {
        await refreshModelProfiles();
      } else if (page === "learning") {
        await refreshEnrouteLearning();
      } else {
        await refreshPrompts();
      }
    } finally {
      setActiveAction(null);
    }
  }

  async function runAction(
    action: () => Promise<Record<string, unknown>>,
    actionKey: ActionKey,
    options: {
      refreshTasks?: boolean;
      clearThreadSelection?: boolean;
      activeThreadId?: string;
    } = {},
  ) {
    setActiveAction(actionKey);
    setActiveThreadActionId(options.activeThreadId ?? "");
    setLoading(true);
    setError("");
    setNotice("");
    try {
      const result = await action();
      setLastResult(result);
      setNotice(actionNotice(result));
      const resultThreadId =
        typeof result.thread_id === "string" ? result.thread_id : selectedThreadId;
      const shouldSelectResultThread = shouldAutoSelectResultThread(result);
      if (shouldSelectResultThread && typeof result.thread_id === "string") {
        setSelectedThreadId(result.thread_id);
      }
      if (options.clearThreadSelection) {
        selectedThreadIdRef.current = "";
        setSelectedThreadId("");
        setThreadState(null);
      }
      if (options.refreshTasks ?? true) {
        await refreshAll({
          autoSelectThread: options.clearThreadSelection ? false : undefined,
        });
        if (!options.clearThreadSelection) {
          await refreshThreadState(
            shouldSelectResultThread ? resultThreadId : selectedThreadId,
          );
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
      setActiveAction(null);
      setActiveThreadActionId("");
    }
  }

  useEffect(() => {
    refreshAll();
    refreshModelProfiles({ silent: true });
    refreshEnrouteLearning({ silent: true });
    refreshPrompts({ silent: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    refreshThreadState();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedThreadId]);

  useEffect(() => {
    const hasRunningThread =
      threads?.threads.some((thread) => thread.status === "busy") ?? false;
    if (!hasRunningThread) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      refreshAll({ silent: true });
      refreshThreadState(undefined, { silent: true });
    }, 5000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threads, selectedThreadId, apiUrl, assistantId]);

  useEffect(() => {
    if (!error) {
      return undefined;
    }
    const timer = window.setTimeout(() => setError(""), 10000);
    return () => window.clearTimeout(timer);
  }, [error]);

  return (
    <main className="min-h-screen text-zinc-950">
      <ErrorToast message={error} onClose={() => setError("")} />
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-5 px-4 py-6">
        <header className="flex flex-col gap-4 rounded-2xl border border-zinc-200/70 bg-white/70 p-5 shadow-[0_1px_2px_rgba(24,24,27,0.04),0_12px_32px_-16px_rgba(24,24,27,0.16)] backdrop-blur md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3.5">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-lg shadow-brand-600/30">
              <Sparkles className="h-5 w-5" />
            </div>
            <div>
              <h1 className="bg-gradient-to-r from-zinc-900 to-zinc-600 bg-clip-text text-2xl font-semibold tracking-tight text-transparent">
                Productv2 控制台
              </h1>
              <p className="mt-0.5 text-sm text-zinc-500">
                本地 LangGraph 服务、任务状态和 resume 控制。
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <PageNav page={page} onChange={setPage} />
            {page === "tasks" ? (
              <>
                <Input
                  className="w-[200px]"
                  aria-label="API URL"
                  placeholder="API URL"
                  value={apiUrl}
                  onChange={(event) => setApiUrl(event.target.value)}
                />
                <Input
                  className="w-[160px]"
                  aria-label="Assistant ID"
                  placeholder="Assistant ID"
                  value={assistantId}
                  onChange={(event) => setAssistantId(event.target.value)}
                />
              </>
            ) : null}
            <Button
              variant="outline"
              onClick={refreshCurrentPage}
              disabled={loading}
              loading={activeAction === "refresh"}
              loadingText="刷新中"
            >
              <RefreshCcw className="h-4 w-4" />
              刷新
            </Button>
          </div>
        </header>

        {notice ? <div className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50/80 p-3.5 text-sm text-amber-800 shadow-sm"><span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-amber-500" />{notice}</div> : null}

        {page === "tasks" ? (
          <section className="grid gap-4 lg:grid-cols-[360px_1fr]">
            <div className="flex flex-col gap-4">
              <ServerPanel
                server={server}
                loading={loading}
                activeAction={activeAction}
                onStart={() =>
                  runAction(
                    () => startServer(2024) as Promise<Record<string, unknown>>,
                    "server-start",
                  )
                }
                onStop={() =>
                  runAction(
                    () => stopServer() as Promise<Record<string, unknown>>,
                    "server-stop",
                  )
                }
                onRestart={() =>
                  runAction(
                    () => restartServer(2024) as Promise<Record<string, unknown>>,
                    "server-restart",
                  )
                }
              />
              <WorkflowPanel
                loading={loading}
                activeAction={activeAction}
                onStart={() =>
                  runAction(
                    () => startWorkflow(apiUrl, assistantId),
                    "workflow-start",
                  )
                }
                onRestart={() =>
                  runAction(
                    () => restartWorkflow(apiUrl, assistantId, selectedThreadId),
                    "workflow-restart",
                  )
                }
                onClearFlows={() =>
                  runAction(
                    () => clearWorkflowFlows(apiUrl, assistantId),
                    "clear-flows",
                    { clearThreadSelection: true },
                  )
                }
              />
              <ThreadList
                threads={threads?.threads ?? []}
                selectedThreadId={selectedThreadId}
                loading={loading}
                activeAction={activeAction}
                activeThreadActionId={activeThreadActionId}
                onSelect={setSelectedThreadId}
                onStop={(threadId) =>
                  runAction(
                    () => stopWorkflowFlow(apiUrl, threadId),
                    "flow-stop",
                    { activeThreadId: threadId },
                  )
                }
                onDelete={(threadId) =>
                  runAction(
                    () => deleteWorkflowFlow(apiUrl, assistantId, threadId),
                    "flow-delete",
                    {
                      activeThreadId: threadId,
                      clearThreadSelection: threadId === selectedThreadId,
                    },
                  )
                }
              />
            </div>

            <div className="flex flex-col gap-4">
              <ThreadDetail
                thread={selectedThread}
                state={threadState}
                learning={enrouteLearning}
                resumeJson={resumeJson}
                setResumeJson={setResumeJson}
                loading={loading}
                activeAction={activeAction}
                onResume={(payload, actionKey) =>
                  runAction(
                    () =>
                      resumeThread(
                        apiUrl,
                        assistantId,
                        selectedThreadId,
                        payload,
                      ),
                    actionKey,
                  )
                }
                onOpenStudio={() => selectedThread?.studio_url && window.open(selectedThread.studio_url, "_blank")}
              />
              <ResultPanel result={lastResult} />
            </div>
          </section>
        ) : page === "models" ? (
          <ModelProfilesPage profiles={modelProfiles?.profiles ?? []} />
        ) : page === "learning" ? (
          <EnrouteLearningPage
            learning={enrouteLearning}
            onClear={() =>
              runAction(
                async () => {
                  const result = await clearEnrouteLearning();
                  await refreshEnrouteLearning({ silent: true });
                  return result;
                },
                "clear-enroute",
                { refreshTasks: false },
              )
            }
            loading={loading}
            activeAction={activeAction}
          />
        ) : (
          <PromptsPage
            prompts={prompts?.prompts ?? []}
            onRefresh={() => refreshPrompts({ silent: true })}
          />
        )}
      </div>
    </main>
  );
}

function PageNav({
  page,
  onChange,
}: {
  page: PageId;
  onChange: (page: PageId) => void;
}) {
  return (
    <nav className="flex gap-0.5 rounded-xl border border-zinc-200 bg-zinc-50/80 p-1 shadow-sm">
      <Button
        className="h-8 px-2"
        variant={page === "tasks" ? "default" : "ghost"}
        onClick={() => onChange("tasks")}
      >
        <Activity className="h-4 w-4" />
        任务
      </Button>
      <Button
        className="h-8 px-2"
        variant={page === "models" ? "default" : "ghost"}
        onClick={() => onChange("models")}
      >
        <GalleryHorizontalEnd className="h-4 w-4" />
        模特
      </Button>
      <Button
        className="h-8 px-2"
        variant={page === "learning" ? "default" : "ghost"}
        onClick={() => onChange("learning")}
      >
        <BookOpenCheck className="h-4 w-4" />
        学习
      </Button>
      <Button
        className="h-8 px-2"
        variant={page === "prompts" ? "default" : "ghost"}
        onClick={() => onChange("prompts")}
      >
        <FileText className="h-4 w-4" />
        提示词
      </Button>
    </nav>
  );
}

function ErrorToast({
  message,
  onClose,
}: {
  message: string;
  onClose: () => void;
}) {
  if (!message) {
    return null;
  }
  return (
    <div className="fixed right-4 top-4 z-50 w-[calc(100vw-2rem)] max-w-md">
      <div className="flex items-start gap-3 rounded-lg border border-red-200 bg-white px-4 py-3 text-sm text-red-800 shadow-lg shadow-red-950/10 ring-1 ring-red-100">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />
        <div className="min-w-0 flex-1">
          <p className="font-medium text-red-900">操作失败</p>
          <p className="mt-1 max-h-28 overflow-auto break-words leading-5">
            {message}
          </p>
        </div>
        <button
          type="button"
          aria-label="关闭异常提示"
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-red-700 transition hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-red-300"
          onClick={onClose}
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

function ServerPanel({
  server,
  loading,
  activeAction,
  onStart,
  onStop,
  onRestart,
}: {
  server: ServerStatus | null;
  loading: boolean;
  activeAction: ActionKey | null;
  onStart: () => void;
  onStop: () => void;
  onRestart: () => void;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>服务</CardTitle>
        <StatusBadge online={Boolean(server?.online)} />
      </CardHeader>
      <CardContent className="space-y-3">
        <InfoRow label="API" value={server?.api_url ?? "-"} />
        <InfoRow label="托管" value={server?.managed ? `PID ${server.pid}` : "否"} />
        <InfoRow label="运行时长" value={server?.uptime_seconds ? `${server.uptime_seconds}s` : "-"} />
        {server?.message ? <p className="text-sm text-zinc-500">{server.message}</p> : null}
        <div className="grid grid-cols-3 gap-2">
          <Button
            onClick={onStart}
            disabled={loading}
            loading={activeAction === "server-start"}
            loadingText="启动中"
            variant="secondary"
          >
            <Power className="h-4 w-4" />
            启动
          </Button>
          <Button
            onClick={onStop}
            disabled={loading}
            loading={activeAction === "server-stop"}
            loadingText="停止中"
            variant="outline"
          >
            <Square className="h-4 w-4" />
            停止
          </Button>
          <Button
            onClick={onRestart}
            disabled={loading}
            loading={activeAction === "server-restart"}
            loadingText="重启中"
            variant="outline"
          >
            <RotateCcw className="h-4 w-4" />
            重启
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function WorkflowPanel({
  loading,
  activeAction,
  onStart,
  onRestart,
  onClearFlows,
}: {
  loading: boolean;
  activeAction: ActionKey | null;
  onStart: () => void;
  onRestart: () => void;
  onClearFlows: () => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Workflow</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-2 sm:grid-cols-3">
        <Button
          onClick={onStart}
          disabled={loading}
          loading={activeAction === "workflow-start"}
          loadingText="启动中"
        >
          <Play className="h-4 w-4" />
          新启动
        </Button>
        <Button
          onClick={onRestart}
          disabled={loading}
          loading={activeAction === "workflow-restart"}
          loadingText="恢复中"
          variant="outline"
        >
          <RefreshCcw className="h-4 w-4" />
          安全恢复
        </Button>
        <Button
          onClick={onClearFlows}
          disabled={loading}
          loading={activeAction === "clear-flows"}
          loadingText="清理中"
          variant="destructive"
        >
          <Trash2 className="h-4 w-4" />
          清理 Flow
        </Button>
      </CardContent>
    </Card>
  );
}

function ThreadList({
  threads,
  selectedThreadId,
  loading,
  activeAction,
  activeThreadActionId,
  onSelect,
  onStop,
  onDelete,
}: {
  threads: WorkflowThread[];
  selectedThreadId: string;
  loading: boolean;
  activeAction: ActionKey | null;
  activeThreadActionId: string;
  onSelect: (threadId: string) => void;
  onStop: (threadId: string) => void;
  onDelete: (threadId: string) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>任务</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {threads.length === 0 ? (
          <p className="text-sm text-zinc-500">暂无任务。</p>
        ) : (
          threads.map((thread) => {
            const isSelected = selectedThreadId === thread.thread_id;
            const canStop =
              thread.status === "busy" ||
              Boolean(thread.progress?.running) ||
              thread.progress?.status === "running";
            const isActiveThreadAction = activeThreadActionId === thread.thread_id;
            return (
              <div
                key={thread.thread_id}
                className={`w-full select-text rounded-lg border p-3 text-left transition-all ${
                  isSelected
                    ? "border-brand-300 bg-brand-50/60 shadow-sm ring-1 ring-brand-200"
                    : "border-zinc-200 bg-white hover:border-zinc-300 hover:bg-zinc-50"
                }`}
              >
                <div className="mb-2 flex min-w-0 items-start justify-between gap-2">
                  <span className="min-w-0 truncate font-mono text-xs">
                    {thread.thread_id}
                  </span>
                  <div className="shrink-0">
                    <ThreadStopReasonBadge thread={thread} />
                  </div>
                </div>
                <div className="mb-2 grid grid-cols-3 gap-1.5 sm:flex sm:flex-wrap">
                  <Button
                    className="h-7 w-full px-2 text-xs sm:w-auto"
                    variant={isSelected ? "default" : "outline"}
                    onClick={() => onSelect(thread.thread_id)}
                  >
                    查看
                  </Button>
                  <Button
                    className="h-7 w-full px-2 text-xs sm:w-auto"
                    variant="outline"
                    title={canStop ? "停止当前 flow 的活跃 run" : "当前没有活跃 run"}
                    disabled={loading || !canStop}
                    loading={activeAction === "flow-stop" && isActiveThreadAction}
                    loadingText="停止中"
                    onClick={() => onStop(thread.thread_id)}
                  >
                    <Square className="h-3.5 w-3.5" />
                    停止
                  </Button>
                  <Button
                    className="h-7 w-full px-2 text-xs sm:w-auto"
                    variant="destructive"
                    title="删除该 flow，并恢复已锁定商品"
                    disabled={loading}
                    loading={activeAction === "flow-delete" && isActiveThreadAction}
                    loadingText="删除中"
                    onClick={() => onDelete(thread.thread_id)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    删除
                  </Button>
                </div>
                <p className="truncate text-sm text-zinc-700">
                  {thread.summary.product_title || thread.summary.product_id || "未选择产品"}
                </p>
                <div className="mt-2 grid gap-1 text-xs text-zinc-500">
                  <p className="truncate">运行状态：{threadStatusLabel(thread.status)}</p>
                  <p className="truncate">
                    运行进度：{thread.progress?.message || thread.progress?.phase_label || "-"}
                  </p>
                  <p className="truncate">当前节点：{thread.summary.current_node_label || "-"}</p>
                  {thread.progress?.elapsed_label ? (
                    <p className="truncate">已运行：{thread.progress.elapsed_label}</p>
                  ) : null}
                  <p className="truncate">停止原因：{thread.summary.stop_reason || "-"}</p>
                </div>
              </div>
            );
          })
        )}
      </CardContent>
    </Card>
  );
}

function ModelProfilesPage({ profiles }: { profiles: ModelProfile[] }) {
  const [selectedKey, setSelectedKey] = useState("");
  const selectedProfile =
    profiles.find((profile) => profile.profile_key === selectedKey) ?? profiles[0];

  useEffect(() => {
    if (profiles.length === 0) {
      if (selectedKey) {
        setSelectedKey("");
      }
      return;
    }
    if (!profiles.some((profile) => profile.profile_key === selectedKey)) {
      setSelectedKey(profiles[0].profile_key);
    }
  }, [profiles, selectedKey]);

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-normal">固定模特</h2>
          <p className="mt-1 text-sm text-zinc-500">
            当前佩戴图生成可选择的 inyourday 虚拟模特 profile。
          </p>
        </div>
        <Badge variant="secondary">{profiles.length} 个 profile</Badge>
      </div>

      {profiles.length === 0 ? (
        <Card>
          <CardContent className="p-4">
            <p className="text-sm text-zinc-500">暂无模特 profile。</p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
          <Card className="self-start overflow-hidden">
            <CardHeader className="border-b border-zinc-200 bg-zinc-50/70">
              <CardTitle>模特列表</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <div
                className="flex gap-2 overflow-x-auto p-2 lg:flex-col lg:overflow-visible"
                role="tablist"
                aria-label="固定模特"
              >
                {profiles.map((profile) => {
                  const active = profile.profile_key === selectedProfile?.profile_key;
                  return (
                    <button
                      key={profile.profile_key}
                      type="button"
                      role="tab"
                      aria-selected={active}
                      onClick={() => setSelectedKey(profile.profile_key)}
                      className={`min-w-[220px] rounded-lg border p-3 text-left shadow-sm transition-all duration-150 lg:min-w-0 ${
                        active
                          ? "border-brand-600 bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-md shadow-brand-600/25"
                          : "border-zinc-200 bg-white text-zinc-950 hover:-translate-y-px hover:border-zinc-300 hover:bg-zinc-50"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium">
                            {profile.name}
                          </p>
                          <p
                            className={`mt-1 truncate font-mono text-xs ${
                              active ? "text-zinc-300" : "text-zinc-500"
                            }`}
                          >
                            {profile.profile_key}
                          </p>
                        </div>
                        <span
                          className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${
                            profile.image_exists ? "bg-emerald-500" : "bg-amber-400"
                          }`}
                        />
                      </div>
                      <p
                        className={`mt-2 line-clamp-2 text-xs ${
                          active ? "text-zinc-200" : "text-zinc-500"
                        }`}
                      >
                        {profile.temperament || profile.ethnicity}
                      </p>
                    </button>
                  );
                })}
              </div>
            </CardContent>
          </Card>
          {selectedProfile ? <ModelProfileCard profile={selectedProfile} /> : null}
        </div>
      )}
    </section>
  );
}

function ModelProfileCard({ profile }: { profile: ModelProfile }) {
  return (
    <Card className="overflow-hidden">
      <CardHeader className="flex flex-row items-start justify-between gap-3 border-b border-zinc-200 bg-zinc-50/70">
        <div className="min-w-0">
          <CardTitle>{profile.name}</CardTitle>
          <p className="mt-1 break-all font-mono text-xs text-zinc-500">
            {profile.profile_key}
          </p>
        </div>
        <Badge variant={profile.image_exists ? "success" : "warning"}>
          {profile.image_exists ? "有图片" : "缺图片"}
        </Badge>
      </CardHeader>
      <CardContent className="grid gap-0 p-0 lg:grid-cols-[320px_1fr]">
        <div className="min-w-0 border-b border-zinc-200 p-4 lg:border-b-0 lg:border-r">
          {profile.image_path ? (
            <ZoomableImage
              className="aspect-[2/3] w-full rounded-md border border-zinc-200 bg-white object-cover"
              src={imageDisplayUrl(profile.image_path, profile.image_mtime_ns)}
              alt={profile.name}
              loading="lazy"
            />
          ) : (
            <div className="flex aspect-[2/3] w-full items-center justify-center rounded-md border border-zinc-200 bg-zinc-50 text-sm text-zinc-500">
              <Images className="mr-2 h-4 w-4" />
              暂无图片
            </div>
          )}
          <p className="mt-2 break-all font-mono text-xs text-zinc-500">
            {profile.image_path || "-"}
          </p>
        </div>

        <div className="min-w-0 space-y-4 p-4">
          <div className="grid gap-3 md:grid-cols-3">
            <InfoBlock label="身份" value={profile.ethnicity} />
            <InfoBlock label="年龄感" value={profile.age_feel} />
            <InfoBlock label="图片状态" value={profile.image_exists ? "已就绪" : "缺图片"} />
          </div>
          <div className="rounded-md border border-zinc-200 bg-zinc-50 p-3">
            <p className="text-sm font-medium">模特摘要</p>
            <p className="mt-2 break-words text-sm leading-relaxed text-zinc-700">
              {profile.summary}
            </p>
          </div>
          <KeyValuePanel
            title="关键风格"
            rows={[
              ["脸部", profile.face],
              ["皮肤", profile.skin],
              ["发型", profile.hair],
              ["气质", profile.temperament],
              ["服装", profile.wardrobe],
              ["姿态", profile.poses],
              ["表情", profile.expression],
            ]}
          />
          <div>
            <p className="mb-2 text-sm font-medium">适合饰品</p>
            <div className="flex flex-wrap gap-2">
              {profile.best_for.map((item) => (
                <Badge key={item} variant="secondary">
                  {item}
                </Badge>
              ))}
            </div>
          </div>
          <details className="rounded-md border border-zinc-200 bg-white">
            <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
              Prompt
            </summary>
            <div className="space-y-3 border-t border-zinc-200 p-3">
              <Textarea className="min-h-28 text-xs" value={profile.prompt} readOnly />
              <Textarea
                className="min-h-24 text-xs"
                value={profile.negative_prompt}
                readOnly
              />
            </div>
          </details>
        </div>
      </CardContent>
    </Card>
  );
}

function EnrouteLearningPage({
  learning,
  onClear,
  loading,
  activeAction,
}: {
  learning: EnrouteLearningResponse | null;
  onClear: () => void;
  loading: boolean;
  activeAction: ActionKey | null;
}) {
  const [category, setCategory] = useState("all");
  const [status, setStatus] = useState("all");
  const items = learning?.items ?? [];
  const categories = learning?.categories ?? [];
  const statuses = learning?.statuses ?? [];
  const visibleItems = items
    .filter((item) => category === "all" || item.enroute_category === category)
    .filter((item) => status === "all" || item.status === status)
    .sort(compareLearningItems);
  const statusOptions = [
    { status: "all", label: "全部", count: learning?.total ?? 0 },
    { status: "pending", label: "待学习", count: countByStatus(statuses, "pending") },
    { status: "learning", label: "学习中", count: countByStatus(statuses, "learning") },
    { status: "learned", label: "已学习", count: countByStatus(statuses, "learned") },
    { status: "failed", label: "失败", count: countByStatus(statuses, "failed") },
  ];

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-normal">Enroute 学习库</h2>
          <p className="mt-1 text-sm text-zinc-500">
            本地 Enroute 参考图、学习状态和已缓存逆向分析，用于后续商品匹配和模特选择。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary">{learning?.total ?? 0} 张参考图</Badge>
          <Button
            variant="destructive"
            onClick={onClear}
            disabled={loading || (learning?.total ?? 0) === 0}
            loading={activeAction === "clear-enroute"}
            loadingText="清理中"
          >
            <RotateCcw className="h-4 w-4" />
            清理学习库
          </Button>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-5">
        <InfoBlock label="参考图" value={learning?.total ?? 0} />
        <InfoBlock label="待学习" value={countByStatus(statuses, "pending")} />
        <InfoBlock label="学习中" value={countByStatus(statuses, "learning")} />
        <InfoBlock label="已学习" value={countByStatus(statuses, "learned")} />
        <InfoBlock label="失败" value={countByStatus(statuses, "failed")} />
      </div>

      <div className="space-y-2 rounded-md border border-zinc-200 bg-white p-2">
        <div className="flex flex-wrap gap-2">
          <Button
            className="h-8 px-2 text-xs"
            variant={category === "all" ? "default" : "outline"}
            onClick={() => setCategory("all")}
          >
            全部类目 ({learning?.total ?? 0})
          </Button>
          {categories.map((item) => (
            <Button
              key={item.category}
              className="h-8 px-2 text-xs"
              variant={category === item.category ? "default" : "outline"}
              onClick={() => setCategory(item.category)}
            >
              {item.category} ({item.count})
            </Button>
          ))}
        </div>
        <div className="flex flex-wrap gap-2 border-t border-zinc-100 pt-2">
          {statusOptions.map((item) => (
            <Button
              key={item.status}
              className="h-8 px-2 text-xs"
              variant={status === item.status ? "default" : "outline"}
              onClick={() => setStatus(item.status)}
            >
              {item.label} ({item.count})
            </Button>
          ))}
        </div>
      </div>

      {visibleItems.length === 0 ? (
        <Card>
          <CardContent className="p-4">
            <p className="text-sm text-zinc-500">暂无 Enroute 学习结果。</p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {visibleItems.map((item) => (
            <EnrouteLearningCard key={item.enroute_product_id} item={item} />
          ))}
        </div>
      )}
    </section>
  );
}

function EnrouteLearningCard({ item }: { item: EnrouteLearningItem }) {
  const selectedModel = asRecord(item.selected_model_profile);
  const analysis = asRecord(item.analysis || item.analysis_json);
  const statusVariant = learningStatusBadgeVariant(item.status);
  return (
    <Card className={item.status === "failed" ? "border-red-200 bg-red-50/20" : ""}>
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div className="min-w-0">
          <CardTitle>{item.enroute_title || item.enroute_product_id}</CardTitle>
          <p className="mt-1 break-all font-mono text-xs text-zinc-500">
            {item.enroute_product_id}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          <Badge variant="secondary">{item.enroute_category || "未分类"}</Badge>
          <Badge variant={statusVariant}>
            {learningStatusLabel(item.status)}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="grid gap-4 md:grid-cols-[220px_1fr]">
        <div className="min-w-0">
          <ImageValuePreview label="Enroute 参考图" path={item.image_path} />
        </div>
        <div className="min-w-0 space-y-3">
          <KeyValuePanel
            title="学习摘要"
            rows={[
              ["类目", item.enroute_category],
              ["Handle", item.enroute_handle],
              ["状态", learningStatusLabel(item.status)],
              ["尝试次数", item.learning_attempts],
              ["图片位置", item.image_position],
              ["模特", selectedModel.name || selectedModel.profile_key],
              ["学习时间", item.learned_at],
              ["错误", item.last_error],
              ["更新时间", item.updated_at],
            ]}
          />
          <div className="rounded-md border border-zinc-200 bg-zinc-50 p-3">
            <p className="text-sm font-medium">逆向摘要</p>
            <p className="mt-2 break-words text-sm leading-relaxed text-zinc-700">
              {item.summary || displayValue(analysis.summary)}
            </p>
          </div>
          {Object.keys(selectedModel).length > 0 ? (
            <KeyValuePanel
              title="选中模特"
              rows={[
                ["profile_key", selectedModel.profile_key],
                ["name", selectedModel.name],
                ["reason", selectedModel.reason],
                ["image_path", selectedModel.image_path],
              ]}
            />
          ) : null}
          <details className="rounded-md border border-zinc-200 bg-white">
            <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
              逆向分析 JSON
            </summary>
            <div className="border-t border-zinc-200 p-3">
              <CompactJson value={analysis} />
            </div>
          </details>
        </div>
      </CardContent>
    </Card>
  );
}

function PromptsPage({
  prompts,
  onRefresh,
}: {
  prompts: PromptInfo[];
  onRefresh: () => Promise<void> | void;
}) {
  const [selectedDir, setSelectedDir] = useState("");
  const selected =
    prompts.find((item) => item.dir === selectedDir) ?? prompts[0];

  if (prompts.length === 0) {
    return (
      <Card>
        <CardContent className="p-4">
          <p className="text-sm text-zinc-500">
            暂无提示词。请确认控制 API 已启动。
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <section className="grid gap-4 lg:grid-cols-[280px_1fr]">
      <Card className="self-start">
        <CardHeader>
          <CardTitle>提示词列表</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1">
          {prompts.map((item) => {
            const active = item.dir === selected.dir;
            const orderTag = item.order < 90 ? `#${item.order}` : "实验";
            return (
              <button
                key={item.dir}
                onClick={() => setSelectedDir(item.dir)}
                className={`w-full rounded-lg border p-2.5 text-left transition-all ${
                  active
                    ? "border-brand-300 bg-brand-50/60 shadow-sm ring-1 ring-brand-200"
                    : "border-zinc-200 bg-white hover:border-zinc-300 hover:bg-zinc-50"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2">
                    <span
                      className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${
                        item.order < 90
                          ? "bg-zinc-900 text-white"
                          : "bg-zinc-100 text-zinc-500"
                      }`}
                    >
                      {orderTag}
                    </span>
                    <span className="truncate text-sm font-medium">{item.label}</span>
                  </div>
                  <Badge variant={item.override != null ? "warning" : "secondary"}>
                    v{item.effective_version}
                    {item.override != null ? " 固定" : ""}
                  </Badge>
                </div>
                {item.purpose ? (
                  <p className="mt-1 line-clamp-2 text-xs text-zinc-500">
                    {item.purpose}
                  </p>
                ) : null}
                <p className="mt-1 truncate font-mono text-[10px] text-zinc-400">
                  {item.dir}
                </p>
              </button>
            );
          })}
        </CardContent>
      </Card>

      <PromptEditor
        key={`${selected.dir}:${selected.effective_version}:${selected.versions.length}`}
        prompt={selected}
        onRefresh={onRefresh}
      />
    </section>
  );
}

function PromptEditor({
  prompt,
  onRefresh,
}: {
  prompt: PromptInfo;
  onRefresh: () => Promise<void> | void;
}) {
  const [draft, setDraft] = useState(prompt.content);
  const [baseline, setBaseline] = useState(prompt.content);
  const [status, setStatus] = useState("");
  const [statusKind, setStatusKind] = useState<"ok" | "error">("ok");
  const [busy, setBusy] = useState(false);
  const dirty = draft !== baseline;

  async function run(
    action: () => Promise<PromptInfo>,
    okMessage: string,
    nextBaseline: string,
  ) {
    setBusy(true);
    setStatus("");
    try {
      await action();
      setBaseline(nextBaseline);
      setStatusKind("ok");
      setStatus(okMessage);
      await onRefresh();
    } catch (err) {
      setStatusKind("error");
      setStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div className="min-w-0">
          <CardTitle>{prompt.label}</CardTitle>
          {prompt.purpose ? (
            <p className="mt-1 text-sm text-zinc-600">{prompt.purpose}</p>
          ) : null}
          <p className="mt-1 font-mono text-xs text-zinc-400">{prompt.dir}</p>
          <p className="mt-1 text-xs text-zinc-500">
            {prompt.order < 90
              ? `工作流第 ${prompt.order} 步`
              : "未接入主工作流"}
            {prompt.node ? ` · 节点 ${prompt.node}` : ""} · 正在编辑 v
            {prompt.effective_version}
            {prompt.override != null ? "（已固定）" : "（默认最新版本）"}
          </p>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-zinc-500">生效版本：</span>
          {prompt.versions.map((version) => (
            <Button
              key={version.version}
              className="h-8 px-2 text-xs"
              variant={version.is_effective ? "default" : "outline"}
              disabled={busy || dirty || version.is_effective}
              onClick={() =>
                run(
                  () => setPromptOverride(prompt.dir, version.version),
                  `已固定到 v${version.version}`,
                  draft,
                )
              }
            >
              v{version.version}
            </Button>
          ))}
          {prompt.override != null ? (
            <Button
              className="h-8 px-2 text-xs"
              variant="ghost"
              disabled={busy || dirty}
              onClick={() =>
                run(() => setPromptOverride(prompt.dir, null), "已恢复为最新版本", draft)
              }
            >
              用最新版本
            </Button>
          ) : null}
          {dirty ? (
            <span className="text-xs text-amber-600">有未保存修改，切换版本前请先保存或重置</span>
          ) : null}
        </div>

        <Textarea
          className="min-h-[440px] font-mono text-xs leading-relaxed"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />

        <div className="flex flex-wrap items-center gap-2">
          <Button
            disabled={busy || !dirty}
            onClick={() =>
              run(
                () => savePromptContent(prompt.dir, prompt.effective_version, draft),
                `已保存到 v${prompt.effective_version}`,
                draft,
              )
            }
          >
            保存到 v{prompt.effective_version}
          </Button>
          <Button
            variant="outline"
            disabled={busy}
            onClick={() =>
              run(() => createPromptVersion(prompt.dir, draft), "已另存为新版本", draft)
            }
          >
            另存为新版本
          </Button>
          <Button
            variant="ghost"
            disabled={busy || !dirty}
            onClick={() => {
              setDraft(baseline);
              setStatus("");
            }}
          >
            重置
          </Button>
          {status ? (
            <span
              className={`text-xs ${
                statusKind === "error" ? "text-red-600" : "text-emerald-600"
              }`}
            >
              {status}
            </span>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

function ThreadDetail({
  thread,
  state,
  learning,
  resumeJson,
  setResumeJson,
  loading,
  activeAction,
  onResume,
  onOpenStudio,
}: {
  thread?: WorkflowThread;
  state: ThreadStateResponse | null;
  learning: EnrouteLearningResponse | null;
  resumeJson: string;
  setResumeJson: (value: string) => void;
  loading: boolean;
  activeAction: ActionKey | null;
  onResume: (payload: unknown, actionKey: ActionKey) => void;
  onOpenStudio: () => void;
}) {
  if (!thread) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>任务详情</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-zinc-500">选择一个任务查看详情。</p>
        </CardContent>
      </Card>
    );
  }

  const canResume = Boolean(thread.summary.can_resume);
  const progress = state?.progress ?? thread.progress;
  const grsaiReview = buildGrsaiReview(state?.state);
  const aiCalls = state?.ai_calls ?? buildAiCallsFromState(state?.state);
  const productUrl = productSourceUrl(thread, state?.state);
  const nodes = buildWorkflowNodes({
    thread,
    state: state?.state,
    learning,
    review: grsaiReview,
    canResume,
    loading,
    activeAction,
    resumeJson,
    setResumeJson,
    onResume,
  });
  const doneCount = nodes.filter((node) => node.state === "done").length;

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div className="min-w-0">
          <CardTitle>任务详情</CardTitle>
          <p className="mt-2 break-all font-mono text-xs text-zinc-500">
            {thread.thread_id}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
          {productUrl ? (
            <a
              className="inline-flex h-9 items-center justify-center gap-2 whitespace-nowrap rounded-lg border border-zinc-200 bg-white px-3.5 text-sm font-medium text-zinc-800 shadow-sm transition-all duration-150 hover:-translate-y-px hover:border-zinc-300 hover:bg-zinc-50 hover:text-zinc-950 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/60 focus-visible:ring-offset-2 active:translate-y-0 active:scale-[0.98] active:shadow-sm"
              href={productUrl}
              target="_blank"
              rel="noreferrer"
            >
              <ExternalLink className="h-4 w-4" />
              1688 原始页
            </a>
          ) : null}
          <Button variant="outline" onClick={onOpenStudio}>
            <ExternalLink className="h-4 w-4" />
            Studio
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <CurrentStatusBanner thread={thread} nodes={nodes} progress={progress} />

        {thread.summary.needs_manual_review || canResume ? (
          <section className="rounded-xl border border-amber-200 bg-amber-50/50 p-3.5 shadow-sm">
            <ManualReviewActions
              canResume={canResume}
              loading={loading}
              activeAction={activeAction}
              resumeJson={resumeJson}
              setResumeJson={setResumeJson}
              onResume={onResume}
            />
          </section>
        ) : null}

        <section className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-zinc-900">执行流程</h3>
            <Badge variant="secondary">
              {doneCount}/{nodes.length} 节点完成
            </Badge>
          </div>
          <WorkflowTimeline nodes={nodes} aiCalls={aiCalls} />
        </section>

        <details className="rounded-xl border border-zinc-200 bg-white">
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-zinc-600">
            运行进度与任务
          </summary>
          <div className="border-t border-zinc-200 p-3">
            <ProgressPanel progress={progress} threadStatus={thread.status} />
          </div>
        </details>

        <details className="rounded-xl border border-zinc-200 bg-white">
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-zinc-600">
            完整 State 调试
          </summary>
          <div className="border-t border-zinc-200 p-3">
            <StatePanel state={state?.state} />
          </div>
        </details>
      </CardContent>
    </Card>
  );
}

type OverallStatus = "running" | "queued" | "review" | "error" | "done" | "idle";

function overallThreadStatus(
  thread: WorkflowThread,
  nodes: WorkflowNode[],
  progress?: ThreadProgress,
): OverallStatus {
  if (thread.summary.needs_manual_review) {
    return "review";
  }
  if (Boolean(progress?.running)) {
    return "running";
  }
  if (Boolean(progress?.queued) || progress?.status === "pending") {
    return "queued";
  }
  if (thread.status === "busy") {
    return "running";
  }
  if (thread.status === "error" || nodes.some((node) => node.state === "error")) {
    return "error";
  }
  if (
    thread.summary.wearing_image_status === "ok" ||
    (nodes.length > 0 &&
      nodes.every((node) => node.state === "done" || node.state === "skipped"))
  ) {
    return "done";
  }
  return "idle";
}

function CurrentStatusBanner({
  thread,
  nodes,
  progress,
}: {
  thread: WorkflowThread;
  nodes: WorkflowNode[];
  progress?: ThreadProgress;
}) {
  const status = overallThreadStatus(thread, nodes, progress);
  const activeNode =
    nodes.find((node) => node.state === "active") ??
    nodes.find((node) => node.state === "error");
  const meta: Record<
    OverallStatus,
    { label: string; icon: typeof Activity; spin?: boolean; tint: string }
  > = {
    running: {
      label: "执行中",
      icon: Loader2,
      spin: true,
      tint: "border-brand-200 bg-brand-50/70 text-brand-700",
    },
    queued: {
      label: "排队中",
      icon: Clock,
      tint: "border-amber-200 bg-amber-50/70 text-amber-700",
    },
    review: {
      label: "等待人工审核",
      icon: PauseCircle,
      tint: "border-amber-200 bg-amber-50/70 text-amber-700",
    },
    error: {
      label: "异常中断",
      icon: AlertCircle,
      tint: "border-red-200 bg-red-50/70 text-red-700",
    },
    done: {
      label: "已完成",
      icon: CheckCircle2,
      tint: "border-emerald-200 bg-emerald-50/70 text-emerald-700",
    },
    idle: {
      label: "空闲",
      icon: Clock,
      tint: "border-zinc-200 bg-zinc-50 text-zinc-600",
    },
  };
  const current = meta[status];
  const Icon = current.icon;
  const nodeLabel = activeNode?.title || thread.summary.current_node_label || "";
  const detail =
    progress?.message ||
    thread.summary.stop_reason_detail ||
    thread.summary.stop_reason ||
    "—";

  return (
    <div className={`flex items-center gap-3 rounded-xl border p-3.5 shadow-sm ${current.tint}`}>
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-white/70 shadow-sm">
        <Icon className={`h-5 w-5 ${current.spin ? "animate-spin" : ""}`} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-semibold">{current.label}</span>
          {nodeLabel && status !== "done" && status !== "idle" ? (
            <span className="truncate text-sm font-medium opacity-80">
              · {nodeLabel}
            </span>
          ) : null}
        </div>
        <p className="mt-0.5 truncate text-xs opacity-80">{detail}</p>
      </div>
      {progress?.elapsed_label ? (
        <span className="shrink-0 font-mono text-xs font-medium opacity-75">
          {progress.elapsed_label}
        </span>
      ) : null}
    </div>
  );
}

function NodeAiCall({ call }: { call: AiCallSummary }) {
  const isImage = call.kind === "image_ai";
  const input = asRecord(call.input);
  const output = asRecord(call.output);
  const promptText = stringValue(output.prompt || input.prompt);
  const providers = arrayValue(call.providers)
    .map((provider) => {
      const record = asRecord(provider);
      return stringValue(record.name) || stringValue(record.api_base);
    })
    .filter(Boolean)
    .join(" / ");
  const summaryRows = aiCallOutputSummary(call).filter(
    ([, value]) => !isEmptyDisplay(value),
  );
  const hasInput = Object.keys(input).length > 0;
  const hasOutput = Object.keys(output).length > 0;

  return (
    <div className="space-y-3 rounded-xl border border-zinc-200 bg-zinc-50/60 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span
            className={`inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md ${
              isImage ? "bg-violet-100 text-violet-700" : "bg-sky-100 text-sky-700"
            }`}
          >
            {isImage ? (
              <ImageIcon className="h-3.5 w-3.5" />
            ) : (
              <Cpu className="h-3.5 w-3.5" />
            )}
          </span>
          <span className="truncate text-sm font-medium text-zinc-800">
            {isImage ? "图片 AI 调用" : "LLM 调用"}
          </span>
        </div>
        <Badge variant={aiCallStatusVariant(call.status)}>
          {aiCallStatusLabel(call.status)}
        </Badge>
      </div>

      {call.model || providers ? (
        <p className="text-xs text-zinc-500">
          {call.model ? (
            <>
              模型 <span className="font-medium text-zinc-700">{call.model}</span>
            </>
          ) : null}
          {call.model && providers ? " · " : null}
          {providers ? (
            <>
              Provider{" "}
              <span className="font-medium text-zinc-700">{providers}</span>
            </>
          ) : null}
        </p>
      ) : null}

      {call.images.length > 0 ? (
        <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
          {call.images.map((image) => (
            <ImagePreview
              key={`${call.key}-${image.role}-${image.path}`}
              label={`${image.label} · ${aiImageRoleLabel(image.role)}`}
              path={image.path}
              url={imageDisplayUrl(image.path)}
            />
          ))}
        </div>
      ) : null}

      {promptText ? (
        <PromptBlock
          label={isImage ? "生图提示词 Prompt" : "提示词 Prompt"}
          text={promptText}
        />
      ) : null}

      {summaryRows.length > 0 ? (
        <div className="space-y-2">
          <span className="text-xs font-medium text-zinc-500">输出结果</span>
          <div className="grid gap-2 sm:grid-cols-2">
            {summaryRows.map(([label, value]) => (
              <InfoBlock key={label} label={label} value={value} />
            ))}
          </div>
        </div>
      ) : null}

      <div className="flex flex-wrap gap-1.5">
        {hasInput ? <JsonModalButton label="输入 JSON" value={input} /> : null}
        {hasOutput ? <JsonModalButton label="输出 JSON" value={output} /> : null}
        {Object.keys(call.prompts || {}).length > 0 ? (
          <JsonModalButton label="Prompt 版本" value={call.prompts} />
        ) : null}
        <JsonModalButton label="原始 checkpoint" value={call.raw_checkpoint} />
      </div>
    </div>
  );
}

function PromptBlock({ label, text }: { label: string; text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-zinc-500">{label}</span>
        <span className="text-[10px] text-zinc-400">{text.length} 字符</span>
      </div>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="group block w-full rounded-lg border border-zinc-200 bg-white p-3 text-left transition-colors hover:border-brand-300 hover:bg-brand-50/30"
      >
        <p className="line-clamp-4 whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-zinc-600">
          {text}
        </p>
        <span className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-brand-600 transition-colors group-hover:text-brand-700">
          <Maximize2 className="h-3.5 w-3.5" />
          查看完整提示词
        </span>
      </button>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title={label}
        description={`${text.length} 字符`}
        footer={
          <>
            <CopyButton text={text} />
            <Button variant="outline" onClick={() => setOpen(false)}>
              关闭
            </Button>
          </>
        }
      >
        <pre className="whitespace-pre-wrap break-words rounded-lg bg-zinc-950 p-4 font-mono text-xs leading-relaxed text-zinc-50">
          {text}
        </pre>
      </Dialog>
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      variant="secondary"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        } catch {
          /* clipboard unavailable */
        }
      }}
    >
      {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
      {copied ? "已复制" : "复制"}
    </Button>
  );
}

function JsonModalButton({ label, value }: { label: string; value: unknown }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1 rounded-md border border-zinc-200 bg-white px-2 py-1 text-xs font-medium text-zinc-600 transition-colors hover:border-brand-300 hover:text-brand-700"
      >
        <Maximize2 className="h-3 w-3" />
        {label}
      </button>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title={label}
        footer={
          <Button variant="outline" onClick={() => setOpen(false)}>
            关闭
          </Button>
        }
      >
        <JsonViewer value={value} />
      </Dialog>
    </>
  );
}

function aiCallStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    ok: "成功",
    success: "成功",
    succeeded: "成功",
    failed: "失败",
    error: "失败",
    running: "执行中",
    in_progress: "执行中",
    skipped: "已跳过",
    pending: "等待中",
  };
  return labels[status] ?? (status || "-");
}

function aiCallOutputSummary(call: AiCallSummary): Array<[string, unknown]> {
  const output = asRecord(call.output);
  if (call.key === "detect_size_reference") {
    return [
      ["产品合格", output.is_product_qualified],
      ["失败项", output.failed_checks],
      ["可判断尺寸", output.can_judge_size],
      ["尺寸图编号", output.size_reference_image_number],
      ["主图编号", output.main_image_number],
      ["原因", output.reason],
    ];
  }
  if (call.key.startsWith("learn_enroute_reference")) {
    return [
      ["缓存", output.cache],
      ["Enroute ID", output.enroute_product_id],
      ["类目", output.category],
      ["摘要", output.summary],
    ];
  }
  if (call.key === "select_wearing_style_profile") {
    const selectedModel = asRecord(output.selected_model_profile);
    const selection = asRecord(output.selection);
    return [
      ["Enroute ID", output.enroute_product_id],
      ["类目", output.category],
      ["模特", selectedModel.name || selectedModel.profile_key],
      ["选择依据", selection.reason],
    ];
  }
  if (call.key === "compile_wearing_generation_prompt") {
    const selectedModel = asRecord(output.selected_model_profile);
    return [
      ["原因", output.reason],
      ["Prompt 长度", output.prompt_length],
      ["输入图", arrayValue(output.input_images).length],
      ["模特", selectedModel.name || selectedModel.profile_key],
      ["Enroute 图", output.enroute_reference_image_path],
    ];
  }
  if (call.key.startsWith("generate_wearing_image")) {
    const imageGeneration = asRecord(output.image_generation);
    return [
      ["原因", output.reason],
      ["Attempt", output.attempt],
      ["Grsai 任务", imageGeneration.id],
      ["Grsai 状态", imageGeneration.status],
      ["进度", imageGeneration.progress],
      ["生成图", output.generated_image_path || output.generated_image_url],
    ];
  }
  return [
    ["状态", output.status],
    ["原因", output.reason],
  ];
}

function aiCallStatusVariant(status: string) {
  if (status === "ok" || status === "succeeded" || status === "success") {
    return "success";
  }
  if (status === "failed" || status === "error") {
    return "danger";
  }
  if (status === "running" || status === "in_progress") {
    return "warning";
  }
  return "secondary";
}

function aiImageRoleLabel(role: string) {
  const labels: Record<string, string> = {
    input: "输入",
    output: "输出",
    context: "上下文",
  };
  return labels[role] ?? role;
}

function ManualReviewActions({
  canResume,
  loading,
  activeAction,
  resumeJson,
  setResumeJson,
  onResume,
}: {
  canResume: boolean;
  loading: boolean;
  activeAction: ActionKey | null;
  resumeJson: string;
  setResumeJson: (value: string) => void;
  onResume: (payload: unknown, actionKey: ActionKey) => void;
}) {
  const disabled = loading || !canResume;
  const [parseError, setParseError] = useState("");

  function submitCustomJson() {
    try {
      const payload = JSON.parse(resumeJson);
      setParseError("");
      onResume(payload, "resume-custom");
    } catch (err) {
      setParseError(err instanceof Error ? err.message : "无效的 JSON");
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm font-medium">审核动作</p>
      <div className="grid gap-2 sm:grid-cols-3">
        <Button
          onClick={() => onResume({ action: "approve" }, "resume-approve")}
          disabled={disabled}
          loading={activeAction === "resume-approve"}
          loadingText="提交中"
        >
          Approve
        </Button>
        <Button
          variant="outline"
          onClick={() => onResume({ action: "regenerate" }, "resume-regenerate")}
          disabled={disabled}
          loading={activeAction === "resume-regenerate"}
          loadingText="提交中"
        >
          Regenerate
        </Button>
        <Button
          variant="destructive"
          onClick={() => onResume({ action: "reject" }, "resume-reject")}
          disabled={disabled}
          loading={activeAction === "resume-reject"}
          loadingText="提交中"
        >
          Reject
        </Button>
      </div>
      <details className="rounded-md border border-zinc-200 bg-zinc-50">
        <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
          自定义 JSON
        </summary>
        <div className="space-y-2 border-t border-zinc-200 p-3">
          <Textarea
            value={resumeJson}
            onChange={(event) => setResumeJson(event.target.value)}
          />
          {parseError ? (
            <p className="text-xs text-red-600">JSON 解析失败：{parseError}</p>
          ) : null}
          <Button
            variant="outline"
            onClick={submitCustomJson}
            disabled={disabled}
            loading={activeAction === "resume-custom"}
            loadingText="提交中"
          >
            <PauseCircle className="h-4 w-4" />
            提交自定义 JSON
          </Button>
        </div>
      </details>
    </div>
  );
}

type WorkflowNodeState = "done" | "active" | "pending" | "error" | "skipped";

type WorkflowNode = {
  id: string;
  title: string;
  state: WorkflowNodeState;
  summary: string;
  rows?: Array<[string, unknown]>;
  content?: ReactNode;
};

function aiCallNodeId(key: string): string {
  if (key.startsWith("learn_enroute_reference")) {
    return "learn_enroute_profiles";
  }
  if (key.startsWith("generate_wearing_image")) {
    return "generate_wearing_image";
  }
  return key;
}

function aiCallsForNode(
  nodeId: string,
  calls: AiCallSummary[],
): AiCallSummary[] {
  return calls.filter((call) => aiCallNodeId(call.key) === nodeId);
}

function WorkflowTimeline({
  nodes,
  aiCalls,
}: {
  nodes: WorkflowNode[];
  aiCalls: AiCallSummary[];
}) {
  return (
    <ol className="relative">
      {nodes.map((node, index) => (
        <TimelineNode
          key={node.id}
          node={node}
          calls={aiCallsForNode(node.id, aiCalls)}
          isLast={index === nodes.length - 1}
        />
      ))}
    </ol>
  );
}

function NodeStateIcon({ state }: { state: WorkflowNodeState }) {
  if (state === "done") {
    return <Check className="h-3.5 w-3.5" />;
  }
  if (state === "error") {
    return <AlertCircle className="h-3.5 w-3.5" />;
  }
  if (state === "skipped") {
    return <Minus className="h-3.5 w-3.5" />;
  }
  if (state === "active") {
    return <span className="h-2 w-2 rounded-full bg-white" />;
  }
  return <span className="h-1.5 w-1.5 rounded-full bg-zinc-400" />;
}

function nodeDotBg(state: WorkflowNodeState) {
  const classes: Record<WorkflowNodeState, string> = {
    done: "bg-emerald-500 text-white",
    active: "bg-brand-500 text-white",
    pending: "bg-white",
    error: "bg-red-500 text-white",
    skipped: "bg-zinc-300 text-white",
  };
  return classes[state];
}

function TimelineNode({
  node,
  calls,
  isLast,
}: {
  node: WorkflowNode;
  calls: AiCallSummary[];
  isLast: boolean;
}) {
  const showDetail = node.state !== "pending" && node.state !== "skipped";
  const rows = showDetail
    ? (node.rows ?? []).filter(([, value]) => !isEmptyDisplay(value))
    : [];
  const isActive = node.state === "active";
  const isError = node.state === "error";

  return (
    <li className="relative flex gap-3 pb-3 last:pb-0">
      {!isLast ? (
        <span
          className="absolute left-[13px] top-7 bottom-0 w-px bg-zinc-200"
          aria-hidden
        />
      ) : null}
      <span
        className={`relative z-10 mt-0.5 flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full border border-zinc-200 ring-4 ring-white ${nodeDotBg(
          node.state,
        )} ${isActive ? "animate-pulse" : ""}`}
      >
        <NodeStateIcon state={node.state} />
      </span>

      <div
        className={`min-w-0 flex-1 rounded-xl border p-3 transition-colors ${
          isActive
            ? "border-brand-200 bg-brand-50/40 shadow-sm ring-1 ring-brand-100"
            : isError
              ? "border-red-200 bg-red-50/40"
              : "border-zinc-200 bg-white"
        }`}
      >
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <h4 className="text-sm font-semibold text-zinc-900">{node.title}</h4>
            <p className="mt-0.5 text-sm text-zinc-600">{node.summary}</p>
          </div>
          <Badge variant={nodeBadgeVariant(node.state)}>
            {nodeStateLabel(node.state)}
          </Badge>
        </div>

        {rows.length ? (
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {rows.map(([label, value]) => (
              <InfoBlock key={label} label={label} value={value} />
            ))}
          </div>
        ) : null}

        {calls.length > 0 ? (
          <div className="mt-3 space-y-2.5">
            {calls.map((call) => (
              <NodeAiCall key={call.key} call={call} />
            ))}
          </div>
        ) : null}

        {showDetail && node.content ? (
          <details className="mt-3 rounded-lg border border-zinc-200 bg-white">
            <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-zinc-500">
              更多详情
            </summary>
            <div className="border-t border-zinc-200 p-3">{node.content}</div>
          </details>
        ) : null}
      </div>
    </li>
  );
}

function isEmptyDisplay(value: unknown): boolean {
  if (value === null || value === undefined || value === "") {
    return true;
  }
  if (typeof value === "string") {
    const text = value.trim();
    return text === "" || text === "-";
  }
  if (Array.isArray(value)) {
    return value.length === 0;
  }
  return false;
}


function buildWorkflowNodes({
  thread,
  state,
  learning,
  review,
  canResume,
  loading,
  activeAction,
  resumeJson,
  setResumeJson,
  onResume,
}: {
  thread: WorkflowThread;
  state: unknown;
  learning: EnrouteLearningResponse | null;
  review: GrsaiReview;
  canResume: boolean;
  loading: boolean;
  activeAction: ActionKey | null;
  resumeJson: string;
  setResumeJson: (value: string) => void;
  onResume: (payload: unknown, actionKey: ActionKey) => void;
}): WorkflowNode[] {
  const root = asRecord(state);
  const values = asRecord(root.values);
  const product = asRecord(values.selected_product);
  const rawdata = asRecord(product.rawdata);
  const mainImage = asRecord(values.main_image_result);
  const sizeReference = asRecord(values.size_reference_result);
  const enrouteReference = asRecord(values.enroute_reference_result);
  const enrouteLearning = asRecord(values.enroute_learning_result);
  const enrouteAnalysis = asRecord(values.enroute_analysis_result);
  const wearingStyleSelectionRaw = asRecord(values.wearing_style_selection_result);
  const wearingStyleSelection = Object.keys(wearingStyleSelectionRaw).length
    ? wearingStyleSelectionRaw
    : enrouteAnalysis;
  const wearingPrompt = asRecord(values.wearing_generation_prompt_result);
  const wearing = asRecord(values.wearing_image_result);
  const nextNodes = Array.isArray(root.next) ? root.next.map(String) : thread.summary.next ?? [];
  const currentNode = nextNodes[0] || "";
  const failedProduct = asRecord(values.failed_product);
  const isFailed = Boolean(failedProduct.reason);
  const styleSelectionPayload = asRecord(wearingStyleSelection.selection);
  const selectedModel = resolvedSelectedModel(wearingStyleSelection);
  const plannedLearningRows = learningRowsForReferencePlan(enrouteReference, learning);
  const learningRowCounts = countLearningItemsByStatus(plannedLearningRows);
  const categoryLearningRows = learningRowsForCategory(
    stringValue(enrouteLearning.category || enrouteReference.category),
    learning,
  );
  const categoryLearningCounts = countLearningItemsByStatus(categoryLearningRows);

  return [
    {
      id: "load_candidates",
      title: "选择商品",
      state: product.product_id ? "done" : nodeState("load_candidates", currentNode, nextNodes, isFailed),
      summary: product.product_id ? "已锁定当前商品。" : "等待选择可处理商品。",
      rows: [
        ["产品 ID", product.product_id || thread.summary.product_id],
        ["平台", product.platform || thread.summary.platform],
        ["商品状态", product.status || thread.summary.product_status],
        ["标题", rawdata.title || thread.summary.product_title],
      ],
    },
    {
      id: "merge_main_images",
      title: "准备主图",
      state: statusToNodeState(mainImage.status, "merge_main_images", currentNode, nextNodes, isFailed),
      summary: mainImage.status
        ? `主图聚合状态：${displayValue(mainImage.status)}。`
        : "等待下载并合并商品主图。",
      rows: [
        ["合图", mainImage.path],
        ["图片数量", mainImage.source_image_count],
        ["临时文件", mainImage.temporary],
      ],
    },
    {
      id: "detect_size_reference",
      title: "产品合格性检测",
      state: statusToNodeState(sizeReference.status, "detect_size_reference", currentNode, nextNodes, isFailed),
      summary: sizeReference.reason
        ? displayValue(sizeReference.reason)
        : "检测商品是否具备继续生成穿戴图所需的合格素材。",
      rows: [
        ["状态", sizeReference.status],
        ["产品合格", sizeReference.is_product_qualified],
        ["失败项", sizeReference.failed_checks],
        ["可判断尺寸", sizeReference.can_judge_size],
        ["尺寸参考图编号", sizeReference.size_reference_image_number],
        ["主图编号", sizeReference.main_image_number],
      ],
      content: <ProductQualificationPanel result={sizeReference} />,
    },
    {
      id: "select_enroute_reference",
      title: "选择 Enroute 参考图",
      state: statusToNodeState(enrouteReference.status, "select_enroute_reference", currentNode, nextNodes, isFailed),
      summary: enrouteReference.reason
        ? reasonLabel(displayValue(enrouteReference.reason))
        : "按商品类目读取 Enroute 同类目参考图库。",
      rows: [
        ["状态", enrouteReference.status],
        ["类目", enrouteReference.category],
        ["参考图数量", enrouteReference.reference_count],
        ["已有缓存", enrouteReference.cached_analysis_count],
        ["未学习数量", enrouteReference.unlearned_count],
        ["本次学习", enrouteReference.learning_count],
      ],
      content: <EnrouteReferencePanel reference={enrouteReference} />,
    },
    {
      id: "learn_enroute_profiles",
      title: "学习 Enroute profile",
      state: statusToNodeState(enrouteLearning.status, "learn_enroute_profiles", currentNode, nextNodes, isFailed),
      summary: enrouteLearning.reason
        ? reasonLabel(displayValue(enrouteLearning.reason))
        : "按数据库学习表串行推进本次计划：缓存少于 5 学 5 张，缓存达到 5 后学 1 张。",
      rows: [
        ["状态", enrouteLearning.status],
        ["类目", enrouteLearning.category || enrouteReference.category],
        ["本次计划", plannedLearningRows.length || enrouteReference.learning_count],
        ["计划待学习", learningRowCounts.pending],
        ["计划学习中", learningRowCounts.learning],
        ["计划已学习", learningRowCounts.learned],
        ["计划失败", learningRowCounts.failed],
        ["学习后缓存", enrouteLearning.cached_analysis_count_after_learning],
      ],
      content: (
        <EnrouteLearningPanel
          reference={enrouteReference}
          learning={enrouteLearning}
          plannedRows={plannedLearningRows}
          categoryCounts={categoryLearningCounts}
        />
      ),
    },
    {
      id: "select_wearing_style_profile",
      title: "选择风格与模特",
      state: statusToNodeState(wearingStyleSelection.status, "select_wearing_style_profile", currentNode, nextNodes, isFailed),
      summary: displayValue(
        styleSelectionPayload.reason ||
          wearingStyleSelection.summary ||
          enrouteReference.reason ||
          "从已学习 Enroute profile 和模特摘要中选择风格组合。",
      ),
      rows: [
        ["状态", wearingStyleSelection.status],
        ["Enroute", wearingStyleSelection.enroute_product_id],
        ["类目", wearingStyleSelection.category],
        ["模特", selectedModel.name || selectedModel.profile_key],
        ["选择依据", styleSelectionPayload.reason],
      ],
      content: (
        <WearingStyleSelectionPanel
          reference={enrouteReference}
          selection={wearingStyleSelection}
        />
      ),
    },
    {
      id: "compile_wearing_generation_prompt",
      title: "编排生图提示词",
      state: statusToNodeState(wearingPrompt.status, "compile_wearing_generation_prompt", currentNode, nextNodes, isFailed),
      summary: wearingPrompt.reason
        ? reasonLabel(displayValue(wearingPrompt.reason))
        : "加载实际 Enroute profile、模特 profile、产品图和尺寸图，生成生图提示词。",
      rows: [
        ["状态", wearingPrompt.status],
        ["输入图数量", arrayValue(wearingPrompt.input_images).length],
        ["提示词长度", stringValue(wearingPrompt.prompt).length],
        ["标记主图", wearingPrompt.marked_main_image_path],
        ["标记尺寸图", wearingPrompt.marked_size_reference_image_path],
        [
          "模特",
          resolvedSelectedModel(wearingPrompt).name ||
            resolvedSelectedModel(wearingPrompt).profile_key,
        ],
      ],
      content: (
        <WearingPromptPanel
          result={wearingPrompt}
        />
      ),
    },
    {
      id: "generate_wearing_image",
      title: "Grsai 生成穿戴图",
      state: statusToNodeState(wearing.status, "generate_wearing_image", currentNode, nextNodes, isFailed),
      summary: wearing.reason
        ? reasonLabel(displayValue(wearing.reason))
        : "调用 Grsai 生成穿戴图。",
      rows: [
        ["状态", wearing.status],
        ["Attempt", wearing.attempt],
        ["生成图", wearing.generated_image_path || thread.summary.generated_image_path],
        ["Grsai 任务", asRecord(wearing.image_generation).id],
      ],
      content: (
        <GrsaiNodePanel
          review={review}
          canResume={canResume}
          loading={loading}
          activeAction={activeAction}
          onRetry={() => onResume({ action: "regenerate" }, "resume-regenerate")}
        />
      ),
    },
    {
      id: "wait_manual_review",
      title: "人工审核",
      state: thread.summary.needs_manual_review
        ? "active"
        : thread.summary.wearing_image_status === "ok"
          ? "done"
          : nodeState("wait_manual_review", currentNode, nextNodes, isFailed),
      summary: thread.summary.stop_reason_detail || thread.summary.stop_reason || "等待审核动作。",
      rows: [
        ["是否需要审核", thread.summary.needs_manual_review ? "是" : "否"],
        ["暂停数量", thread.summary.interrupt_count],
        ["停止原因", thread.summary.stop_reason],
      ],
      content: (
        <ManualReviewActions
          canResume={canResume}
          loading={loading}
          activeAction={activeAction}
          resumeJson={resumeJson}
          setResumeJson={setResumeJson}
          onResume={onResume}
        />
      ),
    },
  ];
}

function nodeState(
  nodeId: string,
  currentNode: string,
  nextNodes: string[],
  isFailed: boolean,
): WorkflowNodeState {
  if (isFailed && currentNode === nodeId) {
    return "error";
  }
  if (currentNode === nodeId) {
    return "active";
  }
  if (!currentNode && nextNodes.length === 0) {
    return "pending";
  }
  return "pending";
}

function statusToNodeState(
  status: unknown,
  nodeId: string,
  currentNode: string,
  nextNodes: string[],
  isFailed: boolean,
): WorkflowNodeState {
  const value = String(status || "");
  if (value === "ok" || value === "succeeded") {
    return "done";
  }
  if (value === "skipped") {
    return "skipped";
  }
  if (value === "failed" || value === "error") {
    return "error";
  }
  if (isFailed) {
    return currentNode === nodeId || !currentNode ? "error" : "pending";
  }
  return nodeState(nodeId, currentNode, nextNodes, isFailed);
}

function nodeBadgeVariant(state: WorkflowNodeState) {
  if (state === "done") {
    return "success";
  }
  if (state === "active") {
    return "warning";
  }
  if (state === "error") {
    return "danger";
  }
  return "secondary";
}

function nodeStateLabel(state: WorkflowNodeState) {
  const labels: Record<WorkflowNodeState, string> = {
    done: "已完成",
    active: "当前节点",
    pending: "未开始",
    error: "异常",
    skipped: "已跳过",
  };
  return labels[state];
}

function reasonLabel(reason: string) {
  const labels: Record<string, string> = {
    wearing_image_generated: "穿戴图已生成。",
    selected_main_or_size_reference_missing: "缺少主图或尺寸参考图。",
    main_image_not_ready: "主图尚未准备好。",
    no_matching_enroute_reference: "没有找到同类目 Enroute 参考图。",
    reference_not_ready: "Enroute 参考选择尚未完成。",
    enroute_category_missing: "缺少 Enroute 类目。",
    no_cached_enroute_analysis: "没有可用的 Enroute profile 缓存。",
    selected_product_images_missing: "缺少已选产品主图或尺寸参考图。",
    style_profile_not_ready: "风格与模特选择尚未完成。",
    selected_enroute_or_model_profile_missing: "缺少选中的 Enroute profile 或模特 profile。",
    wearing_generation_prompt_compiled: "生图提示词已编排。",
    compiled_prompt_or_input_images_missing: "缺少已编排提示词或输入图。",
    size_reference_unusable: "尺寸参考不可用。",
    product_qualification: "产品合格性检测未通过。",
  };
  return labels[reason] ?? reason;
}

type ReviewImage = {
  label: string;
  path: string;
  url: string;
};

type GrsaiReview = {
  prompt: string;
  generatedImagePath: string;
  generatedImageUrl: string;
  images: ReviewImage[];
  imageGeneration: Record<string, unknown>;
};

function ProductQualificationPanel({
  result,
}: {
  result: Record<string, unknown>;
}) {
  const selectedImages = asRecord(result.selected_images);
  const mainImage = asRecord(selectedImages.main_image);
  const sizeReferenceImage = asRecord(selectedImages.size_reference_image);
  const qualificationChecks = asRecord(result.qualification_checks);
  const mainImagePath = stringValue(mainImage.path);
  const sizeReferencePath = stringValue(sizeReferenceImage.path);
  const hasRaw = Object.keys(result).length > 0;

  return (
    <div className="space-y-3">
      <div className="grid gap-3 lg:grid-cols-2">
        <KeyValuePanel
          title="检测结果"
          rows={[
            ["状态", result.status],
            ["产品合格", result.is_product_qualified],
            ["失败项", result.failed_checks],
            ["失败类型", result.failure_type],
            ["失败详情", result.failure_detail],
            ["原因", result.reason],
          ]}
        />
        <KeyValuePanel
          title="尺寸推断参考"
          rows={[
            ["可判断尺寸", result.can_judge_size],
            ["候选图片编号", result.image_numbers],
            ["主图编号", result.main_image_number],
            ["尺寸参考图编号", result.size_reference_image_number],
            ["主图路径", mainImage.path],
            ["尺寸参考图路径", sizeReferenceImage.path],
          ]}
        />
      </div>

      {mainImagePath || sizeReferencePath ? (
        <div className="grid gap-3 lg:grid-cols-2">
          {mainImagePath ? (
            <ImagePreview
              label={`产品主图 ${displayValue(mainImage.number)}`}
              path={mainImagePath}
              url={imageDisplayUrl(mainImagePath)}
            />
          ) : null}
          {sizeReferencePath ? (
            <ImagePreview
              label={`尺寸参考图 ${displayValue(sizeReferenceImage.number)}`}
              path={sizeReferencePath}
              url={imageDisplayUrl(sizeReferencePath)}
            />
          ) : null}
        </div>
      ) : null}

      {Object.keys(qualificationChecks).length > 0 ? (
        <details className="rounded-md border border-zinc-200 bg-white">
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
            合格性检查项
          </summary>
          <div className="border-t border-zinc-200 p-3">
            <CompactJson value={qualificationChecks} />
          </div>
        </details>
      ) : null}

      {hasRaw ? (
        <details className="rounded-md border border-zinc-200 bg-white">
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
            产品合格性原始结果
          </summary>
          <div className="border-t border-zinc-200 p-3">
            <CompactJson value={result} />
          </div>
        </details>
      ) : null}
    </div>
  );
}

function EnrouteReferencePanel({
  reference,
}: {
  reference: Record<string, unknown>;
}) {
  const learningReferences = arrayValue(reference.learning_references);
  const selectedImagePath = stringValue(reference.selected_image_path);
  const hasRaw = Object.keys(reference).length > 0;

  return (
    <div className="space-y-3">
      <KeyValuePanel
        title="参考图库"
        rows={[
          ["状态", reference.status],
          ["类目", reference.category],
          ["参考图数量", reference.reference_count],
          ["已有缓存", reference.cached_analysis_count],
          ["未学习数量", reference.unlearned_count],
          ["本次计划学习", reference.learning_count],
          ["选中 Enroute", reference.selected_enroute_product_id],
          ["选择依据", reference.selection_reason],
        ]}
      />

      {selectedImagePath ? (
        <ImagePreview
          label="选中 Enroute 参考图"
          path={selectedImagePath}
          url={imageDisplayUrl(selectedImagePath)}
        />
      ) : null}

      {learningReferences.length > 0 ? (
        <EnrouteRecordList title="本次待学习参考" items={learningReferences} />
      ) : null}

      {hasRaw ? (
        <details className="rounded-md border border-zinc-200 bg-white">
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
            Enroute 参考选择原始结果
          </summary>
          <div className="border-t border-zinc-200 p-3">
            <CompactJson value={reference} />
          </div>
        </details>
      ) : null}
    </div>
  );
}

function EnrouteLearningPanel({
  reference,
  learning,
  plannedRows,
  categoryCounts,
}: {
  reference: Record<string, unknown>;
  learning: Record<string, unknown>;
  plannedRows: EnrouteLearningItem[];
  categoryCounts: LearningStatusCounts;
}) {
  const plannedIds = new Set(plannedRows.map((item) => item.enroute_product_id));
  const fallbackReferences = arrayValue(reference.learning_references).filter((item) => {
    const productId = stringValue(asRecord(item).product_id || asRecord(item).enroute_product_id);
    return productId && !plannedIds.has(productId);
  });
  const hasRaw = Object.keys(reference).length > 0 || Object.keys(learning).length > 0;

  return (
    <div className="space-y-3">
      <div className="grid gap-3 lg:grid-cols-2">
        <KeyValuePanel
          title="学习计划"
          rows={[
            ["类目", learning.category || reference.category],
            ["参考总数", reference.reference_count],
            ["缓存数", reference.cached_analysis_count],
            ["未学习数量", reference.unlearned_count],
            ["本次计划", plannedRows.length || reference.learning_count],
          ]}
        />
        <KeyValuePanel
          title="数据库学习状态"
          rows={[
            ["状态", learning.status],
            ["原因", learning.reason],
            ["待学习", categoryCounts.pending],
            ["学习中", categoryCounts.learning],
            ["已学习", categoryCounts.learned],
            ["失败", categoryCounts.failed],
            ["学习后缓存数", learning.cached_analysis_count_after_learning],
          ]}
        />
      </div>

      {plannedRows.length > 0 ? (
        <LearningReferenceList title="本次计划参考" items={plannedRows} />
      ) : null}
      {fallbackReferences.length > 0 ? (
        <EnrouteRecordList title="本次计划参考（state）" items={fallbackReferences} />
      ) : null}

      {hasRaw ? (
        <details className="rounded-md border border-zinc-200 bg-white">
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
            Enroute 学习原始结果
          </summary>
          <div className="border-t border-zinc-200 p-3">
            <CompactJson value={{ reference, learning }} />
          </div>
        </details>
      ) : null}
    </div>
  );
}

function WearingStyleSelectionPanel({
  reference,
  selection,
}: {
  reference: Record<string, unknown>;
  selection: Record<string, unknown>;
}) {
  const analysisJson = asRecord(selection.analysis);
  const selectionPayload = asRecord(selection.selection);
  const selectedModel = resolvedSelectedModel(selection);
  const selectedImagePath = stringValue(
    selection.reference_image_path ||
      selection.enroute_reference_image_path ||
      reference.selected_image_path,
  );
  const selectedModelImagePath = stringValue(selectedModel.image_path);
  const summary = displayValue(selection.summary || analysisJson.summary);
  const hasRaw = Object.keys(selection).length > 0;

  return (
    <div className="space-y-3">
      <div className="grid gap-3 lg:grid-cols-2">
        <KeyValuePanel
          title="选中 Enroute profile"
          rows={[
            ["状态", selection.status],
            ["Enroute ID", selection.enroute_product_id],
            ["类目", selection.category || reference.category],
            ["选择来源", selection.cache || selection.checkpoint],
            ["参考图", selection.reference_image_path || reference.selected_image_path],
            ["选择依据", selectionPayload.reason || reference.selection_reason],
          ]}
        />
        <KeyValuePanel
          title="选中模特 profile"
          rows={[
            ["profile_key", selectedModel.profile_key],
            ["name", selectedModel.name],
            ["summary", selectedModel.summary],
            ["image_path", selectedModel.image_path],
          ]}
        />
      </div>

      {summary !== "-" ? (
        <div className="rounded-md border border-zinc-200 bg-zinc-50 p-3">
          <p className="text-sm font-medium">Enroute profile 摘要</p>
          <p className="mt-2 break-words text-sm leading-relaxed text-zinc-700">
            {summary}
          </p>
        </div>
      ) : null}

      {selectedImagePath || selectedModelImagePath ? (
        <div className="grid gap-3 lg:grid-cols-2">
          {selectedImagePath ? (
            <ImagePreview
              label="选中 Enroute 参考图"
              path={selectedImagePath}
              url={imageDisplayUrl(selectedImagePath)}
            />
          ) : null}
          {selectedModelImagePath ? (
            <ImagePreview
              label="选中固定模特"
              path={selectedModelImagePath}
              url={imageDisplayUrl(selectedModelImagePath)}
            />
          ) : null}
        </div>
      ) : null}

      {Object.keys(selectionPayload).length > 0 ? (
        <details className="rounded-md border border-zinc-200 bg-white">
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
            风格与模特选择 JSON
          </summary>
          <div className="border-t border-zinc-200 p-3">
            <CompactJson value={selectionPayload} />
          </div>
        </details>
      ) : null}

      {Object.keys(analysisJson).length > 0 ? (
        <details className="rounded-md border border-zinc-200 bg-white">
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
            选中 Enroute profile JSON
          </summary>
          <div className="border-t border-zinc-200 p-3">
            <CompactJson value={analysisJson} />
          </div>
        </details>
      ) : null}

      {hasRaw ? (
        <details className="rounded-md border border-zinc-200 bg-white">
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
            风格选择原始结果
          </summary>
          <div className="border-t border-zinc-200 p-3">
            <CompactJson value={selection} />
          </div>
        </details>
      ) : null}
    </div>
  );
}

function WearingPromptPanel({ result }: { result: Record<string, unknown> }) {
  const selectedModel = resolvedSelectedModel(result);
  const inputImages = arrayValue(result.input_images)
    .map((item) => stringValue(item))
    .filter(Boolean);
  const prompt = stringValue(result.prompt);
  const enrouteImagePath = stringValue(result.enroute_reference_image_path);
  const hasRaw = Object.keys(result).length > 0;

  return (
    <div className="space-y-3">
      <div className="grid gap-3 lg:grid-cols-2">
        <KeyValuePanel
          title="编排结果"
          rows={[
            ["状态", result.status],
            ["原因", result.reason],
            ["产品 ID", result.product_id],
            ["输入图数量", inputImages.length],
            ["选择依据", result.selection_reason],
          ]}
        />
        <KeyValuePanel
          title="输入素材"
          rows={[
            ["标记主图", result.marked_main_image_path],
            ["标记尺寸图", result.marked_size_reference_image_path],
            ["Enroute 参考图", result.enroute_reference_image_path],
            ["模特", selectedModel.name || selectedModel.profile_key],
            ["模特图", selectedModel.image_path],
          ]}
        />
      </div>

      {inputImages.length > 0 || enrouteImagePath ? (
        <div>
          <p className="mb-2 text-xs font-medium text-zinc-500">生图输入素材</p>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {inputImages.map((path, index) => (
              <ImagePreview
                key={`${index}-${path}`}
                label={`输入图 ${index + 1}`}
                path={path}
                url={imageDisplayUrl(path)}
              />
            ))}
            {enrouteImagePath ? (
              <ImagePreview
                label="Enroute profile 参考"
                path={enrouteImagePath}
                url={imageDisplayUrl(enrouteImagePath)}
              />
            ) : null}
          </div>
        </div>
      ) : null}

      {prompt ? (
        <div className="space-y-2">
          <label className="text-xs font-medium text-zinc-500">编排后的完整提示词</label>
          <Textarea
            className="min-h-72 font-mono text-xs leading-relaxed"
            value={prompt}
            readOnly
          />
        </div>
      ) : null}

      {hasRaw ? (
        <details className="rounded-md border border-zinc-200 bg-white">
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
            生图提示词编排原始结果
          </summary>
          <div className="border-t border-zinc-200 p-3">
            <CompactJson value={result} />
          </div>
        </details>
      ) : null}
    </div>
  );
}

function EnrouteRecordList({
  title,
  items,
}: {
  title: string;
  items: unknown[];
}) {
  return (
    <div>
      <p className="mb-2 text-xs font-medium text-zinc-500">
        {title} ({items.length})
      </p>
      <div className="space-y-2">
        {items.map((item, index) => {
          const record = asRecord(item);
          return (
            <div key={index} className="rounded-md bg-zinc-50 p-2 text-sm">
              <div className="grid gap-1 md:grid-cols-[120px_1fr]">
                <span className="text-zinc-500">Enroute ID</span>
                <span className="min-w-0 break-words font-medium">
                  {displayValue(record.enroute_product_id)}
                </span>
                <span className="text-zinc-500">状态 / 缓存</span>
                <span className="min-w-0 break-words font-medium">
                  {displayValue(record.status)} / {displayValue(record.cache)}
                </span>
                <span className="text-zinc-500">参考图</span>
                <div className="min-w-0 font-medium">
                  <SmartValue
                    label="参考图"
                    value={record.image_path || record.reference_image_path}
                    compact
                  />
                </div>
                <span className="text-zinc-500">摘要</span>
                <span className="min-w-0 break-words font-medium">
                  {displayValue(record.summary)}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function LearningReferenceList({
  title,
  items,
}: {
  title: string;
  items: EnrouteLearningItem[];
}) {
  return (
    <div className="rounded-md border border-zinc-200 bg-white p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium">{title}</p>
        <Badge variant="secondary">{items.length} 张</Badge>
      </div>
      <div className="grid gap-2 md:grid-cols-2">
        {items.map((item) => (
          <div
            key={item.enroute_product_id}
            className={`rounded-md border p-2 text-sm ${
              item.status === "failed"
                ? "border-red-200 bg-red-50/60"
                : item.status === "learning"
                  ? "border-amber-200 bg-amber-50/60"
                  : "border-zinc-200 bg-zinc-50"
            }`}
          >
            <div className="mb-1 flex items-start justify-between gap-2">
              <p className="min-w-0 break-words font-medium">
                {item.enroute_title || item.enroute_product_id}
              </p>
              <Badge variant={learningStatusBadgeVariant(item.status)}>
                {learningStatusLabel(item.status)}
              </Badge>
            </div>
            <p className="break-all font-mono text-xs text-zinc-500">
              {item.enroute_product_id}
            </p>
            <div className="mt-2 grid gap-1 text-xs text-zinc-600">
              <span>尝试次数：{displayValue(item.learning_attempts)}</span>
              <span>学习时间：{formatTimestamp(item.learned_at)}</span>
              {item.last_error ? (
                <span className="break-words text-red-700">
                  错误：{item.last_error}
                </span>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function GrsaiNodePanel({
  review,
  canResume,
  loading,
  activeAction,
  onRetry,
}: {
  review: GrsaiReview;
  canResume: boolean;
  loading: boolean;
  activeAction: ActionKey | null;
  onRetry: () => void;
}) {
  const disabled = loading || !canResume;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-zinc-200 bg-zinc-50 px-3 py-2">
        <div>
          <p className="text-sm font-medium">生成操作</p>
          <p className="mt-1 text-xs text-zinc-500">
            {canResume ? "当前可提交人工重试。" : "等待人工审核时可重试。"}
          </p>
        </div>
        <Button
          variant="outline"
          onClick={onRetry}
          disabled={disabled}
          loading={activeAction === "resume-regenerate"}
          loadingText="提交中"
          title={canResume ? "重新生成穿戴图" : "等待人工审核时可重试"}
        >
          <RefreshCcw className="h-4 w-4" />
          人工重试生成
        </Button>
      </div>
      <GrsaiReviewPanel review={review} />
    </div>
  );
}

function GrsaiReviewPanel({ review }: { review: GrsaiReview }) {
  const hasImages = review.images.length > 0;
  const hasResult = Boolean(review.generatedImagePath || review.generatedImageUrl);
  const hasPrompt = Boolean(review.prompt);
  const hasGeneration = Object.keys(review.imageGeneration).length > 0;

  if (!hasImages && !hasResult && !hasPrompt && !hasGeneration) {
    return null;
  }

  return (
    <div className="space-y-3">
      <div>
        <p className="text-sm font-medium">Grsai 生成详情</p>
        <p className="mt-1 text-xs text-zinc-500">
          参考图、完整提示词和生成结果。
        </p>
      </div>

      {hasResult ? (
        <ImagePreview
          label="生成结果"
          path={review.generatedImagePath || review.generatedImageUrl}
          url={imageDisplayUrl(review.generatedImageUrl || review.generatedImagePath)}
          large
        />
      ) : null}

      {hasImages ? (
        <div>
          <p className="mb-2 text-xs font-medium text-zinc-500">参考图</p>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {review.images.map((image) => (
              <ImagePreview
                key={`${image.label}-${image.path}`}
                label={image.label}
                path={image.path}
                url={image.url}
              />
            ))}
          </div>
        </div>
      ) : null}

      {hasPrompt ? (
        <div className="space-y-2">
          <label className="text-xs font-medium text-zinc-500">完整提示词</label>
          <Textarea
            className="min-h-72 font-mono text-xs leading-relaxed"
            value={review.prompt}
            readOnly
          />
        </div>
      ) : null}

      {hasGeneration ? (
        <details className="rounded-md border border-zinc-200 bg-zinc-50">
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
            Grsai 原始结果
          </summary>
          <div className="border-t border-zinc-200 p-3">
            <CompactJson value={review.imageGeneration} />
          </div>
        </details>
      ) : null}
    </div>
  );
}

function ImagePreview({
  label,
  path,
  url,
  large = false,
}: {
  label: string;
  path: string;
  url: string;
  large?: boolean;
}) {
  return (
    <div className="overflow-hidden rounded-md border border-zinc-200 bg-zinc-50">
      <div className="flex items-center justify-between gap-2 border-b border-zinc-200 px-3 py-2">
        <span className="text-sm font-medium">{label}</span>
        {url ? (
          <a
            className="text-xs text-zinc-500 underline underline-offset-2"
            href={url}
            target="_blank"
            rel="noreferrer"
          >
            打开
          </a>
        ) : null}
      </div>
      {url ? (
        <ZoomableImage
          className={`w-full bg-white object-contain ${large ? "max-h-[560px]" : "h-56"}`}
          src={url}
          alt={label}
          loading="lazy"
        />
      ) : (
        <div className={large ? "h-80" : "h-56"} />
      )}
      <p className="break-all px-3 py-2 font-mono text-xs text-zinc-500">
        {path || "-"}
      </p>
    </div>
  );
}

function ZoomableImage({
  className,
  src,
  alt,
  loading,
}: {
  className: string;
  src: string;
  alt: string;
  loading?: "eager" | "lazy";
}) {
  return (
    <Zoom>
      <img
        className={`${className} cursor-zoom-in`}
        src={src}
        alt={alt}
        loading={loading}
      />
    </Zoom>
  );
}

function buildGrsaiReview(state: unknown): GrsaiReview {
  const root = asRecord(state);
  const values = asRecord(root.values);
  const wearing = asRecord(values.wearing_image_result);
  const wearingPrompt = asRecord(values.wearing_generation_prompt_result);
  const manualReview = latestManualReviewPayload(root, values);
  const selectedModelFromWearing = resolvedSelectedModel(wearing);
  const selectedModelFromPrompt = resolvedSelectedModel(wearingPrompt);
  const selectedModelProfile = Object.keys(selectedModelFromWearing).length
    ? selectedModelFromWearing
    : Object.keys(selectedModelFromPrompt).length
      ? selectedModelFromPrompt
      : asRecord(manualReview.selected_model_profile);
  const imageGeneration = asRecord(wearing.image_generation);
  const imageMap = new Map<string, ReviewImage>();

  addReviewImage(
    imageMap,
    "主图",
    stringValue(wearing.marked_main_image_path || wearingPrompt.marked_main_image_path),
  );
  addReviewImage(
    imageMap,
    "尺寸参考图",
    stringValue(
      wearing.marked_size_reference_image_path ||
        wearingPrompt.marked_size_reference_image_path,
    ),
  );
  addReviewImage(
    imageMap,
    "Enroute 参考图",
    stringValue(
      wearing.enroute_reference_image_path ||
        wearingPrompt.enroute_reference_image_path ||
        manualReview.enroute_reference_image_path,
    ),
  );
  addReviewImage(
    imageMap,
    "固定模特",
    stringValue(selectedModelProfile.image_path),
  );

  const inputImages = Array.isArray(wearing.input_images)
    ? wearing.input_images
    : Array.isArray(wearingPrompt.input_images)
      ? wearingPrompt.input_images
      : [];
  inputImages.forEach((item, index) => {
    addReviewImage(imageMap, `输入图 ${index + 1}`, stringValue(item));
  });

  return {
    prompt: stringValue(wearing.prompt || wearingPrompt.prompt || manualReview.prompt),
    generatedImagePath: stringValue(
      wearing.generated_image_path || manualReview.generated_image_path,
    ),
    generatedImageUrl: stringValue(
      wearing.generated_image_url || manualReview.generated_image_url,
    ),
    images: Array.from(imageMap.values()),
    imageGeneration,
  };
}

function buildAiCallsFromState(state: unknown): AiCallSummary[] {
  const root = asRecord(state);
  const values = asRecord(root.values);
  const checkpoints = asRecord(values.ai_checkpoints);
  return Object.entries(checkpoints).map(([key, checkpointValue]) => {
    const checkpoint = asRecord(checkpointValue);
    const input = asRecord(checkpoint.input);
    const result = asRecord(checkpoint.result);
    const runtime = asRecord(input._runtime);
    return {
      key,
      label: fallbackAiCallLabel(key),
      kind: stringValue(checkpoint.type) || (key.startsWith("generate_wearing_image") ? "image_ai" : "llm"),
      status: stringValue(checkpoint.status || result.status),
      source: stringValue(checkpoint.source),
      attempt_count:
        typeof checkpoint.attempt_count === "number" ? checkpoint.attempt_count : null,
      input_hash: stringValue(checkpoint.input_hash),
      model: stringValue(runtime.model),
      providers: arrayValue(runtime.providers).map(asRecord),
      prompts: asRecord(runtime.prompts),
      input,
      output: result,
      images: collectAiCallImages(key, input, result),
      raw_checkpoint: checkpoint,
    };
  });
}

function collectAiCallImages(
  key: string,
  input: Record<string, unknown>,
  output: Record<string, unknown>,
) {
  const images: Array<{ label: string; path: string; role: string }> = [];
  const seen = new Set<string>();
  function add(label: string, path: unknown, role = "input") {
    const value = stringValue(path).trim();
    if (!value || seen.has(value)) {
      return;
    }
    seen.add(value);
    images.push({ label, path: value, role });
  }
  add("检测拼图", input.collage_path);
  add("Enroute 学习图", input.reference_image_path);
  add("产品主图", input.main_image_path);
  add("尺寸参考图", input.size_reference_image_path);
  add("Enroute profile 图", output.enroute_reference_image_path || output.reference_image_path, "context");
  add("生成结果", output.generated_image_path || output.generated_image_url, "output");

  const promptInput = asRecord(input.wearing_generation_prompt_result);
  arrayValue(promptInput.input_images || output.input_images).forEach((path, index) => {
    add(
      key.startsWith("generate_wearing_image")
        ? `Grsai 输入图 ${index + 1}`
        : `Prompt 输入图 ${index + 1}`,
      path,
    );
  });
  return images;
}

function fallbackAiCallLabel(key: string) {
  if (key === "detect_size_reference") {
    return "LLM 产品合格性检测";
  }
  if (key.startsWith("learn_enroute_reference")) {
    return "LLM 学习 Enroute profile";
  }
  if (key === "select_wearing_style_profile") {
    return "LLM 选择风格与模特";
  }
  if (key === "compile_wearing_generation_prompt") {
    return "LLM 编排生图提示词";
  }
  if (key.startsWith("generate_wearing_image")) {
    return "图片 AI 生成穿戴图";
  }
  return key;
}

function latestManualReviewPayload(
  root: Record<string, unknown>,
  values: Record<string, unknown>,
) {
  const manualReview = asRecord(values.manual_review_request);
  if (Object.keys(manualReview).length > 0) {
    return manualReview;
  }
  const interrupts = Array.isArray(root.interrupts) ? root.interrupts : [];
  for (const interrupt of interrupts) {
    const value = asRecord(asRecord(interrupt).value);
    if (value.type === "wearing_image_review") {
      return value;
    }
  }
  const tasks = Array.isArray(root.tasks) ? root.tasks : [];
  for (const task of tasks) {
    const taskRecord = asRecord(task);
    const rawTaskInterrupts = taskRecord.interrupts;
    const taskInterrupts = Array.isArray(rawTaskInterrupts)
      ? rawTaskInterrupts
      : [];
    for (const interrupt of taskInterrupts) {
      const value = asRecord(asRecord(interrupt).value);
      if (value.type === "wearing_image_review") {
        return value;
      }
    }
  }
  return {};
}

function addReviewImage(
  imageMap: Map<string, ReviewImage>,
  label: string,
  path: string,
) {
  if (!path || imageMap.has(path)) {
    return;
  }
  imageMap.set(path, {
    label,
    path,
    url: imageDisplayUrl(path),
  });
}

function imageDisplayUrl(path: string, version?: number | string) {
  if (!path) {
    return "";
  }
  if (/^https?:\/\//i.test(path)) {
    return appendUrlVersion(path, version);
  }
  const url = `${CONTROL_API_BASE}/api/files/image?path=${encodeURIComponent(path)}`;
  return appendUrlVersion(url, version);
}

function appendUrlVersion(url: string, version?: number | string) {
  if (!version) {
    return url;
  }
  return `${url}${url.includes("?") ? "&" : "?"}v=${encodeURIComponent(String(version))}`;
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function ResultPanel({ result }: { result: Record<string, unknown> | null }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>最近操作结果</CardTitle>
      </CardHeader>
      <CardContent>
        <OperationResult result={result} />
      </CardContent>
    </Card>
  );
}

function StatusBadge({ online }: { online: boolean }) {
  return online ? (
    <Badge variant="success">
      <Activity className="mr-1 h-3 w-3" />
      在线
    </Badge>
  ) : (
    <Badge variant="danger">离线</Badge>
  );
}

function ProgressPanel({
  progress,
  threadStatus,
}: {
  progress?: ThreadProgress;
  threadStatus: string;
}) {
  const activeRun = asRecord(progress?.active_run);
  const tasks = Array.isArray(progress?.tasks) ? progress.tasks : [];
  const running = Boolean(progress?.running);
  const queued = Boolean(progress?.queued || progress?.status === "pending");
  return (
    <div
      className={`rounded-md border p-3 ${
        running
          ? "border-emerald-200 bg-emerald-50"
          : queued
            ? "border-amber-200 bg-amber-50"
            : "border-zinc-200 bg-white"
      }`}
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-medium">运行进度</p>
          <p className="mt-1 text-sm text-zinc-600">
            {progress?.message || "暂无运行进度。"}
          </p>
        </div>
        <Badge variant={running ? "success" : queued ? "warning" : "secondary"}>
          {progress?.status_label || threadStatusLabel(threadStatus)}
        </Badge>
      </div>
      <div className="grid gap-3 md:grid-cols-4">
        <InfoBlock label="阶段" value={progress?.phase_label || "-"} />
        <InfoBlock label="已运行" value={progress?.elapsed_label || "-"} />
        <InfoBlock label="Run" value={displayValue(activeRun.run_id)} />
        <InfoBlock label="更新时间" value={formatTimestamp(progress?.updated_at)} />
      </div>
      {tasks.length > 0 ? (
        <div className="mt-3 space-y-2">
          {tasks.map((item, index) => {
            const task = asRecord(item);
            return (
              <div key={index} className="rounded-md bg-white/80 p-2 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{displayValue(task.label || task.name)}</span>
                  <span className="font-mono text-xs text-zinc-500">
                    {displayValue(task.id)}
                  </span>
                </div>
                {task.error ? (
                  <p className="mt-1 break-words text-red-700">
                    {displayValue(task.error)}
                  </p>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

function ThreadStopReasonBadge({ thread }: { thread: WorkflowThread }) {
  if (thread.summary.needs_manual_review) {
    return <Badge variant="warning">需要审核</Badge>;
  }
  const code = thread.summary.stop_reason_code ?? "";
  const variant =
    thread.status === "error" ||
    code.includes("failed") ||
    code.includes("error")
      ? "danger"
      : thread.status === "busy"
        ? "success"
        : "secondary";
  return <Badge variant={variant}>{thread.summary.stop_reason || threadStatusLabel(thread.status)}</Badge>;
}

function threadStatusLabel(status: string) {
  const labels: Record<string, string> = {
    busy: "运行中",
    interrupted: "已停止",
    idle: "空闲",
    error: "异常",
  };
  return labels[status] ?? status;
}

function actionNotice(result: Record<string, unknown>) {
  const message = typeof result.message === "string" ? result.message : "";
  if (message) {
    return message;
  }
  if (result.mode === "resume_required") {
    return "存在等待人工审核的任务，安全恢复未自动继续。请先提交审核动作。";
  }
  if (result.mode === "selected_thread_restarted") {
    return "已对当前选中的任务发起普通节点重试。";
  }
  if (result.mode === "already_running") {
    return "已有任务正在运行，未创建新 workflow。";
  }
  if (result.mode === "resumed") {
    return "已提交恢复请求。";
  }
  if (result.mode === "started_after_no_unfinished_thread") {
    return "未找到未完成任务，已创建新 workflow。";
  }
  if (result.mode === "started") {
    return "已启动新 workflow。";
  }
  if (result.mode === "clear_flows") {
    const deletedThreads =
      typeof result.deleted_threads === "number" ? result.deleted_threads : 0;
    const productsReset =
      typeof result.products_reset === "number" ? result.products_reset : 0;
    return `已清理 ${deletedThreads} 个 flow，同步恢复 ${productsReset} 个商品。`;
  }
  if (result.mode === "stop_flow") {
    const cancelledRuns =
      typeof result.cancelled_runs === "number" ? result.cancelled_runs : 0;
    return `已停止 ${cancelledRuns} 个活跃 run。`;
  }
  if (result.mode === "delete_flow") {
    const deletedThreads =
      typeof result.deleted_threads === "number" ? result.deleted_threads : 0;
    const productsReset =
      typeof result.products_reset === "number" ? result.products_reset : 0;
    return `已删除 ${deletedThreads} 个 flow，同步恢复 ${productsReset} 个商品。`;
  }
  return "";
}

function shouldAutoSelectResultThread(result: Record<string, unknown>) {
  if (
    result.mode === "resume_required" ||
    result.mode === "stop_flow" ||
    result.mode === "delete_flow"
  ) {
    return false;
  }
  return typeof result.thread_id === "string";
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <span className="text-zinc-500">{label}</span>
      <span className="truncate font-medium">{value}</span>
    </div>
  );
}

function InfoBlock({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded-md border border-zinc-200 bg-zinc-50 p-3">
      <p className="text-xs text-zinc-500">{label}</p>
      <div className="mt-1 text-sm font-medium">
        <SmartValue label={label} value={value} compact />
      </div>
    </div>
  );
}

function StatePanel({ state }: { state: unknown }) {
  if (!state) {
    return (
      <div>
        <p className="mb-2 text-sm font-medium">State</p>
        <p className="rounded-md border border-zinc-200 bg-white p-3 text-sm text-zinc-500">
          暂无 state。
        </p>
      </div>
    );
  }

  const root = asRecord(state);
  const values = asRecord(root.values);
  const product = asRecord(values.selected_product);
  const rawdata = asRecord(product.rawdata);
  const mainImage = asRecord(values.main_image_result);
  const wearing = asRecord(values.wearing_image_result);
  const sizeReference = asRecord(values.size_reference_result);
  const enrouteReference = asRecord(values.enroute_reference_result);
  const enrouteAnalysis = asRecord(values.enroute_analysis_result);
  const enrouteLearning = asRecord(values.enroute_learning_result);
  const wearingStyleSelectionRaw = asRecord(values.wearing_style_selection_result);
  const wearingStyleSelection = Object.keys(wearingStyleSelectionRaw).length
    ? wearingStyleSelectionRaw
    : enrouteAnalysis;
  const wearingPrompt = asRecord(values.wearing_generation_prompt_result);
  const selectedModel = resolvedSelectedModel(wearingStyleSelection);
  const manualReview = asRecord(values.manual_review_request);
  const metrics = asRecord(values.metrics);
  const checkpoints = asRecord(values.ai_checkpoints);
  const tasks = Array.isArray(root.tasks) ? root.tasks : [];
  const interrupts = Array.isArray(root.interrupts) ? root.interrupts : [];
  const nextNodes = Array.isArray(root.next) ? root.next.map(String).join("、") : "-";

  return (
    <div className="space-y-3">
      <p className="text-sm font-medium">State</p>

      <div className="grid gap-3 md:grid-cols-3">
        <InfoBlock label="当前节点" value={nextNodes || "-"} />
        <InfoBlock label="暂停数量" value={String(interrupts.length)} />
        <InfoBlock label="任务数量" value={String(tasks.length)} />
      </div>

      {tasks.length > 0 ? (
        <details open className="rounded-md border border-zinc-200 bg-white">
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
            当前任务
          </summary>
          <div className="space-y-2 border-t border-zinc-200 p-3">
            {tasks.map((item, index) => {
              const task = asRecord(item);
              return (
                <div key={index} className="rounded-md bg-zinc-50 p-2 text-sm">
                  <p className="font-medium">{displayValue(task.name)}</p>
                  <p className="font-mono text-xs text-zinc-500">
                    {displayValue(task.id)}
                  </p>
                  {task.error ? (
                    <p className="mt-1 break-words text-red-700">
                      {displayValue(task.error)}
                    </p>
                  ) : null}
                </div>
              );
            })}
          </div>
        </details>
      ) : null}

      <div className="grid gap-3 md:grid-cols-2">
        <KeyValuePanel
          title="商品"
          rows={[
            ["产品 ID", product.product_id],
            ["平台", product.platform],
            ["状态", product.status],
            ["标题", rawdata.title],
          ]}
        />
        <KeyValuePanel
          title="准备主图"
          rows={[
            ["状态", mainImage.status],
            ["合图", mainImage.path],
            ["图片数量", mainImage.source_image_count],
            ["临时文件", mainImage.temporary],
          ]}
        />
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <KeyValuePanel
          title="产品合格性检测"
          rows={[
            ["状态", sizeReference.status],
            ["产品合格", sizeReference.is_product_qualified],
            ["失败项", sizeReference.failed_checks],
            ["可判断尺寸", sizeReference.can_judge_size],
            ["尺寸参考图编号", sizeReference.size_reference_image_number],
            ["主图编号", sizeReference.main_image_number],
            ["原因", sizeReference.reason],
          ]}
        />
        <KeyValuePanel
          title="Enroute 参考选择"
          rows={[
            ["状态", enrouteReference.status],
            ["类目", enrouteReference.category],
            ["参考图数量", enrouteReference.reference_count],
            ["未学习数量", enrouteReference.unlearned_count],
            ["本次学习", enrouteReference.learning_count],
            ["选中参考图", enrouteReference.selected_image_path],
          ]}
        />
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <KeyValuePanel
          title="Enroute profile 学习"
          rows={[
            ["状态", enrouteLearning.status],
            ["类目", enrouteLearning.category],
            ["本次学习", enrouteLearning.learning_count],
            ["学习后缓存", enrouteLearning.cached_analysis_count_after_learning],
            ["原因", enrouteLearning.reason],
          ]}
        />
        <KeyValuePanel
          title="风格与模特"
          rows={[
            ["状态", wearingStyleSelection.status],
            ["Enroute", wearingStyleSelection.enroute_product_id],
            ["参考图", wearingStyleSelection.reference_image_path],
            ["模特", selectedModel.name || selectedModel.profile_key],
            ["选择依据", asRecord(wearingStyleSelection.selection).reason],
          ]}
        />
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <KeyValuePanel
          title="生图提示词"
          rows={[
            ["状态", wearingPrompt.status],
            ["原因", wearingPrompt.reason],
            ["输入图数量", arrayValue(wearingPrompt.input_images).length],
            ["提示词长度", stringValue(wearingPrompt.prompt).length],
            ["标记主图", wearingPrompt.marked_main_image_path],
            ["标记尺寸图", wearingPrompt.marked_size_reference_image_path],
          ]}
        />
        <KeyValuePanel
          title="穿戴图"
          rows={[
            ["状态", wearing.status],
            ["原因", wearing.reason],
            ["生成图", wearing.generated_image_path],
            ["Attempt", wearing.attempt],
            ["Grsai 任务", asRecord(wearing.image_generation).id],
          ]}
        />
      </div>

      <details className="rounded-md border border-zinc-200 bg-white">
        <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
          人工审核 payload
        </summary>
        <div className="border-t border-zinc-200 p-3">
          <CompactJson value={manualReview} />
        </div>
      </details>

      <details className="rounded-md border border-zinc-200 bg-white">
        <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
          AI checkpoints ({Object.keys(checkpoints).length})
        </summary>
        <div className="space-y-2 border-t border-zinc-200 p-3">
          {Object.keys(checkpoints).length === 0 ? (
            <p className="text-sm text-zinc-500">暂无 checkpoints。</p>
          ) : (
            Object.entries(checkpoints).map(([key, value]) => {
              const checkpoint = asRecord(value);
              return (
                <div key={key} className="rounded-md bg-zinc-50 p-2 text-sm">
                  <p className="font-mono text-xs text-zinc-500">{key}</p>
                  <p className="mt-1">
                    状态：{displayValue(checkpoint.status)} · 来源：
                    {displayValue(checkpoint.source)} · 次数：
                    {displayValue(checkpoint.attempt_count)}
                  </p>
                </div>
              );
            })
          )}
        </div>
      </details>

      <details className="rounded-md border border-zinc-200 bg-white">
        <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
          运行指标
        </summary>
        <div className="border-t border-zinc-200 p-3">
          <CompactJson value={metrics} />
        </div>
      </details>

      <details className="rounded-md border border-zinc-200 bg-white">
        <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
          原始 State JSON
        </summary>
        <div className="border-t border-zinc-200 p-3">
          <JsonViewer value={state} />
        </div>
      </details>
    </div>
  );
}

function OperationResult({ result }: { result: Record<string, unknown> | null }) {
  if (!result) {
    return <p className="text-sm text-zinc-500">暂无操作结果。</p>;
  }

  const summary = asRecord(result.summary);
  const skippedThreads = Array.isArray(result.skipped_threads)
    ? result.skipped_threads
    : [];
  const isClearFlows = result.mode === "clear_flows";

  return (
    <div className="space-y-3">
      <div className="grid gap-3 md:grid-cols-3">
        <InfoBlock label="结果" value={operationModeLabel(result.mode)} />
        <InfoBlock label="Thread" value={result.thread_id} />
        <InfoBlock label="Run" value={result.run_id} />
      </div>

      {typeof result.message === "string" && result.message ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          {result.message}
        </div>
      ) : null}

      {isClearFlows ? (
        <div className="grid gap-3 md:grid-cols-3">
          <InfoBlock label="清理 Flow" value={result.deleted_threads} />
          <InfoBlock label="恢复商品" value={result.products_reset} />
          <InfoBlock label="跳过商品" value={result.skipped_products} />
        </div>
      ) : null}

      {Object.keys(summary).length > 0 ? (
        <KeyValuePanel
          title="任务摘要"
          rows={[
            ["产品 ID", summary.product_id],
            ["标题", summary.product_title],
            ["当前节点", summary.current_node_label],
            ["停止原因", summary.stop_reason],
            ["详情", summary.stop_reason_detail],
          ]}
        />
      ) : null}

      {skippedThreads.length > 0 ? (
        <details className="rounded-md border border-zinc-200 bg-white">
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
            跳过的 thread ({skippedThreads.length})
          </summary>
          <div className="space-y-2 border-t border-zinc-200 p-3">
            {skippedThreads.map((item, index) => {
              const thread = asRecord(item);
              const threadSummary = asRecord(thread.summary);
              return (
                <div key={index} className="rounded-md bg-zinc-50 p-2 text-sm">
                  <p className="font-mono text-xs text-zinc-500">
                    {displayValue(thread.thread_id)}
                  </p>
                  <p className="mt-1">原因：{displayValue(threadSummary.stop_reason)}</p>
                  <p className="mt-1 text-zinc-500">
                    {displayValue(threadSummary.product_title)}
                  </p>
                </div>
              );
            })}
          </div>
        </details>
      ) : null}

      <details className="rounded-md border border-zinc-200 bg-white">
        <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
          原始操作结果 JSON
        </summary>
        <div className="border-t border-zinc-200 p-3">
          <JsonViewer value={result} />
        </div>
      </details>
    </div>
  );
}

function KeyValuePanel({
  title,
  rows,
}: {
  title: string;
  rows: Array<[string, unknown]>;
}) {
  return (
    <div className="rounded-md border border-zinc-200 bg-white p-3">
      <p className="mb-2 text-sm font-medium">{title}</p>
      <div className="space-y-2">
        {rows.map(([label, value]) => (
          <div key={label} className="grid gap-1 text-sm md:grid-cols-[120px_1fr]">
            <span className="text-zinc-500">{label}</span>
            <div className="min-w-0 font-medium">
              <SmartValue label={label} value={value} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SmartValue({
  label,
  value,
  compact = false,
}: {
  label: string;
  value: unknown;
  compact?: boolean;
}) {
  const imagePath = imagePathFromValue(label, value);
  if (imagePath) {
    return <ImageValuePreview label={label} path={imagePath} compact={compact} />;
  }
  return <span className="min-w-0 break-words">{displayValue(value)}</span>;
}

function ImageValuePreview({
  label,
  path,
  compact = false,
}: {
  label: string;
  path: string;
  compact?: boolean;
}) {
  const url = imageDisplayUrl(path);
  return (
    <div className="min-w-0 space-y-2">
      <ZoomableImage
        className={`w-full rounded-md border border-zinc-200 bg-white object-contain ${
          compact ? "max-h-40" : "max-h-72"
        }`}
        src={url}
        alt={label}
        loading="lazy"
      />
      <p className="select-text break-all font-mono text-xs font-normal text-zinc-500">
        {path}
      </p>
    </div>
  );
}

function CompactJson({ value }: { value: unknown }) {
  return (
    <div className="space-y-3">
      <pre className="max-h-80 overflow-auto rounded-md bg-zinc-950 p-3 text-xs leading-relaxed text-zinc-50">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

function JsonViewer({ title, value }: { title?: string; value: unknown }) {
  return (
    <div>
      {title ? <p className="mb-2 text-sm font-medium">{title}</p> : null}
      <pre className="max-h-[520px] overflow-auto rounded-md border border-zinc-200 bg-zinc-950 p-3 text-xs leading-relaxed text-zinc-50">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function productSourceUrl(thread: WorkflowThread, state: unknown): string {
  const root = asRecord(state);
  const values = asRecord(root.values);
  const product = asRecord(values.selected_product);
  const rawdata = asRecord(product.rawdata);
  const directUrl =
    stringValue(rawdata.url) ||
    stringValue(rawdata.requested_url) ||
    stringValue(rawdata.product_url) ||
    stringValue(thread.summary.product_url);
  if (isHttpUrl(directUrl)) {
    return directUrl;
  }

  const platform = stringValue(product.platform || thread.summary.platform).toLowerCase();
  const productId = stringValue(product.product_id || thread.summary.product_id);
  if (platform.includes("1688") && productId) {
    return `https://detail.1688.com/offer/${encodeURIComponent(productId)}.html`;
  }
  return "";
}

function isHttpUrl(value: string): boolean {
  return /^https?:\/\//i.test(value);
}

function resolvedSelectedModel(value: unknown): Record<string, unknown> {
  const record = asRecord(value);
  const direct = asRecord(record.selected_model_profile);
  if (Object.keys(direct).length > 0) {
    return direct;
  }
  return asRecord(asRecord(record.analysis).selected_model_profile);
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function countByStatus(
  statuses: Array<{ status: string; count: number }>,
  targetStatus: string,
): number {
  return statuses.find((item) => item.status === targetStatus)?.count ?? 0;
}

type LearningStatusCounts = {
  pending: number;
  learning: number;
  learned: number;
  failed: number;
};

function emptyLearningStatusCounts(): LearningStatusCounts {
  return {
    pending: 0,
    learning: 0,
    learned: 0,
    failed: 0,
  };
}

function countLearningItemsByStatus(items: EnrouteLearningItem[]): LearningStatusCounts {
  const counts = emptyLearningStatusCounts();
  for (const item of items) {
    if (item.status === "pending") {
      counts.pending += 1;
    } else if (item.status === "learning") {
      counts.learning += 1;
    } else if (item.status === "learned") {
      counts.learned += 1;
    } else if (item.status === "failed") {
      counts.failed += 1;
    }
  }
  return counts;
}

function learningRowsForCategory(
  category: string,
  learning: EnrouteLearningResponse | null,
): EnrouteLearningItem[] {
  if (!category || !learning) {
    return [];
  }
  return learning.items.filter((item) => item.enroute_category === category);
}

function learningRowsForReferencePlan(
  reference: Record<string, unknown>,
  learning: EnrouteLearningResponse | null,
): EnrouteLearningItem[] {
  if (!learning) {
    return [];
  }
  const ids = new Set<string>();
  for (const item of arrayValue(reference.learning_reference_rows)) {
    const record = asRecord(item);
    const id = stringValue(record.enroute_product_id || record.product_id);
    if (id) {
      ids.add(id);
    }
  }
  for (const item of arrayValue(reference.learning_references)) {
    const record = asRecord(item);
    const id = stringValue(record.enroute_product_id || record.product_id);
    if (id) {
      ids.add(id);
    }
  }
  if (ids.size === 0) {
    return [];
  }
  return learning.items
    .filter((item) => ids.has(item.enroute_product_id))
    .sort(compareLearningItems);
}

function compareLearningItems(a: EnrouteLearningItem, b: EnrouteLearningItem): number {
  const statusOrder: Record<string, number> = {
    learning: 0,
    failed: 1,
    pending: 2,
    learned: 3,
  };
  const statusDiff =
    (statusOrder[a.status] ?? 9) - (statusOrder[b.status] ?? 9);
  if (statusDiff !== 0) {
    return statusDiff;
  }
  return a.enroute_product_id.localeCompare(b.enroute_product_id);
}

function learningStatusBadgeVariant(
  status: unknown,
): "secondary" | "success" | "warning" | "danger" {
  const value = stringValue(status);
  if (value === "learned") {
    return "success";
  }
  if (value === "learning") {
    return "warning";
  }
  if (value === "failed") {
    return "danger";
  }
  return "secondary";
}

function learningStatusLabel(status: unknown): string {
  const value = stringValue(status);
  const labels: Record<string, string> = {
    pending: "待学习",
    learning: "学习中",
    learned: "已学习",
    failed: "失败",
  };
  return labels[value] ?? displayValue(value);
}

function imagePathFromValue(label: string, value: unknown): string {
  if (typeof value !== "string") {
    return "";
  }
  const text = value.trim();
  if (!text || text === "-") {
    return "";
  }
  return looksLikeImageReference(label, text) ? text : "";
}

function looksLikeImageReference(label: string, text: string): boolean {
  if (/^data:image\//i.test(text) || hasImageExtension(text)) {
    return true;
  }
  const imageLabel = /图|图片|image|img|photo|thumbnail|avatar|wearing|generated|reference/i.test(
    label,
  );
  if (!imageLabel) {
    return false;
  }
  return /^https?:\/\//i.test(text) || text.startsWith("/") || text.includes("/");
}

function hasImageExtension(text: string): boolean {
  return /\.(png|jpe?g|webp|gif|bmp|avif|svg)(\?.*)?$/i.test(text);
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.length === 0 ? "-" : value.map(displayValue).join("、");
  }
  return JSON.stringify(value);
}

function formatTimestamp(value: unknown): string {
  if (!value) {
    return "-";
  }
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleString("zh-CN", { hour12: false });
}

function operationModeLabel(mode: unknown) {
  const labels: Record<string, string> = {
    resume_required: "等待人工审核",
    selected_thread_restarted: "已重试当前任务",
    already_running: "已有任务运行中",
    resumed: "已提交恢复",
    started_after_no_unfinished_thread: "已启动新任务",
    started: "已启动",
    clear_flows: "已清理 Flow",
  };
  return typeof mode === "string" ? labels[mode] ?? mode : "-";
}

function setStableJsonState<T>(
  setter: Dispatch<SetStateAction<T | null>>,
  nextValue: T,
) {
  setter((previousValue) =>
    JSON.stringify(previousValue) === JSON.stringify(nextValue)
      ? previousValue
      : nextValue,
  );
}
