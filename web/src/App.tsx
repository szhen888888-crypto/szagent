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
  ExternalLink,
  GalleryHorizontalEnd,
  Images,
  PauseCircle,
  Play,
  Power,
  RefreshCcw,
  RotateCcw,
  Square,
} from "lucide-react";
import {
  getServerStatus,
  getThreadState,
  listEnrouteLearning,
  listModelProfiles,
  listThreads,
  EnrouteLearningItem,
  EnrouteLearningResponse,
  ModelProfile,
  ModelProfilesResponse,
  restartServer,
  restartWorkflow,
  resumeThread,
  ServerStatus,
  startServer,
  startWorkflow,
  stopServer,
  ThreadStateResponse,
  ThreadsResponse,
  ThreadProgress,
  WorkflowThread,
  CONTROL_API_BASE,
} from "./api";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./components/ui/card";
import { Input } from "./components/ui/input";
import { Textarea } from "./components/ui/textarea";

const DEFAULT_API_URL = "http://127.0.0.1:2024";
const DEFAULT_ASSISTANT_ID = "product_listing";
type PageId = "tasks" | "models" | "learning";

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
  const [selectedThreadId, setSelectedThreadId] = useState("");
  const [threadState, setThreadState] = useState<ThreadStateResponse | null>(null);
  const [resumeJson, setResumeJson] = useState('{"action":"approve"}');
  const [lastResult, setLastResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const selectedThreadIdRef = useRef(selectedThreadId);

  const selectedThread = useMemo(
    () => threads?.threads.find((thread) => thread.thread_id === selectedThreadId),
    [selectedThreadId, threads],
  );

  useEffect(() => {
    selectedThreadIdRef.current = selectedThreadId;
  }, [selectedThreadId]);

  async function refreshAll(options: { silent?: boolean } = {}) {
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
      if (!selectedThreadIdRef.current && threadList.threads.length > 0) {
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

  async function runAction(action: () => Promise<Record<string, unknown>>) {
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
      await refreshAll();
      await refreshThreadState(shouldSelectResultThread ? resultThreadId : selectedThreadId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refreshAll();
    refreshModelProfiles({ silent: true });
    refreshEnrouteLearning({ silent: true });
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

  return (
    <main className="min-h-screen bg-zinc-50 text-zinc-950">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-4 py-4">
        <header className="flex flex-col gap-3 border-b border-zinc-200 pb-4 md:flex-row md:items-end md:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-normal">Productv2 控制台</h1>
            <p className="mt-1 text-sm text-zinc-500">
              本地 LangGraph 服务、任务状态和 resume 控制。
            </p>
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
              onClick={() =>
                page === "tasks"
                  ? refreshAll()
                  : page === "models"
                    ? refreshModelProfiles()
                    : refreshEnrouteLearning()
              }
              disabled={loading}
            >
              <RefreshCcw className="h-4 w-4" />
              刷新
            </Button>
          </div>
        </header>

        {error ? <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}
        {notice ? <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">{notice}</div> : null}

        {page === "tasks" ? (
          <section className="grid gap-4 lg:grid-cols-[360px_1fr]">
            <div className="flex flex-col gap-4">
              <ServerPanel
                server={server}
                loading={loading}
                onStart={() => runAction(() => startServer(2024) as Promise<Record<string, unknown>>)}
                onStop={() => runAction(() => stopServer() as Promise<Record<string, unknown>>)}
                onRestart={() => runAction(() => restartServer(2024) as Promise<Record<string, unknown>>)}
              />
              <WorkflowPanel
                loading={loading}
                onStart={() => runAction(() => startWorkflow(apiUrl, assistantId))}
                onRestart={() =>
                  runAction(() =>
                    restartWorkflow(apiUrl, assistantId, selectedThreadId),
                  )
                }
              />
              <ThreadList
                threads={threads?.threads ?? []}
                selectedThreadId={selectedThreadId}
                onSelect={setSelectedThreadId}
              />
            </div>

            <div className="flex flex-col gap-4">
              <ThreadDetail
                thread={selectedThread}
                state={threadState}
                resumeJson={resumeJson}
                setResumeJson={setResumeJson}
                loading={loading}
                onResume={(payload) =>
                  runAction(() =>
                    resumeThread(
                      apiUrl,
                      assistantId,
                      selectedThreadId,
                      payload,
                    ),
                  )
                }
                onOpenStudio={() => selectedThread?.studio_url && window.open(selectedThread.studio_url, "_blank")}
              />
              <ResultPanel result={lastResult} />
            </div>
          </section>
        ) : page === "models" ? (
          <ModelProfilesPage profiles={modelProfiles?.profiles ?? []} />
        ) : (
          <EnrouteLearningPage learning={enrouteLearning} />
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
    <nav className="flex rounded-md border border-zinc-200 bg-white p-1">
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
    </nav>
  );
}

function ServerPanel({
  server,
  loading,
  onStart,
  onStop,
  onRestart,
}: {
  server: ServerStatus | null;
  loading: boolean;
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
          <Button onClick={onStart} disabled={loading} variant="secondary">
            <Power className="h-4 w-4" />
            启动
          </Button>
          <Button onClick={onStop} disabled={loading} variant="outline">
            <Square className="h-4 w-4" />
            停止
          </Button>
          <Button onClick={onRestart} disabled={loading} variant="outline">
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
  onStart,
  onRestart,
}: {
  loading: boolean;
  onStart: () => void;
  onRestart: () => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Workflow</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-2">
        <Button onClick={onStart} disabled={loading}>
          <Play className="h-4 w-4" />
          新启动
        </Button>
        <Button onClick={onRestart} disabled={loading} variant="outline">
          <RefreshCcw className="h-4 w-4" />
          安全恢复
        </Button>
      </CardContent>
    </Card>
  );
}

function ThreadList({
  threads,
  selectedThreadId,
  onSelect,
}: {
  threads: WorkflowThread[];
  selectedThreadId: string;
  onSelect: (threadId: string) => void;
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
          threads.map((thread) => (
            <div
              key={thread.thread_id}
              className={`w-full select-text rounded-md border p-3 text-left transition-colors ${
                selectedThreadId === thread.thread_id
                  ? "border-zinc-950 bg-zinc-50"
                  : "border-zinc-200 bg-white hover:bg-zinc-50"
              }`}
            >
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="truncate font-mono text-xs">{thread.thread_id}</span>
                <div className="flex shrink-0 items-center gap-2">
                  <ThreadStopReasonBadge thread={thread} />
                  <Button
                    className="h-7 px-2 text-xs"
                    variant={selectedThreadId === thread.thread_id ? "default" : "outline"}
                    onClick={() => onSelect(thread.thread_id)}
                  >
                    查看
                  </Button>
                </div>
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
          ))
        )}
      </CardContent>
    </Card>
  );
}

function ModelProfilesPage({ profiles }: { profiles: ModelProfile[] }) {
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
        <div className="grid gap-4 xl:grid-cols-2">
          {profiles.map((profile) => (
            <ModelProfileCard key={profile.profile_key} profile={profile} />
          ))}
        </div>
      )}
    </section>
  );
}

function ModelProfileCard({ profile }: { profile: ModelProfile }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3">
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
      <CardContent className="grid gap-4 md:grid-cols-[260px_1fr]">
        <div className="min-w-0">
          {profile.image_path ? (
            <img
              className="aspect-[2/3] w-full rounded-md border border-zinc-200 bg-zinc-50 object-cover"
              src={imageDisplayUrl(profile.image_path, profile.image_mtime_ns)}
              alt={profile.name}
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

        <div className="min-w-0 space-y-3">
          <div className="grid gap-3 md:grid-cols-2">
            <InfoBlock label="身份" value={profile.ethnicity} />
            <InfoBlock label="年龄感" value={profile.age_feel} />
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
}: {
  learning: EnrouteLearningResponse | null;
}) {
  const [category, setCategory] = useState("all");
  const items = learning?.items ?? [];
  const categories = learning?.categories ?? [];
  const visibleItems =
    category === "all"
      ? items
      : items.filter((item) => item.enroute_category === category);

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-normal">Enroute 学习结果</h2>
          <p className="mt-1 text-sm text-zinc-500">
            已缓存的 Enroute 佩戴参考逆向分析，用于后续商品匹配和模特选择。
          </p>
        </div>
        <Badge variant="secondary">{learning?.total ?? 0} 条学习数据</Badge>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <InfoBlock label="总数" value={learning?.total ?? 0} />
        <InfoBlock label="类目数" value={categories.length} />
        <InfoBlock label="当前筛选" value={category === "all" ? "全部" : category} />
        <InfoBlock label="展示数量" value={visibleItems.length} />
      </div>

      <div className="flex flex-wrap gap-2 rounded-md border border-zinc-200 bg-white p-2">
        <Button
          className="h-8 px-2 text-xs"
          variant={category === "all" ? "default" : "outline"}
          onClick={() => setCategory("all")}
        >
          全部 ({learning?.total ?? 0})
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
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div className="min-w-0">
          <CardTitle>{item.enroute_title || item.enroute_product_id}</CardTitle>
          <p className="mt-1 break-all font-mono text-xs text-zinc-500">
            {item.enroute_product_id}
          </p>
        </div>
        <Badge variant="secondary">{item.enroute_category || "未分类"}</Badge>
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
              ["图片位置", item.image_position],
              ["模特", selectedModel.name || selectedModel.profile_key],
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

function ThreadDetail({
  thread,
  state,
  resumeJson,
  setResumeJson,
  loading,
  onResume,
  onOpenStudio,
}: {
  thread?: WorkflowThread;
  state: ThreadStateResponse | null;
  resumeJson: string;
  setResumeJson: (value: string) => void;
  loading: boolean;
  onResume: (payload: unknown) => void;
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

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div>
          <CardTitle>任务详情</CardTitle>
          <p className="mt-2 font-mono text-xs text-zinc-500">{thread.thread_id}</p>
        </div>
        <Button variant="outline" onClick={onOpenStudio}>
          <ExternalLink className="h-4 w-4" />
          Studio
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        <ProgressPanel progress={progress} threadStatus={thread.status} />
        <WorkflowNodesPanel
          thread={thread}
          state={state?.state}
          review={grsaiReview}
          canResume={canResume}
          loading={loading}
          resumeJson={resumeJson}
          setResumeJson={setResumeJson}
          onResume={onResume}
        />
        <StatePanel state={state?.state} />
      </CardContent>
    </Card>
  );
}

function ManualReviewActions({
  canResume,
  loading,
  resumeJson,
  setResumeJson,
  onResume,
}: {
  canResume: boolean;
  loading: boolean;
  resumeJson: string;
  setResumeJson: (value: string) => void;
  onResume: (payload: unknown) => void;
}) {
  const disabled = loading || !canResume;
  const [parseError, setParseError] = useState("");

  function submitCustomJson() {
    try {
      const payload = JSON.parse(resumeJson);
      setParseError("");
      onResume(payload);
    } catch (err) {
      setParseError(err instanceof Error ? err.message : "无效的 JSON");
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm font-medium">审核动作</p>
      <div className="grid gap-2 md:grid-cols-3">
        <Button onClick={() => onResume({ action: "approve" })} disabled={disabled}>
          Approve
        </Button>
        <Button
          variant="outline"
          onClick={() => onResume({ action: "regenerate" })}
          disabled={disabled}
        >
          Regenerate
        </Button>
        <Button
          variant="destructive"
          onClick={() => onResume({ action: "reject" })}
          disabled={disabled}
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

function WorkflowNodesPanel({
  thread,
  state,
  review,
  canResume,
  loading,
  resumeJson,
  setResumeJson,
  onResume,
}: {
  thread: WorkflowThread;
  state: unknown;
  review: GrsaiReview;
  canResume: boolean;
  loading: boolean;
  resumeJson: string;
  setResumeJson: (value: string) => void;
  onResume: (payload: unknown) => void;
}) {
  const nodes = buildWorkflowNodes({
    thread,
    state,
    review,
    canResume,
    loading,
    resumeJson,
    setResumeJson,
    onResume,
  });

  return (
    <div className="space-y-3">
      {nodes.map((node) => (
        <WorkflowNodeCard key={node.id} node={node} />
      ))}
    </div>
  );
}

function WorkflowNodeCard({ node }: { node: WorkflowNode }) {
  const showDetail = node.state !== "pending" && node.state !== "skipped";
  const rows = showDetail
    ? (node.rows ?? []).filter(([, value]) => !isEmptyDisplay(value))
    : [];
  return (
    <section className="rounded-md border border-zinc-200 bg-white">
      <div className="flex flex-wrap items-start justify-between gap-3 px-3 py-3">
        <div>
          <div className="flex items-center gap-2">
            <span className={`h-2.5 w-2.5 rounded-full ${nodeDotClass(node.state)}`} />
            <h3 className="text-sm font-medium">{node.title}</h3>
          </div>
          <p className="mt-1 text-sm text-zinc-600">{node.summary}</p>
        </div>
        <Badge variant={nodeBadgeVariant(node.state)}>{nodeStateLabel(node.state)}</Badge>
      </div>
      {rows.length ? (
        <div className="grid gap-2 border-t border-zinc-200 p-3 md:grid-cols-2">
          {rows.map(([label, value]) => (
            <InfoBlock key={label} label={label} value={value} />
          ))}
        </div>
      ) : null}
      {showDetail && node.content ? (
        <div className="border-t border-zinc-200 p-3">{node.content}</div>
      ) : null}
    </section>
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
  review,
  canResume,
  loading,
  resumeJson,
  setResumeJson,
  onResume,
}: {
  thread: WorkflowThread;
  state: unknown;
  review: GrsaiReview;
  canResume: boolean;
  loading: boolean;
  resumeJson: string;
  setResumeJson: (value: string) => void;
  onResume: (payload: unknown) => void;
}): WorkflowNode[] {
  const root = asRecord(state);
  const values = asRecord(root.values);
  const product = asRecord(values.selected_product);
  const rawdata = asRecord(product.rawdata);
  const mainImage = asRecord(values.main_image_result);
  const sizeReference = asRecord(values.size_reference_result);
  const enrouteReference = asRecord(values.enroute_reference_result);
  const enrouteAnalysis = asRecord(values.enroute_analysis_result);
  const wearing = asRecord(values.wearing_image_result);
  const nextNodes = Array.isArray(root.next) ? root.next.map(String) : thread.summary.next ?? [];
  const currentNode = nextNodes[0] || "";
  const failedProduct = asRecord(values.failed_product);
  const isFailed = Boolean(failedProduct.reason);

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
      id: "prepare_main_images",
      title: "准备主图",
      state: statusToNodeState(mainImage.status, "prepare_main_images", currentNode, nextNodes, isFailed),
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
      title: "尺寸检测",
      state: statusToNodeState(sizeReference.status, "detect_size_reference", currentNode, nextNodes, isFailed),
      summary: sizeReference.reason
        ? displayValue(sizeReference.reason)
        : "识别可用于比例判断的商品图。",
      rows: [
        ["状态", sizeReference.status],
        ["可判断尺寸", sizeReference.can_judge_size],
        ["尺寸参考图编号", sizeReference.size_reference_image_number],
        ["主图编号", sizeReference.main_image_number],
      ],
    },
    {
      id: "analyze_enroute_reference",
      title: "Enroute / 模特",
      state: statusToNodeState(enrouteAnalysis.status || enrouteReference.status, "analyze_enroute_reference", currentNode, nextNodes, isFailed),
      summary: displayValue(
        enrouteAnalysis.summary ||
          asRecord(enrouteAnalysis.selection).reason ||
          enrouteReference.reason ||
          "选择并分析同类目佩戴参考。",
      ),
      rows: [
        ["参考图状态", enrouteReference.status],
        ["分析状态", enrouteAnalysis.status],
        ["参考图", enrouteAnalysis.reference_image_path],
        ["模特", asRecord(asRecord(enrouteAnalysis.analysis).selected_model_profile).name],
      ],
      content: (
        <EnrouteNodePanel
          reference={enrouteReference}
          analysis={enrouteAnalysis}
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
          onRetry={() => onResume({ action: "regenerate" })}
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
  if (value === "failed" || value === "error" || isFailed) {
    return currentNode === nodeId || !currentNode ? "error" : "pending";
  }
  return nodeState(nodeId, currentNode, nextNodes, isFailed);
}

function nodeDotClass(state: WorkflowNodeState) {
  const classes: Record<WorkflowNodeState, string> = {
    done: "bg-emerald-500",
    active: "bg-amber-500",
    pending: "bg-zinc-300",
    error: "bg-red-500",
    skipped: "bg-zinc-400",
  };
  return classes[state];
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

function EnrouteNodePanel({
  reference,
  analysis,
}: {
  reference: Record<string, unknown>;
  analysis: Record<string, unknown>;
}) {
  const analysisJson = asRecord(analysis.analysis);
  const selection = asRecord(analysis.selection);
  const selectedModel = asRecord(analysisJson.selected_model_profile);
  const learningReferences = arrayValue(reference.learning_references);
  const learningResults = arrayValue(
    reference.learning_results || analysis.learning_results,
  );
  const selectedImagePath = stringValue(
    analysis.reference_image_path || reference.selected_image_path,
  );
  const selectedModelImagePath = stringValue(selectedModel.image_path);
  const selectionReason = displayValue(
    selection.reason || reference.selection_reason,
  );
  const summary = displayValue(analysis.summary || analysisJson.summary);
  const hasAnalysis = Object.keys(analysisJson).length > 0;
  const hasRaw = Object.keys(reference).length > 0 || Object.keys(analysis).length > 0;

  return (
    <div className="space-y-3">
      <div className="grid gap-3 lg:grid-cols-2">
        <KeyValuePanel
          title="参考图库选择"
          rows={[
            ["类目", reference.category || analysis.category],
            ["参考图数量", reference.reference_count],
            ["已有缓存", reference.cached_analysis_count],
            ["学习后缓存", reference.cached_analysis_count_after_learning],
            ["未学习数量", reference.unlearned_count],
            ["本次学习", reference.learning_count],
          ]}
        />
        <KeyValuePanel
          title="当前商品匹配"
          rows={[
            [
              "选中 Enroute",
              analysis.enroute_product_id || reference.selected_enroute_product_id,
            ],
            ["选择来源", analysis.cache || analysis.checkpoint],
            ["分析状态", analysis.status],
            [
              "模特",
              selectedModel.name || selectedModel.profile_key,
            ],
            ["选择依据", selectionReason],
          ]}
        />
      </div>

      {summary !== "-" ? (
        <div className="rounded-md border border-zinc-200 bg-zinc-50 p-3">
          <p className="text-sm font-medium">逆向摘要</p>
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

      {learningReferences.length > 0 || learningResults.length > 0 ? (
        <details className="rounded-md border border-zinc-200 bg-white">
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
            逆向学习记录
          </summary>
          <div className="space-y-3 border-t border-zinc-200 p-3">
            {learningReferences.length > 0 ? (
              <EnrouteRecordList title="待学习参考" items={learningReferences} />
            ) : null}
            {learningResults.length > 0 ? (
              <EnrouteRecordList title="学习结果" items={learningResults} />
            ) : null}
          </div>
        </details>
      ) : null}

      {hasAnalysis ? (
        <details className="rounded-md border border-zinc-200 bg-white">
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
            逆向分析 JSON
          </summary>
          <div className="border-t border-zinc-200 p-3">
            <CompactJson value={analysisJson} />
          </div>
        </details>
      ) : null}

      {hasRaw ? (
        <details className="rounded-md border border-zinc-200 bg-white">
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
            Enroute 原始结果
          </summary>
          <div className="border-t border-zinc-200 p-3">
            <CompactJson value={{ reference, analysis }} />
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

function GrsaiNodePanel({
  review,
  canResume,
  loading,
  onRetry,
}: {
  review: GrsaiReview;
  canResume: boolean;
  loading: boolean;
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
        <img
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

function buildGrsaiReview(state: unknown): GrsaiReview {
  const root = asRecord(state);
  const values = asRecord(root.values);
  const wearing = asRecord(values.wearing_image_result);
  const manualReview = latestManualReviewPayload(root, values);
  const selectedModelProfile = asRecord(
    wearing.selected_model_profile || manualReview.selected_model_profile,
  );
  const imageGeneration = asRecord(wearing.image_generation);
  const imageMap = new Map<string, ReviewImage>();

  addReviewImage(imageMap, "主图", stringValue(wearing.marked_main_image_path));
  addReviewImage(
    imageMap,
    "尺寸参考图",
    stringValue(wearing.marked_size_reference_image_path),
  );
  addReviewImage(
    imageMap,
    "Enroute 参考图",
    stringValue(wearing.enroute_reference_image_path || manualReview.enroute_reference_image_path),
  );
  addReviewImage(
    imageMap,
    "固定模特",
    stringValue(selectedModelProfile.image_path),
  );

  const inputImages = Array.isArray(wearing.input_images) ? wearing.input_images : [];
  inputImages.forEach((item, index) => {
    addReviewImage(imageMap, `输入图 ${index + 1}`, stringValue(item));
  });

  return {
    prompt: stringValue(wearing.prompt || manualReview.prompt),
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
  const running = Boolean(progress?.running || threadStatus === "busy");
  return (
    <div
      className={`rounded-md border p-3 ${
        running ? "border-emerald-200 bg-emerald-50" : "border-zinc-200 bg-white"
      }`}
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-medium">运行进度</p>
          <p className="mt-1 text-sm text-zinc-600">
            {progress?.message || "暂无运行进度。"}
          </p>
        </div>
        <Badge variant={running ? "success" : "secondary"}>
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
  return "";
}

function shouldAutoSelectResultThread(result: Record<string, unknown>) {
  if (result.mode === "resume_required") {
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
  const wearing = asRecord(values.wearing_image_result);
  const sizeReference = asRecord(values.size_reference_result);
  const enrouteReference = asRecord(values.enroute_reference_result);
  const enrouteAnalysis = asRecord(values.enroute_analysis_result);
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
          title="穿戴图"
          rows={[
            ["状态", wearing.status],
            ["原因", wearing.reason],
            ["生成图", wearing.generated_image_path],
            ["Attempt", wearing.attempt],
          ]}
        />
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <KeyValuePanel
          title="尺寸检测"
          rows={[
            ["状态", sizeReference.status],
            ["可判断尺寸", sizeReference.can_judge_size],
            ["尺寸参考图编号", sizeReference.size_reference_image_number],
            ["主图编号", sizeReference.main_image_number],
            ["原因", sizeReference.reason],
          ]}
        />
        <KeyValuePanel
          title="Enroute / 模特"
          rows={[
            ["参考图状态", enrouteReference.status],
            ["分析状态", enrouteAnalysis.status],
            ["参考图", enrouteAnalysis.reference_image_path],
            [
              "模特",
              asRecord(asRecord(enrouteAnalysis.analysis).selected_model_profile).name ||
                asRecord(asRecord(enrouteAnalysis.analysis).selected_model_profile)
                  .profile_key,
            ],
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
      <a href={url} target="_blank" rel="noreferrer" className="block">
        <img
          className={`w-full rounded-md border border-zinc-200 bg-white object-contain ${
            compact ? "max-h-40" : "max-h-72"
          }`}
          src={url}
          alt={label}
          loading="lazy"
        />
      </a>
      <p className="select-text break-all font-mono text-xs font-normal text-zinc-500">
        {path}
      </p>
    </div>
  );
}

function CompactJson({ value }: { value: unknown }) {
  return (
    <div className="space-y-3">
      <JsonImagePreviewStrip value={value} compact />
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
      <JsonImagePreviewStrip value={value} />
      <pre className="max-h-[520px] overflow-auto rounded-md border border-zinc-200 bg-zinc-950 p-3 text-xs leading-relaxed text-zinc-50">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

function JsonImagePreviewStrip({
  value,
  compact = false,
}: {
  value: unknown;
  compact?: boolean;
}) {
  const images = collectImageReferences(value);
  if (images.length === 0) {
    return null;
  }
  return (
    <details open className="rounded-md border border-zinc-200 bg-white">
      <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
        图片字段 ({images.length})
      </summary>
      <div className="grid gap-3 border-t border-zinc-200 p-3 md:grid-cols-2 xl:grid-cols-3">
        {images.map((image) => (
          <div key={`${image.label}-${image.path}`} className="min-w-0">
            <p className="mb-2 truncate text-xs font-medium text-zinc-500">
              {image.label}
            </p>
            <ImageValuePreview
              label={image.label}
              path={image.path}
              compact={compact}
            />
          </div>
        ))}
      </div>
    </details>
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
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

function collectImageReferences(value: unknown) {
  const results: Array<{ label: string; path: string }> = [];
  const seenObjects = new Set<object>();
  const seenPaths = new Set<string>();
  collectImageReferencesInner(value, "", results, seenObjects, seenPaths);
  return results;
}

function collectImageReferencesInner(
  value: unknown,
  label: string,
  results: Array<{ label: string; path: string }>,
  seenObjects: Set<object>,
  seenPaths: Set<string>,
) {
  if (results.length >= 24) {
    return;
  }
  const imagePath = imagePathFromValue(label, value);
  if (imagePath && !seenPaths.has(imagePath)) {
    seenPaths.add(imagePath);
    results.push({ label: label || "图片", path: imagePath });
    return;
  }
  if (!value || typeof value !== "object") {
    return;
  }
  if (seenObjects.has(value)) {
    return;
  }
  seenObjects.add(value);
  if (Array.isArray(value)) {
    value.forEach((item, index) =>
      collectImageReferencesInner(
        item,
        label ? `${label}[${index}]` : `[${index}]`,
        results,
        seenObjects,
        seenPaths,
      ),
    );
    return;
  }
  Object.entries(value as Record<string, unknown>).forEach(([key, child]) => {
    collectImageReferencesInner(
      child,
      label ? `${label}.${key}` : key,
      results,
      seenObjects,
      seenPaths,
    );
  });
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
