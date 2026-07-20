import { useMutation, useQuery } from "@tanstack/react-query"
import {
  Activity,
  ArrowDownToLine,
  ArrowRightLeft,
  ArrowUpFromLine,
  BarChart3,
  Bell,
  CalendarClock,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  Database,
  FileSearch,
  Gauge,
  Menu,
  RefreshCw,
  Search,
  Server,
  ShieldCheck,
  Sparkles,
  TrainFront,
  TrendingUp,
  X,
} from "lucide-react"
import type { ComponentType, FormEvent } from "react"
import { lazy, Suspense, useMemo, useState } from "react"
import {
  createAssistantSession,
  getAudit,
  getCatalog,
  getHealth,
  runForecast,
  runQuery,
  sendAssistantMessage,
} from "./api"
import type {
  AuditSummary,
  CatalogResponse,
  QueryRequest,
  QueryResponse,
  RunRecord,
} from "./client/types.gen"
import type { ChartProps } from "./components/MetricChart"
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  cn,
  Field,
  inputClass,
} from "./components/ui"

type Page =
  | "dashboard"
  | "assistant"
  | "query"
  | "forecast"
  | "audit"
  | "system"
type Icon = ComponentType<{ className?: string }>

const LazyMetricChart = lazy(() =>
  import("./components/MetricChart").then((module) => ({
    default: module.MetricChart,
  })),
)

function MetricChart(props: ChartProps) {
  return (
    <Suspense
      fallback={
        <div className="h-[260px] animate-pulse rounded-xl bg-white/4" />
      }
    >
      <LazyMetricChart {...props} />
    </Suspense>
  )
}

const navigation: Array<{
  id: Page
  label: string
  icon: Icon
  note?: string
}> = [
  { id: "dashboard", label: "运营总览", icon: Gauge },
  { id: "assistant", label: "智能分析", icon: Sparkles, note: "Agent" },
  { id: "query", label: "受约束查询", icon: BarChart3 },
  {
    id: "forecast",
    label: "基线预测",
    icon: CalendarClock,
    note: "参考日复制",
  },
  { id: "audit", label: "审计追踪", icon: ClipboardList },
  { id: "system", label: "系统状态", icon: Server },
]

const metricMeta = {
  entries: {
    label: "进站客流",
    icon: ArrowDownToLine,
    color: "#22d3ee",
    tint: "bg-cyan-400/10 text-cyan-300",
  },
  exits: {
    label: "出站客流",
    icon: ArrowUpFromLine,
    color: "#60a5fa",
    tint: "bg-blue-400/10 text-blue-300",
  },
  transfers: {
    label: "换乘客流",
    icon: ArrowRightLeft,
    color: "#a78bfa",
    tint: "bg-violet-400/10 text-violet-300",
  },
  net_inflow: {
    label: "净流入",
    icon: TrendingUp,
    color: "#34d399",
    tint: "bg-emerald-400/10 text-emerald-300",
  },
} as const

function formatNumber(value: unknown) {
  return typeof value === "number"
    ? new Intl.NumberFormat("zh-CN").format(value)
    : "—"
}

function displayTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value))
}

function ApiError({ error }: { error: unknown }) {
  return (
    <div className="rounded-xl border border-rose-400/20 bg-rose-400/8 p-4 text-sm text-rose-200">
      {error instanceof Error ? error.message : "请求失败，请检查服务状态"}
    </div>
  )
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="grid min-h-48 place-items-center rounded-xl border border-dashed border-white/10 text-sm text-slate-500">
      {text}
    </div>
  )
}

function PageHeading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string
  title: string
  description: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
      <div>
        <div className="mb-2 text-xs font-semibold uppercase tracking-[.22em] text-cyan-400">
          {eyebrow}
        </div>
        <h1 className="text-2xl font-semibold tracking-tight text-white md:text-3xl">
          {title}
        </h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
          {description}
        </p>
      </div>
      {action}
    </div>
  )
}

function buildQuery(
  catalog: CatalogResponse,
  metric: string,
  dimensions: QueryRequest["dimensions"] = [],
): QueryRequest {
  return {
    metric,
    time_range: catalog.default_time_range,
    dimensions,
    filters: [],
    limit: 100,
  }
}

