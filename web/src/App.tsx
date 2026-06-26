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
  Activity,
  ExternalLink,
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
  listThreads,
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

export default function App() {
  const [apiUrl, setApiUrl] = useState(DEFAULT_API_URL);
  const [assistantId, setAssistantId] = useState(DEFAULT_ASSISTANT_ID);
  const [server, setServer] = useState<ServerStatus | null>(null);
  const [threads, setThreads] = useState<ThreadsResponse | null>(null);
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
          <div className="grid gap-2 md:grid-cols-[240px_180px_auto] md:items-center">
            <Input value={apiUrl} onChange={(event) => setApiUrl(event.target.value)} />
            <Input
              value={assistantId}
              onChange={(event) => setAssistantId(event.target.value)}
            />
            <Button variant="outline" onClick={() => refreshAll()} disabled={loading}>
              <RefreshCcw className="h-4 w-4" />
              刷新
            </Button>
          </div>
        </header>

        {error ? <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}
        {notice ? <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">{notice}</div> : null}

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
      </div>
    </main>
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
          <Button
            variant="outline"
            onClick={() => onResume(JSON.parse(resumeJson))}
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
  rows?: Array<[string, string]>;
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
  return (
    <section className="rounded-md border border-zinc-200 bg-white">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-zinc-200 px-3 py-3">
        <div>
          <div className="flex items-center gap-2">
            <span className={`h-2.5 w-2.5 rounded-full ${nodeDotClass(node.state)}`} />
            <h3 className="text-sm font-medium">{node.title}</h3>
          </div>
          <p className="mt-1 text-sm text-zinc-600">{node.summary}</p>
        </div>
        <Badge variant={nodeBadgeVariant(node.state)}>{nodeStateLabel(node.state)}</Badge>
      </div>
      {node.rows?.length ? (
        <div className="grid gap-2 border-b border-zinc-200 p-3 md:grid-cols-2">
          {node.rows.map(([label, value]) => (
            <InfoBlock key={label} label={label} value={value} />
          ))}
        </div>
      ) : null}
      {node.content ? <div className="p-3">{node.content}</div> : null}
    </section>
  );
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
        ["产品 ID", displayValue(product.product_id || thread.summary.product_id)],
        ["平台", displayValue(product.platform || thread.summary.platform)],
        ["商品状态", displayValue(product.status || thread.summary.product_status)],
        ["标题", displayValue(rawdata.title || thread.summary.product_title)],
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
        ["合图", displayValue(mainImage.path)],
        ["图片数量", displayValue(mainImage.source_image_count)],
        ["临时文件", displayValue(mainImage.temporary)],
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
        ["状态", displayValue(sizeReference.status)],
        ["可判断尺寸", displayValue(sizeReference.can_judge_size)],
        ["尺寸参考图编号", displayValue(sizeReference.size_reference_image_number)],
        ["主图编号", displayValue(sizeReference.main_image_number)],
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
        ["参考图状态", displayValue(enrouteReference.status)],
        ["分析状态", displayValue(enrouteAnalysis.status)],
        ["参考图", displayValue(enrouteAnalysis.reference_image_path)],
        ["模特", displayValue(asRecord(asRecord(enrouteAnalysis.analysis).selected_model_profile).name)],
      ],
    },
    {
      id: "generate_wearing_image",
      title: "Grsai 生成穿戴图",
      state: statusToNodeState(wearing.status, "generate_wearing_image", currentNode, nextNodes, isFailed),
      summary: wearing.reason
        ? reasonLabel(displayValue(wearing.reason))
        : "调用 Grsai 生成穿戴图。",
      rows: [
        ["状态", displayValue(wearing.status)],
        ["Attempt", displayValue(wearing.attempt)],
        ["生成图", displayValue(wearing.generated_image_path || thread.summary.generated_image_path)],
        ["Grsai 任务", displayValue(asRecord(wearing.image_generation).id)],
      ],
      content: <GrsaiReviewPanel review={review} />,
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
        ["暂停数量", displayValue(thread.summary.interrupt_count)],
        ["停止原因", displayValue(thread.summary.stop_reason)],
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

function imageDisplayUrl(path: string) {
  if (!path) {
    return "";
  }
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  return `${CONTROL_API_BASE}/api/files/image?path=${encodeURIComponent(path)}`;
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

function InfoBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-zinc-200 bg-zinc-50 p-3">
      <p className="text-xs text-zinc-500">{label}</p>
      <p className="mt-1 truncate text-sm font-medium">{value}</p>
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
            ["产品 ID", displayValue(product.product_id)],
            ["平台", displayValue(product.platform)],
            ["状态", displayValue(product.status)],
            ["标题", displayValue(rawdata.title)],
          ]}
        />
        <KeyValuePanel
          title="穿戴图"
          rows={[
            ["状态", displayValue(wearing.status)],
            ["原因", displayValue(wearing.reason)],
            ["生成图", displayValue(wearing.generated_image_path)],
            ["Attempt", displayValue(wearing.attempt)],
          ]}
        />
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <KeyValuePanel
          title="尺寸检测"
          rows={[
            ["状态", displayValue(sizeReference.status)],
            ["可判断尺寸", displayValue(sizeReference.can_judge_size)],
            ["尺寸参考图编号", displayValue(sizeReference.size_reference_image_number)],
            ["主图编号", displayValue(sizeReference.main_image_number)],
            ["原因", displayValue(sizeReference.reason)],
          ]}
        />
        <KeyValuePanel
          title="Enroute / 模特"
          rows={[
            ["参考图状态", displayValue(enrouteReference.status)],
            ["分析状态", displayValue(enrouteAnalysis.status)],
            ["参考图", displayValue(enrouteAnalysis.reference_image_path)],
            [
              "模特",
              displayValue(
                asRecord(asRecord(enrouteAnalysis.analysis).selected_model_profile).name ||
                  asRecord(asRecord(enrouteAnalysis.analysis).selected_model_profile)
                    .profile_key,
              ),
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
        <InfoBlock label="Thread" value={displayValue(result.thread_id)} />
        <InfoBlock label="Run" value={displayValue(result.run_id)} />
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
            ["产品 ID", displayValue(summary.product_id)],
            ["标题", displayValue(summary.product_title)],
            ["当前节点", displayValue(summary.current_node_label)],
            ["停止原因", displayValue(summary.stop_reason)],
            ["详情", displayValue(summary.stop_reason_detail)],
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
  rows: Array<[string, string]>;
}) {
  return (
    <div className="rounded-md border border-zinc-200 bg-white p-3">
      <p className="mb-2 text-sm font-medium">{title}</p>
      <div className="space-y-2">
        {rows.map(([label, value]) => (
          <div key={label} className="grid gap-1 text-sm md:grid-cols-[120px_1fr]">
            <span className="text-zinc-500">{label}</span>
            <span className="min-w-0 break-words font-medium">{value || "-"}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function CompactJson({ value }: { value: unknown }) {
  return (
    <pre className="max-h-80 overflow-auto rounded-md bg-zinc-950 p-3 text-xs leading-relaxed text-zinc-50">
      {JSON.stringify(value, null, 2)}
    </pre>
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