function Dashboard() {
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: getCatalog })
  const health = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 60_000,
  })
  const overview = useQuery({
    queryKey: ["dashboard", catalog.data?.default_time_range],
    enabled: Boolean(catalog.data),
    queryFn: async () => {
      const source = catalog.data
      if (!source) throw new Error("Catalog is not ready")
      const [entries, exits, transfers, net, station, trend] =
        await Promise.all([
          runQuery(buildQuery(source, "entries")),
          runQuery(buildQuery(source, "exits")),
          runQuery(buildQuery(source, "transfers")),
          runQuery(buildQuery(source, "net_inflow")),
          runQuery(buildQuery(source, "entries", ["station"])),
          runQuery(buildQuery(source, "entries", ["time"])),
        ])
      return { entries, exits, transfers, net, station, trend }
    },
  })

  if (catalog.isError) return <ApiError error={catalog.error} />
  const source = catalog.data
  const cards = overview.data
    ? ([
        ["entries", overview.data.entries.rows[0]?.entries],
        ["exits", overview.data.exits.rows[0]?.exits],
        ["transfers", overview.data.transfers.rows[0]?.transfers],
        ["net_inflow", overview.data.net.rows[0]?.net_inflow],
      ] as const)
    : []
  const stationRows = [...(overview.data?.station.rows ?? [])].sort(
    (a, b) => Number(b.entries) - Number(a.entries),
  )
  const trendRows = overview.data?.trend.rows ?? []

  return (
    <div className="space-y-6">
      <PageHeading
        eyebrow="Operation intelligence"
        title="地铁客流运营总览"
        description="将受约束 QueryIR 的确定性结果汇总为运营视图。当前仅展示合成数据，不连接生产数据库。"
        action={
          <div className="flex items-center gap-2">
            <Badge tone={health.data?.status === "ok" ? "green" : "amber"}>
              <span className="mr-1.5 h-1.5 w-1.5 rounded-full bg-current" />
              API {health.data?.status === "ok" ? "运行正常" : "检测中"}
            </Badge>
            <Badge tone="slate">{source?.timezone ?? "Asia/Shanghai"}</Badge>
          </div>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {overview.isLoading
          ? ["entries", "exits", "transfers", "net"].map((key) => (
              <div
                key={key}
                className="h-36 animate-pulse rounded-2xl bg-white/5"
              />
            ))
          : cards.map(([key, value]) => {
              const meta = metricMeta[key]
              const Icon = meta.icon
              return (
                <Card key={key} className="overflow-hidden p-5">
                  <div className="flex items-start justify-between">
                    <div
                      className={cn(
                        "grid h-10 w-10 place-items-center rounded-xl",
                        meta.tint,
                      )}
                    >
                      <Icon className="h-5 w-5" />
                    </div>
                    <Activity className="h-4 w-4 text-slate-600" />
                  </div>
                  <div className="mt-5 text-3xl font-semibold tracking-tight text-white">
                    {formatNumber(value)}
                  </div>
                  <div className="mt-1 text-sm text-slate-400">
                    {meta.label} <span className="text-slate-600">· 人次</span>
                  </div>
                </Card>
              )
            })}
      </div>

      {overview.isError ? <ApiError error={overview.error} /> : null}

      <div className="grid gap-5 xl:grid-cols-[1.6fr_1fr]">
        <Card>
          <CardHeader>
            <div>
              <h2 className="font-semibold text-white">分时客流趋势</h2>
              <p className="mt-1 text-xs text-slate-500">
                进站量 · 半开时间区间
              </p>
            </div>
            <Badge tone="cyan">ECharts</Badge>
          </CardHeader>
          <CardContent>
            {trendRows.length ? (
              <MetricChart
                labels={trendRows.map((row) => displayTime(String(row.time)))}
                values={trendRows.map((row) => Number(row.entries))}
                kind="line"
                name="进站量"
              />
            ) : (
              <EmptyState text="正在读取趋势数据" />
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <div>
              <h2 className="font-semibold text-white">站点客流排行</h2>
              <p className="mt-1 text-xs text-slate-500">按进站量降序</p>
            </div>
            <TrainFront className="h-5 w-5 text-cyan-400" />
          </CardHeader>
          <CardContent className="space-y-4">
            {stationRows.map((row, index) => {
              const max = Number(stationRows[0]?.entries || 1)
              return (
                <div key={String(row.station)}>
                  <div className="mb-2 flex items-center justify-between text-sm">
                    <span className="text-slate-300">
                      <span className="mr-3 text-xs text-slate-600">
                        {String(index + 1).padStart(2, "0")}
                      </span>
                      {String(row.station)}
                    </span>
                    <strong className="text-slate-100">
                      {formatNumber(row.entries)}
                    </strong>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-white/5">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-cyan-500 to-blue-400"
                      style={{ width: `${(Number(row.entries) / max) * 100}%` }}
                    />
                  </div>
                </div>
              )
            })}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent className="grid gap-5 md:grid-cols-3">
          <StatusBlock
            icon={Database}
            label="数据范围"
            value="Synthetic fixtures"
            detail={`${source?.lines.length ?? 0} 条线路 · ${source?.stations.length ?? 0} 个站点`}
          />
          <StatusBlock
            icon={ShieldCheck}
            label="查询治理"
            value="QueryIR allowlist"
            detail="固定指标 · 参数化查询 · 审计回读"
          />
          <StatusBlock
            icon={CalendarClock}
            label="可用日期"
            value={source?.available_dates[0] ?? "—"}
            detail="预测仅为参考日模式复制"
          />
        </CardContent>
      </Card>
    </div>
  )
}

function StatusBlock({
  icon: Icon,
  label,
  value,
  detail,
}: {
  icon: Icon
  label: string
  value: string
  detail: string
}) {
  return (
    <div className="flex gap-4">
      <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-white/5 text-cyan-300">
        <Icon className="h-5 w-5" />
      </div>
      <div>
        <div className="text-xs uppercase tracking-wider text-slate-500">
          {label}
        </div>
        <div className="mt-1 font-semibold text-white">{value}</div>
        <div className="mt-1 text-xs text-slate-500">{detail}</div>
      </div>
    </div>
  )
}

function ResultsView({ result }: { result: QueryResponse }) {
  const columns = result.rows.length ? Object.keys(result.rows[0]) : []
  const labels = result.rows.map((row, index) =>
    String(row[result.dimensions[0]] ?? index + 1),
  )
  const values = result.rows.map((row) => Number(row[result.metric]))
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="green">查询成功</Badge>
        <Badge tone="slate">{result.row_count} 行</Badge>
        <Badge tone="cyan">{result.metric}</Badge>
        <span className="ml-auto max-w-full truncate font-mono text-[11px] text-slate-600">
          {result.audit.audit_id}
        </span>
      </div>
      {result.rows.length > 1 ? (
        <MetricChart labels={labels} values={values} name={result.metric} />
      ) : null}
      <div className="overflow-auto rounded-xl border border-white/8">
        <table className="data-table">
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column}>{column}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.rows.map((row) => (
              <tr key={JSON.stringify(row)}>
                {columns.map((column) => (
                  <td key={column}>
                    {typeof row[column] === "number"
                      ? formatNumber(row[column])
                      : String(row[column] ?? "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

const assistantExamples = [
  "查询各站进站客流并排序",
  "奥体中心有 4 万人演唱会，预测客流并给出建议",
  "昨天客流为什么下降？",
  "绘制工作日上午通勤热力图",
]

function AssistantRunView({ run }: { run: RunRecord }) {
  const tools = run.tool_results ?? []
  const events = run.events ?? []
  const planSteps = run.plan?.steps ?? []
  const evidenceGroups = run.evidence
    ? [
        ...(run.evidence.facts ?? []),
        ...(run.evidence.statistics ?? []),
        ...(run.evidence.charts ?? []),
        ...(run.evidence.model_outputs ?? []),
        ...(run.evidence.knowledge_sources ?? []),
      ]
    : []
  const tableEntries = tools
    .flatMap((tool) =>
      (tool.rows ?? []).map((row) => ({
        key: `${tool.step_id}-${JSON.stringify(row)}`,
        row,
      })),
    )
    .slice(0, 20)
  const tableRows = tableEntries.map((entry) => entry.row)
  const columns = tableRows[0] ? Object.keys(tableRows[0]).slice(0, 6) : []
  const numericColumn = columns.find((column) =>
    tableRows.some((row) => typeof row[column] === "number"),
  )
  const labelColumn = columns.find((column) => column !== numericColumn)
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={run.status === "completed" ? "green" : "amber"}>
          {run.status}
        </Badge>
        <Badge tone="cyan">{run.intent?.task_type ?? "understand"}</Badge>
        <Badge tone="slate">{run.provider}</Badge>
        <span className="ml-auto font-mono text-[11px] text-slate-600">
          {run.run_id}
        </span>
      </div>
      <div className="rounded-xl border border-cyan-400/12 bg-cyan-400/5 p-4">
        <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-cyan-300">
          证据化回答
        </div>
        <p className="text-sm leading-7 text-slate-200">
          {run.response?.answer ?? "尚未生成回答"}
        </p>
        {run.response?.limitations?.length ? (
          <div className="mt-3 space-y-1 border-t border-white/6 pt-3 text-xs text-amber-200/75">
            {run.response.limitations.map((item) => (
              <div key={item}>限制：{item}</div>
            ))}
          </div>
        ) : null}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <h3 className="mb-3 text-sm font-semibold text-white">
            执行计划与工具
          </h3>
          <div className="space-y-2">
            {planSteps.map((step) => (
              <div
                key={`plan-${step.step_id}`}
                className="rounded-xl border border-cyan-400/10 bg-cyan-400/4 p-3"
              >
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-mono text-xs text-cyan-400">
                    {step.step_id}
                  </span>
                  <strong className="text-slate-200">{step.tool}</strong>
                  <Badge tone="slate">计划步骤</Badge>
                </div>
                <p className="mt-2 break-all font-mono text-[11px] leading-5 text-slate-500">
                  depends_on: {(step.depends_on ?? []).join(", ") || "none"}
                  <br />
                  arguments: {JSON.stringify(step.arguments)}
                </p>
              </div>
            ))}
            {run.plan?.expected_evidence?.length ? (
              <p className="rounded-lg border border-white/6 px-3 py-2 text-xs text-slate-500">
                expected evidence: {run.plan.expected_evidence.join(" · ")}
              </p>
            ) : null}
            <div className="pt-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
              实际工具结果
            </div>
            {tools.map((tool) => (
              <div
                key={tool.step_id}
                className="rounded-xl border border-white/7 bg-white/3 p-3"
              >
                <div className="flex items-center gap-2 text-sm">
                  <span className="font-mono text-xs text-cyan-400">
                    {tool.step_id}
                  </span>
                  <strong className="text-slate-200">{tool.tool}</strong>
                  <Badge tone={tool.status === "success" ? "green" : "amber"}>
                    {tool.status}
                  </Badge>
                </div>
                <p className="mt-2 text-xs leading-5 text-slate-500">
                  {String(
                    tool.summary?.claim ?? `${tool.rows?.length ?? 0} rows`,
                  )}
                </p>
              </div>
            ))}
          </div>
        </div>
        <div>
          <h3 className="mb-3 text-sm font-semibold text-white">
            状态机时间线
          </h3>
          <div className="space-y-2">
            {events.map((event) => (
              <div
                key={String(event.timestamp)}
                className="grid grid-cols-[92px_1fr] gap-3 text-xs"
              >
                <span className="font-mono text-cyan-400">
                  {String(event.state)}
                </span>
                <span className="text-slate-500">{String(event.detail)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
      {tableRows.length ? (
        <div className="grid gap-4 xl:grid-cols-[0.85fr_1.15fr]">
          <div className="min-w-0">
            <h3 className="mb-3 text-sm font-semibold text-white">
              工具结果图表
            </h3>
            {numericColumn ? (
              <MetricChart
                labels={tableRows.map((row, index) =>
                  String(row[labelColumn ?? ""] ?? `#${index + 1}`),
                )}
                values={tableRows.map((row) => Number(row[numericColumn] ?? 0))}
                name={numericColumn}
                color="#22d3ee"
              />
            ) : (
              <EmptyState text="当前结果没有可绘制的数值列" />
            )}
          </div>
          <div className="min-w-0">
            <h3 className="mb-3 text-sm font-semibold text-white">
              结果数据表
            </h3>
            <div className="overflow-auto rounded-xl border border-white/8">
              <table className="data-table">
                <thead>
                  <tr>
                    {columns.map((column) => (
                      <th key={column}>{column}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {tableEntries.map(({ key, row }) => (
                    <tr key={key}>
                      {columns.map((column) => (
                        <td key={column}>{String(row[column] ?? "—")}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : null}
      {evidenceGroups.length ? (
        <div>
          <h3 className="mb-3 text-sm font-semibold text-white">
            Evidence Packet
          </h3>
          <div className="grid gap-2 md:grid-cols-2">
            {evidenceGroups.map((item) => (
              <div
                key={item.evidence_id}
                className="rounded-xl border border-white/7 bg-white/3 p-3"
              >
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-cyan-400">
                    {item.evidence_id}
                  </span>
                  <Badge tone="slate">{item.kind}</Badge>
                </div>
                <p className="mt-2 text-xs leading-5 text-slate-400">
                  {item.claim}
                </p>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      {run.response?.recommendations?.length ? (
        <div className="rounded-xl border border-amber-300/12 bg-amber-300/5 p-4">
          <div className="mb-2 text-sm font-semibold text-amber-200">
            处置建议（待人工确认）
          </div>
          <ul className="space-y-1 text-sm text-slate-400">
            {run.response.recommendations.map((item) => (
              <li key={item}>• {item}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}

function AssistantPage() {
  const session = useQuery({
    queryKey: ["assistant-session"],
    queryFn: createAssistantSession,
    staleTime: Number.POSITIVE_INFINITY,
  })
  const [message, setMessage] = useState(assistantExamples[0])
  const [runs, setRuns] = useState<RunRecord[]>([])
  const mutation = useMutation({
    mutationFn: async (value: string) => {
      if (!session.data) throw new Error("智能分析会话尚未就绪")
      return sendAssistantMessage(session.data.session_id, value)
    },
    onSuccess: (run) => setRuns((current) => [...current, run]),
  })
  function submit(event: FormEvent) {
    event.preventDefault()
    if (message.trim()) mutation.mutate(message.trim())
  }
  return (
    <div className="space-y-6">
      <PageHeading
        eyebrow="Governed agent workflow"
        title="地铁客流智能分析"
        description="同一可替换模型分阶段完成意图理解、任务规划、工具调用、证据综合和回答；确定性工具负责所有数字、统计、预测情景和 GIS 数据。"
        action={<Badge tone="cyan">完整轨迹可回放</Badge>}
      />
      <div className="grid gap-5 xl:grid-cols-[380px_1fr]">
        <Card className="h-fit">
          <CardHeader>
            <div>
              <h2 className="font-semibold text-white">业务问题</h2>
              <p className="mt-1 text-xs text-slate-500">
                当前默认离线 FakeProvider；配置后可替换 GPT-5.6-sol
              </p>
            </div>
            <Sparkles className="h-5 w-5 text-cyan-300" />
          </CardHeader>
          <CardContent>
            {runs.length ? (
              <div className="mb-4 max-h-72 space-y-3 overflow-auto rounded-xl border border-white/7 bg-black/10 p-3">
                {runs.map((run) => (
                  <div key={run.run_id} className="space-y-1 text-xs">
                    <div className="rounded-lg bg-cyan-400/7 p-2 text-cyan-100">
                      用户：{run.original_question}
                    </div>
                    <div className="rounded-lg bg-white/4 p-2 leading-5 text-slate-400">
                      助手：{run.response?.answer ?? run.status}
                    </div>
                  </div>
                ))}
              </div>
            ) : null}
            <form className="space-y-4" onSubmit={submit}>
              <Field label="自然语言任务">
                <textarea
                  aria-label="自然语言任务"
                  className={cn(inputClass, "min-h-32 resize-y")}
                  value={message}
                  onChange={(event) => setMessage(event.target.value)}
                  maxLength={4000}
                />
              </Field>
              <div className="flex flex-wrap gap-2">
                {assistantExamples.map((example) => (
                  <button
                    type="button"
                    className="rounded-lg border border-white/8 px-2.5 py-1.5 text-left text-[11px] text-slate-500 hover:text-cyan-300"
                    key={example}
                    onClick={() => setMessage(example)}
                  >
                    {example}
                  </button>
                ))}
              </div>
              <Button
                className="w-full"
                disabled={!session.data || mutation.isPending}
              >
                {mutation.isPending ? (
                  <RefreshCw className="h-4 w-4 animate-spin" />
                ) : (
                  <Sparkles className="h-4 w-4" />
                )}
                {mutation.isPending ? "正在执行状态机" : "开始智能分析"}
              </Button>
            </form>
          </CardContent>
        </Card>
        <Card className="min-w-0">
          <CardHeader>
            <div>
              <h2 className="font-semibold text-white">回答、证据与轨迹</h2>
              <p className="mt-1 text-xs text-slate-500">
                {session.data?.session_id ?? "正在创建会话"}
              </p>
            </div>
            {mutation.data?.verification?.valid ? (
              <Badge tone="green">Evidence verified</Badge>
            ) : (
              <Badge tone="slate">等待任务</Badge>
            )}
          </CardHeader>
          <CardContent>
            {session.isError ? (
              <ApiError error={session.error} />
            ) : mutation.isError ? (
              <ApiError error={mutation.error} />
            ) : mutation.data ? (
              <AssistantRunView run={mutation.data} />
            ) : (
              <EmptyState text="输入业务问题，查看计划、工具时间线、Evidence Packet 和回答" />
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function QueryWorkbench() {
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: getCatalog })
  const [metric, setMetric] = useState("entries")
  const [dimension, setDimension] = useState<
    QueryRequest["dimensions"][number] | "none"
  >("station")
  const [line, setLine] = useState("all")
  const [station, setStation] = useState("all")
  const [direction, setDirection] = useState("all")
  const mutation = useMutation({ mutationFn: runQuery })

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!catalog.data) return
    const filters: QueryRequest["filters"] = []
    if (line !== "all")
      filters.push({ field: "line_id", operator: "eq", value: line })
    if (station !== "all")
      filters.push({ field: "station_id", operator: "eq", value: station })
    if (direction !== "all")
      filters.push({ field: "direction", operator: "eq", value: direction })
    mutation.mutate({
      metric,
      dimensions: dimension === "none" ? [] : [dimension],
      filters,
      limit: 100,
      time_range: catalog.data.default_time_range,
    })
  }

  return (
    <div className="space-y-6">
      <PageHeading
        eyebrow="Governed analytics"
        title="受约束客流查询"
        description="只选择注册指标、维度和过滤条件；浏览器不会接收或提交自由 SQL。每次执行都会生成可回读的审计摘要。"
      />
      <div className="grid gap-5 xl:grid-cols-[380px_1fr]">
        <Card className="h-fit">
          <CardHeader>
            <div>
              <h2 className="font-semibold text-white">QueryIR 构建器</h2>
              <p className="mt-1 text-xs text-slate-500">
                字段来自后端 catalog
              </p>
            </div>
            <ShieldCheck className="h-5 w-5 text-emerald-400" />
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={submit}>
              <Field label="业务指标">
                <select
                  className={inputClass}
                  value={metric}
                  onChange={(event) => setMetric(event.target.value)}
                >
                  {catalog.data?.metrics.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label} · {item.unit}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="分组维度">
                <select
                  className={inputClass}
                  value={dimension}
                  onChange={(event) =>
                    setDimension(event.target.value as typeof dimension)
                  }
                >
                  <option value="none">不分组（合计）</option>
                  {catalog.data?.dimensions.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="线路">
                  <select
                    className={inputClass}
                    value={line}
                    onChange={(event) => setLine(event.target.value)}
                  >
                    <option value="all">全部</option>
                    {catalog.data?.lines.map((item) => (
                      <option key={item}>{item}</option>
                    ))}
                  </select>
                </Field>
                <Field label="方向">
                  <select
                    className={inputClass}
                    value={direction}
                    onChange={(event) => setDirection(event.target.value)}
                  >
                    <option value="all">全部</option>
                    {catalog.data?.directions.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
              <Field label="车站">
                <select
                  className={inputClass}
                  value={station}
                  onChange={(event) => setStation(event.target.value)}
                >
                  <option value="all">全部</option>
                  {catalog.data?.stations.map((item) => (
                    <option key={item}>{item}</option>
                  ))}
                </select>
              </Field>
              <Field label="查询时间" hint="后端 catalog">
                <div className="rounded-xl border border-white/8 bg-[#07111f] p-3 text-xs leading-5 text-slate-400">
                  {catalog.data
                    ? `${displayTime(catalog.data.default_time_range.start)} — ${displayTime(catalog.data.default_time_range.end)}`
                    : "加载中"}
                </div>
              </Field>
              <Button
                className="w-full"
                disabled={!catalog.data || mutation.isPending}
              >
                {mutation.isPending ? (
                  <RefreshCw className="h-4 w-4 animate-spin" />
                ) : (
                  <Search className="h-4 w-4" />
                )}
                {mutation.isPending ? "执行中" : "执行安全查询"}
              </Button>
            </form>
          </CardContent>
        </Card>
        <Card className="min-w-0">
          <CardHeader>
            <div>
              <h2 className="font-semibold text-white">查询结果</h2>
              <p className="mt-1 text-xs text-slate-500">
                图表与表格消费同一 API 响应
              </p>
            </div>
            {mutation.data ? (
              <Badge tone="green">已审计</Badge>
            ) : (
              <Badge tone="slate">等待查询</Badge>
            )}
          </CardHeader>
          <CardContent>
            {mutation.isError ? (
              <ApiError error={mutation.error} />
            ) : mutation.data ? (
              <ResultsView result={mutation.data} />
            ) : (
              <EmptyState text="选择指标与维度后执行查询" />
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function ForecastPage() {
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: getCatalog })
  const [referenceDate, setReferenceDate] = useState("")
  const [targetDate, setTargetDate] = useState("")
  const [schemeId, setSchemeId] = useState(1)
  const mutation = useMutation({ mutationFn: runForecast })
  const defaultReference =
    referenceDate || catalog.data?.available_dates[0] || ""
  const defaultTarget =
    targetDate ||
    (defaultReference
      ? new Date(
          new Date(`${defaultReference}T00:00:00`).getTime() + 86_400_000,
        )
          .toISOString()
          .slice(0, 10)
      : "")

  function submit(event: FormEvent) {
    event.preventDefault()
    mutation.mutate({
      reference_date: defaultReference,
      target_date: defaultTarget,
      scheme_id: schemeId,
      limit: 1000,
    })
  }
  const rows = mutation.data?.rows ?? []
  const stationTotals = useMemo(() => {
    const totals = new Map<string, number>()
    for (const row of rows)
      totals.set(
        String(row.station_id),
        (totals.get(String(row.station_id)) ?? 0) + Number(row.entries),
      )
    return [...totals.entries()]
  }, [rows])

  return (
    <div className="space-y-6">
      <PageHeading
        eyebrow="Scenario preview"
        title="指定日基线预测"
        description="把参考日的站点进出站模式映射到目标日，用于验证预测链路和界面；方法明确标注为 reference_day_copy，不代表机器学习精度。"
        action={<Badge tone="amber">非 ML 模型</Badge>}
      />
      <div className="grid gap-5 xl:grid-cols-[380px_1fr]">
        <Card className="h-fit">
          <CardHeader>
            <div>
              <h2 className="font-semibold text-white">预测参数</h2>
              <p className="mt-1 text-xs text-slate-500">
                只读生成 · 不写数据库
              </p>
            </div>
            <Sparkles className="h-5 w-5 text-amber-300" />
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={submit}>
              <Field label="参考日期">
                <select
                  className={inputClass}
                  value={defaultReference}
                  onChange={(event) => setReferenceDate(event.target.value)}
                >
                  {catalog.data?.available_dates.map((item) => (
                    <option key={item}>{item}</option>
                  ))}
                </select>
              </Field>
              <Field label="目标日期">
                <input
                  className={inputClass}
                  type="date"
                  value={defaultTarget}
                  onChange={(event) => setTargetDate(event.target.value)}
                  required
                />
              </Field>
              <Field label="方案编号">
                <input
                  className={inputClass}
                  type="number"
                  min="0"
                  value={schemeId}
                  onChange={(event) => setSchemeId(Number(event.target.value))}
                />
              </Field>
              <div className="rounded-xl border border-amber-300/15 bg-amber-300/6 p-3 text-xs leading-5 text-amber-100/70">
                输出复制参考日客流结构，仅用于受治理的 baseline
                preview。页面不会声称模型准确率。
              </div>
              <Button
                className="w-full"
                disabled={!defaultReference || mutation.isPending}
              >
                {mutation.isPending ? (
                  <RefreshCw className="h-4 w-4 animate-spin" />
                ) : (
                  <CalendarClock className="h-4 w-4" />
                )}
                生成预测预览
              </Button>
            </form>
          </CardContent>
        </Card>
        <Card className="min-w-0">
          <CardHeader>
            <div>
              <h2 className="font-semibold text-white">预测预览</h2>
              <p className="mt-1 text-xs text-slate-500">
                目标日 {mutation.data?.target_date ?? "—"}
              </p>
            </div>
            {mutation.data ? (
              <Badge tone="green">{mutation.data.row_count} 行</Badge>
            ) : null}
          </CardHeader>
          <CardContent>
            {mutation.isError ? (
              <ApiError error={mutation.error} />
            ) : mutation.data ? (
              <div className="space-y-5">
                <div className="grid gap-3 sm:grid-cols-3">
                  <MiniStat label="方法" value="reference_day_copy" />
                  <MiniStat
                    label="方案"
                    value={`#${mutation.data.scheme_id}`}
                  />
                  <MiniStat label="审计" value="已生成" />
                </div>
                <MetricChart
                  labels={stationTotals.map(([station]) => station)}
                  values={stationTotals.map(([, value]) => value)}
                  name="预测进站量"
                  color="#fbbf24"
                />
                <div className="overflow-auto rounded-xl border border-white/8">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>时间</th>
                        <th>线路</th>
                        <th>车站</th>
                        <th>方向</th>
                        <th>进站</th>
                        <th>出站</th>
                        <th>换乘</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.slice(0, 20).map((row) => (
                        <tr
                          key={`${String(row.timestamp)}-${String(row.station_id)}-${String(row.direction)}`}
                        >
                          <td>{displayTime(String(row.timestamp))}</td>
                          <td>{String(row.line_id)}</td>
                          <td>{String(row.station_id)}</td>
                          <td>{String(row.direction)}</td>
                          <td>{formatNumber(row.entries)}</td>
                          <td>{formatNumber(row.exits)}</td>
                          <td>{formatNumber(row.transfers)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : (
              <EmptyState text="设置参考日与目标日后生成预览" />
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-white/4 p-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-slate-200">
        {value}
      </div>
    </div>
  )
}

function AuditPage() {
  const [auditId, setAuditId] = useState("")
  const mutation = useMutation({ mutationFn: getAudit })
  function submit(event: FormEvent) {
    event.preventDefault()
    mutation.mutate(auditId.trim())
  }
  return (
    <div className="space-y-6">
      <PageHeading
        eyebrow="Traceability"
        title="审计记录回读"
        description="按服务返回的 audit id 查询脱敏摘要。页面不显示原始筛选值、SQL、凭证或生产数据。"
      />
      <div className="grid gap-5 lg:grid-cols-[1fr_1.2fr]">
        <Card>
          <CardHeader>
            <div>
              <h2 className="font-semibold text-white">查找审计记录</h2>
              <p className="mt-1 text-xs text-slate-500">
                query-* 或 forecast-*
              </p>
            </div>
            <FileSearch className="h-5 w-5 text-cyan-300" />
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={submit}>
              <Field label="Audit ID">
                <input
                  className={inputClass}
                  value={auditId}
                  onChange={(event) => setAuditId(event.target.value)}
                  placeholder="query-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                  pattern="(?:query|forecast)-[0-9a-f]{32}"
                  required
                />
              </Field>
              <Button disabled={mutation.isPending} className="w-full">
                <Search className="h-4 w-4" />
                回读摘要
              </Button>
            </form>
            <div className="mt-5 rounded-xl border border-white/8 bg-white/3 p-4 text-xs leading-6 text-slate-500">
              <ShieldCheck className="mb-2 h-5 w-5 text-emerald-400" />
              审计响应只包含操作、状态、行数、数据源和查询指纹。原始 QueryIR
              保留在受控服务端 artifact 中。
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <div>
              <h2 className="font-semibold text-white">审计摘要</h2>
              <p className="mt-1 text-xs text-slate-500">可验证执行身份</p>
            </div>
            {mutation.data ? <Badge tone="green">Verified</Badge> : null}
          </CardHeader>
          <CardContent>
            {mutation.isError ? (
              <ApiError error={mutation.error} />
            ) : mutation.data ? (
              <AuditDetails audit={mutation.data} />
            ) : (
              <EmptyState text="输入一次查询或预测返回的 audit id" />
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function AuditDetails({ audit }: { audit: AuditSummary }) {
  const items = [
    ["状态", audit.status],
    ["操作", audit.operation],
    ["生成时间", new Date(audit.created_at).toLocaleString("zh-CN")],
    ["结果行数", String(audit.row_count)],
    ["数据源", audit.data_source],
    ["查询指纹", audit.query_fingerprint],
  ]
  return (
    <div className="space-y-1">
      {items.map(([label, value]) => (
        <div
          key={label}
          className="grid gap-1 border-b border-white/6 py-3 last:border-0 sm:grid-cols-[120px_1fr]"
        >
          <span className="text-xs text-slate-500">{label}</span>
          <span
            className={cn(
              "break-all text-sm text-slate-200",
              label === "查询指纹" && "font-mono text-xs",
            )}
          >
            {value}
          </span>
        </div>
      ))}
    </div>
  )
}

function SystemPage() {
  const health = useQuery({ queryKey: ["health"], queryFn: getHealth })
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: getCatalog })
  return (
    <div className="space-y-6">
      <PageHeading
        eyebrow="Runtime"
        title="系统与数据状态"
        description="显示前后端运行边界、版本、数据范围和 API 契约来源；不探测或暴露服务器敏感配置。"
        action={
          <Button
            variant="secondary"
            onClick={() => {
              health.refetch()
              catalog.refetch()
            }}
          >
            <RefreshCw className="h-4 w-4" />
            重新检测
          </Button>
        }
      />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <SystemCard
          icon={Server}
          label="后端服务"
          value={health.data?.service ?? "检测中"}
          status={health.data?.status === "ok"}
          detail={`v${health.data?.version ?? "—"} · ${health.data?.environment ?? "—"}`}
        />
        <SystemCard
          icon={Database}
          label="数据范围"
          value={health.data?.data_scope ?? "—"}
          status={health.data?.data_scope === "synthetic"}
          detail="未连接生产数据库"
        />
        <SystemCard
          icon={ShieldCheck}
          label="接口契约"
          value="OpenAPI generated"
          status
          detail="TypeScript 客户端自动生成"
        />
      </div>
      <Card>
        <CardHeader>
          <div>
            <h2 className="font-semibold text-white">能力边界</h2>
            <p className="mt-1 text-xs text-slate-500">Protected baseline</p>
          </div>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <Boundary
            good
            title="当前启用"
            items={[
              "FastAPI 合成数据服务",
              "受约束 QueryIR 查询",
              "指定日 baseline preview",
              "脱敏审计摘要",
              "React + ECharts 展示",
            ]}
          />
          <Boundary
            title="明确未启用"
            items={[
              "自由 SQL / 模型生成 SQL",
              "生产数据库连接",
              "自动写入与处置",
              "公网域名与 HTTPS",
              "真实预测精度声明",
            ]}
          />
        </CardContent>
      </Card>
      <Card>
        <CardContent className="grid gap-5 md:grid-cols-3">
          <StatusBlock
            icon={TrainFront}
            label="线路"
            value={String(catalog.data?.lines.length ?? "—")}
            detail={catalog.data?.lines.join("、") || "等待 catalog"}
          />
          <StatusBlock
            icon={Database}
            label="站点"
            value={String(catalog.data?.stations.length ?? "—")}
            detail={catalog.data?.stations.join("、") || "等待 catalog"}
          />
          <StatusBlock
            icon={Activity}
            label="注册指标"
            value={String(catalog.data?.metrics.length ?? "—")}
            detail={
              catalog.data?.metrics.map((item) => item.label).join("、") ||
              "等待 catalog"
            }
          />
        </CardContent>
      </Card>
    </div>
  )
}

function SystemCard({
  icon: Icon,
  label,
  value,
  status,
  detail,
}: {
  icon: Icon
  label: string
  value: string
  status: boolean
  detail: string
}) {
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between">
        <div className="grid h-10 w-10 place-items-center rounded-xl bg-white/5 text-cyan-300">
          <Icon className="h-5 w-5" />
        </div>
        <span
          className={cn(
            "h-2 w-2 rounded-full",
            status
              ? "bg-emerald-400 shadow-[0_0_12px_#34d399]"
              : "bg-amber-400",
          )}
        />
      </div>
      <div className="mt-5 text-xs uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <div className="mt-1 font-semibold text-white">{value}</div>
      <div className="mt-1 text-xs text-slate-500">{detail}</div>
    </Card>
  )
}
function Boundary({
  title,
  items,
  good = false,
}: {
  title: string
  items: string[]
  good?: boolean
}) {
  return (
    <div
      className={cn(
        "rounded-xl border p-4",
        good
          ? "border-emerald-400/15 bg-emerald-400/5"
          : "border-white/8 bg-white/3",
      )}
    >
      <div className="mb-3 text-sm font-semibold text-slate-200">{title}</div>
      <div className="space-y-2">
        {items.map((item) => (
          <div
            className="flex items-center gap-2 text-sm text-slate-400"
            key={item}
          >
            {good ? (
              <CheckCircle2 className="h-4 w-4 text-emerald-400" />
            ) : (
              <X className="h-4 w-4 text-slate-600" />
            )}
            {item}
          </div>
        ))}
      </div>
    </div>
  )
}

export function App() {
  const [page, setPage] = useState<Page>("dashboard")
  const [menuOpen, setMenuOpen] = useState(false)
  const selected = navigation.find((item) => item.id === page) ?? navigation[0]
  const PageComponent =
    page === "dashboard"
      ? Dashboard
      : page === "assistant"
        ? AssistantPage
        : page === "query"
          ? QueryWorkbench
          : page === "forecast"
            ? ForecastPage
            : page === "audit"
              ? AuditPage
              : SystemPage

  return (
    <div className="min-h-screen">
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-white/7 bg-[#07111f]/96 backdrop-blur transition-transform lg:translate-x-0",
          menuOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex h-20 items-center gap-3 border-b border-white/7 px-6">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-cyan-300 to-blue-500 text-slate-950 shadow-[0_0_28px_rgba(34,211,238,.2)]">
            <TrainFront className="h-5 w-5" />
          </div>
          <div>
            <div className="font-semibold tracking-tight text-white">
              MetroFlow
            </div>
            <div className="text-[10px] uppercase tracking-[.22em] text-cyan-400">
              Passenger intelligence
            </div>
          </div>
          <button
            type="button"
            className="ml-auto p-2 text-slate-400 lg:hidden"
            onClick={() => setMenuOpen(false)}
            aria-label="关闭导航"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <nav className="flex-1 space-y-1 px-3 py-6">
          {navigation.map((item) => {
            const Icon = item.icon
            const active = item.id === page
            return (
              <button
                type="button"
                key={item.id}
                className={cn(
                  "flex w-full items-center gap-3 rounded-xl px-3.5 py-3 text-left text-sm transition",
                  active
                    ? "bg-cyan-400/10 text-cyan-200"
                    : "text-slate-400 hover:bg-white/4 hover:text-slate-100",
                )}
                onClick={() => {
                  setPage(item.id)
                  setMenuOpen(false)
                }}
              >
                <Icon
                  className={cn(
                    "h-5 w-5",
                    active ? "text-cyan-300" : "text-slate-500",
                  )}
                />
                <span className="font-medium">{item.label}</span>
                {item.note ? (
                  <span className="ml-auto text-[10px] text-slate-600">
                    {item.note}
                  </span>
                ) : active ? (
                  <ChevronRight className="ml-auto h-4 w-4" />
                ) : null}
              </button>
            )
          })}
        </nav>
        <div className="m-4 rounded-2xl border border-cyan-400/10 bg-cyan-400/5 p-4">
          <div className="flex items-center gap-2 text-xs font-semibold text-cyan-200">
            <ShieldCheck className="h-4 w-4" />
            受治理数据链路
          </div>
          <p className="mt-2 text-xs leading-5 text-slate-500">
            只读 · QueryIR 白名单 · 审计可追踪
          </p>
        </div>
      </aside>
      {menuOpen ? (
        <button
          type="button"
          className="fixed inset-0 z-30 bg-black/60 lg:hidden"
          onClick={() => setMenuOpen(false)}
          aria-label="关闭遮罩"
        />
      ) : null}
      <div className="lg:pl-72">
        <header className="sticky top-0 z-20 flex h-20 items-center border-b border-white/7 bg-[#06101d]/78 px-4 backdrop-blur-xl sm:px-6 lg:px-8">
          <button
            type="button"
            className="mr-3 p-2 text-slate-400 lg:hidden"
            onClick={() => setMenuOpen(true)}
            aria-label="打开导航"
          >
            <Menu className="h-5 w-5" />
          </button>
          <div>
            <div className="text-xs text-slate-600">Metro operations /</div>
            <div className="text-sm font-semibold text-slate-200">
              {selected.label}
            </div>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <button
              type="button"
              className="grid h-9 w-9 place-items-center rounded-xl border border-white/8 text-slate-500"
              aria-label="通知（未启用）"
            >
              <Bell className="h-4 w-4" />
            </button>
            <div className="hidden items-center gap-2 rounded-xl border border-white/8 bg-white/3 px-3 py-2 sm:flex">
              <span className="h-2 w-2 rounded-full bg-emerald-400" />
              <span className="text-xs text-slate-400">
                Synthetic environment
              </span>
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-[1600px] p-4 sm:p-6 lg:p-8">
          <PageComponent />
        </main>
      </div>
    </div>
  )
}
