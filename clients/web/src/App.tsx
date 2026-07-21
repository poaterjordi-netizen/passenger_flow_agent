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
  getAssistantCapabilities,
  getAudit,
  getCatalog,
  getGovernanceStatus,
  getHealth,
  runForecast,
  runQuery,
  sendAssistantMessage,
} from "./api"
import type {
  AssistantCapabilities,
  AuditSummary,
  CatalogResponse,
  GovernanceStatus,
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

function compactHash(value: unknown) {
  const text = typeof value === "string" ? value : ""
  return text ? `${text.slice(0, 12)}…` : "—"
}

function ApiError({ error }: { error: unknown }) {
  return (
    <div
      role="alert"
      className="rounded-xl border border-rose-400/20 bg-rose-400/8 p-4 text-sm text-rose-200"
    >
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
  limit = 100,
): QueryRequest {
  const metricDefinition = catalog.metrics.find((item) => item.id === metric)
  return {
    metric,
    metric_version: metricDefinition?.version,
    city: catalog.city,
    dataset_role: metricDefinition?.dataset_role ?? "actual",
    source_version: catalog.source_version,
    time_range: catalog.default_time_range,
    dimensions,
    filters: [],
    limit,
  }
}

function Dashboard() {
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: getCatalog })
  const governance = useQuery({
    queryKey: ["governance-status"],
    queryFn: getGovernanceStatus,
    staleTime: 30_000,
  })
  const health = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 60_000,
  })
  const overview = useQuery({
    queryKey: [
      "dashboard",
      catalog.data?.default_time_range,
      governance.data?.access_scope.access_scope_hash,
    ],
    enabled: Boolean(catalog.data && governance.data),
    queryFn: async () => {
      const source = catalog.data
      const policy = governance.data
      if (!source || !policy)
        throw new Error("Catalog or governance status is not ready")
      const rowLimit = Math.min(100, policy.access_scope.row_limit)
      const registered = new Set(source.metrics.map((item) => item.id))
      const metricIds = (
        ["entries", "exits", "transfers", "net_inflow"] as const
      ).filter((item) => registered.has(item))
      const primaryMetric = registered.has("entries") ? "entries" : metricIds[0]
      if (!primaryMetric) throw new Error("当前授权范围没有可展示的指标")
      const [totals, station, trend] = await Promise.all([
        Promise.all(
          metricIds.map(
            async (item) =>
              [
                item,
                await runQuery(buildQuery(source, item, [], rowLimit)),
              ] as const,
          ),
        ),
        runQuery(buildQuery(source, primaryMetric, ["station"], rowLimit)),
        runQuery(buildQuery(source, primaryMetric, ["time"], rowLimit)),
      ])
      return {
        totals: Object.fromEntries(totals) as Partial<
          Record<keyof typeof metricMeta, QueryResponse>
        >,
        primaryMetric,
        station,
        trend,
      }
    },
  })

  if (catalog.isError) return <ApiError error={catalog.error} />
  const source = catalog.data
  const cards = overview.data
    ? (Object.keys(overview.data.totals) as Array<keyof typeof metricMeta>).map(
        (key) => [key, overview.data?.totals[key]?.rows[0]?.[key]] as const,
      )
    : []
  const stationRows = [...(overview.data?.station.rows ?? [])].sort(
    (a, b) =>
      Number(b[overview.data?.primaryMetric ?? "entries"]) -
      Number(a[overview.data?.primaryMetric ?? "entries"]),
  )
  const trendRows = overview.data?.trend.rows ?? []

  return (
    <div className="space-y-6">
      <PageHeading
        eyebrow="Operation intelligence"
        title="地铁客流运营总览"
        description={`将受约束 QueryIR 的确定性结果汇总为运营视图。当前数据范围：${source?.data_scope ?? "检测中"}；页面只消费后端批准的指标和来源版本。`}
        action={
          <div className="flex items-center gap-2">
            {source?.data_scope === "production-shadow" ? (
              <Badge tone="amber">真实 MySQL · 本地 Shadow</Badge>
            ) : null}
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
                {overview.data?.primaryMetric ?? "指标"} · 半开时间区间
              </p>
            </div>
            <Badge tone="cyan">ECharts</Badge>
          </CardHeader>
          <CardContent>
            {trendRows.length ? (
              <MetricChart
                labels={trendRows.map((row) => displayTime(String(row.time)))}
                values={trendRows.map((row) =>
                  Number(row[overview.data?.primaryMetric ?? "entries"]),
                )}
                kind="line"
                name={overview.data?.primaryMetric ?? "entries"}
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
              const primaryMetric = overview.data?.primaryMetric ?? "entries"
              const max = Number(stationRows[0]?.[primaryMetric] || 1)
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
                      {formatNumber(row[primaryMetric])}
                    </strong>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-white/5">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-cyan-500 to-blue-400"
                      style={{
                        width: `${(Number(row[primaryMetric]) / max) * 100}%`,
                      }}
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
            value={source?.data_scope ?? "—"}
            detail={`${source?.lines.length ?? 0} 条线路 · ${source?.stations.length ?? 0} 个站点`}
          />
          <StatusBlock
            icon={ShieldCheck}
            label="查询治理"
            value="QueryIR allowlist"
            detail={`固定指标 · 行上限 ${governance.data?.access_scope.row_limit ?? "—"} · 审计回读`}
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

const assistantStatusLabels: Record<
  GovernanceStatus["assistant_status"],
  string
> = {
  synthetic_baseline: "合成基线可用",
  disabled_by_runtime_flag: "生产 Assistant 开关未启用",
  blocked_by_promotion_gate: "Promotion 门禁未通过",
  enabled_for_local_shadow: "本地真实 Shadow 已显式授权（非生产晋级）",
  enabled_after_promotion: "已通过 Promotion 并启用",
}

const promotionBlockerLabels: Record<string, string> = {
  gate_status_not_approved: "门禁状态尚未批准",
  owners_incomplete: "业务、数据、安全或工程 Owner 未齐",
  thresholds_incomplete: "验收阈值未全部量化",
  required_artifacts_incomplete: "必需签字或测试产物未齐",
  promotion_gate_configuration_invalid: "门禁配置缺失或无效（已安全关闭）",
}

function GovernanceGateBanner({ status }: { status: GovernanceStatus }) {
  const localLiveShadow = status.assistant_status === "enabled_for_local_shadow"
  return (
    <div
      className={cn(
        "rounded-xl border p-4",
        status.assistant_enabled && !localLiveShadow
          ? "border-emerald-400/15 bg-emerald-400/5"
          : "border-amber-300/20 bg-amber-300/7",
      )}
      aria-live="polite"
    >
      <div className="flex flex-wrap items-center gap-2">
        <ShieldCheck className="h-4 w-4 text-emerald-300" />
        <strong className="text-sm text-slate-100">
          {assistantStatusLabels[status.assistant_status]}
        </strong>
        <Badge
          tone={
            status.assistant_enabled && !localLiveShadow ? "green" : "amber"
          }
        >
          {status.assistant_enabled
            ? localLiveShadow
              ? "可提交本地 Shadow 任务"
              : "可提交任务"
            : "禁止提交任务"}
        </Badge>
        <Badge tone="slate">{status.data_scope}</Badge>
        <Badge
          tone={status.model_policy.evidence_egress_allowed ? "amber" : "green"}
        >
          证据出域：{status.model_policy.data_egress}
        </Badge>
        <Badge
          tone={status.model_policy.intent_egress_allowed ? "amber" : "green"}
        >
          意图出域：{status.model_policy.intent_egress}
        </Badge>
        <Badge
          tone={
            status.model_policy.endpoint_binding_verified ? "green" : "slate"
          }
        >
          端点绑定：
          {status.model_policy.endpoint_binding_verified ? "已核验" : "未核验"}
        </Badge>
      </div>
      <p className="mt-2 text-xs leading-5 text-slate-500">
        身份 {status.identity.subject_id} · {status.identity.identity_adapter} ·
        策略 {status.access_scope.policy_snapshot_id} · 行上限{" "}
        {status.access_scope.row_limit} · 已注册工具{" "}
        {status.tool_registry.tool_count} 个
      </p>
      {localLiveShadow ? (
        <div className="mt-3 text-xs leading-5 text-amber-100/80">
          当前会话会读取真实 MySQL 并调用真实模型，但来源语义和 Promotion
          产物尚未完成；结果仅用于本地 shadow 验证，不可作为运营处置依据。
        </div>
      ) : null}
      {!status.assistant_enabled && status.promotion.blockers.length ? (
        <div className="mt-3 text-xs text-amber-100/75">
          阻断原因：
          {status.promotion.blockers
            .map((item) => promotionBlockerLabels[item] ?? item)
            .join("；")}
        </div>
      ) : null}
    </div>
  )
}

function GovernanceDetails({ status }: { status: GovernanceStatus }) {
  const sourceHashes = [
    [
      "逻辑 registry",
      status.data_source.logical_registry_version,
      status.data_source.logical_registry_hash,
    ],
    [
      "物理 mapping",
      status.data_source.physical_mapping_version,
      status.data_source.physical_mapping_hash,
    ],
  ] as const
  return (
    <Card>
      <CardHeader>
        <div>
          <h2 className="font-semibold text-white">实际生效的治理状态</h2>
          <p className="mt-1 text-xs text-slate-500">
            来自后端运行时，不是前端写死的说明
          </p>
        </div>
        <Badge tone={status.assistant_enabled ? "green" : "amber"}>
          {assistantStatusLabels[status.assistant_status]}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-5">
        <GovernanceGateBanner status={status} />
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MiniStat
            label="授权城市"
            value={status.access_scope.allowed_cities.join("、")}
          />
          <MiniStat
            label="授权数据角色"
            value={status.access_scope.allowed_dataset_roles.join("、")}
          />
          <MiniStat
            label="最长时间范围"
            value={`${status.access_scope.max_time_range_hours} 小时`}
          />
          <MiniStat
            label="导出策略"
            value={status.access_scope.export_policy}
          />
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="rounded-xl border border-white/7 bg-white/3 p-4">
            <h3 className="text-sm font-semibold text-slate-200">
              数据源与映射
            </h3>
            <div className="mt-3 space-y-2 text-xs text-slate-500">
              <div>城市：{status.data_source.city ?? "—"}</div>
              <div>源版本：{status.data_source.source_version ?? "—"}</div>
              <div>注册状态：{status.data_source.registration_status}</div>
              <div>
                注册质量：{status.data_source.registration_quality_status} ·
                运行质量：{status.data_source.runtime_quality_status}
              </div>
              <div>
                新鲜度：{status.data_source.freshness_status} · 评估时间：
                {status.data_source.quality_gate_evaluated_at
                  ? new Date(
                      status.data_source.quality_gate_evaluated_at,
                    ).toLocaleString("zh-CN")
                  : "未评估"}
              </div>
              {sourceHashes.map(([label, version, hash]) => (
                <div key={label} className="font-mono">
                  {label}：{version ?? "—"} · {compactHash(hash)}
                </div>
              ))}
              <div className="font-mono">
                access scope：
                {compactHash(status.access_scope.access_scope_hash)}
              </div>
            </div>
          </div>
          <div className="rounded-xl border border-white/7 bg-white/3 p-4">
            <h3 className="text-sm font-semibold text-slate-200">
              Promotion 门禁
            </h3>
            <div className="mt-3 space-y-2 text-xs text-slate-500">
              <div>Gate：{status.promotion.gate_id}</div>
              <div>配置状态：{status.promotion.configured_status}</div>
              <div>
                环境开关：
                {status.promotion.runtime_flag_requested ? "已请求" : "未请求"}{" "}
                · 当前范围
                {status.promotion.enforced ? "强制执行" : "不强制（合成数据）"}
              </div>
              <div>
                本地真实 Shadow 确认：
                {status.promotion.local_live_shadow_acknowledged
                  ? "已显式确认（不等于生产晋级）"
                  : "未确认"}
              </div>
              {status.promotion.blockers.map((item) => (
                <div key={item} className="text-amber-200/75">
                  • {promotionBlockerLabels[item] ?? item}
                </div>
              ))}
              {status.promotion.missing_owner_roles.length ? (
                <div>
                  缺少 Owner：{status.promotion.missing_owner_roles.join("、")}
                </div>
              ) : null}
              {status.promotion.missing_thresholds.length ? (
                <div>
                  缺少阈值：{status.promotion.missing_thresholds.join("、")}
                </div>
              ) : null}
              {status.promotion.pending_artifacts.length ? (
                <div>
                  待批准产物：{status.promotion.pending_artifacts.join("、")}
                </div>
              ) : null}
            </div>
          </div>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="rounded-xl border border-white/7 bg-white/3 p-4">
            <h3 className="text-sm font-semibold text-slate-200">身份边界</h3>
            <div className="mt-3 space-y-2 text-xs text-slate-500">
              <div>Adapter：{status.identity.identity_adapter}</div>
              <div>Subject：{status.identity.subject_id}</div>
              <div>部门 / Tenant：{status.identity.tenant_or_department}</div>
              <div>角色：{status.identity.roles.join("、")}</div>
              <div className="text-amber-200/75">
                {status.identity.multi_user_isolation
                  ? "已具备多用户强隔离"
                  : "当前是单主体静态令牌适配器，不声称多用户 IdP 隔离"}
              </div>
            </div>
          </div>
          <div className="rounded-xl border border-white/7 bg-white/3 p-4">
            <h3 className="text-sm font-semibold text-slate-200">
              模型端点策略
            </h3>
            <div className="mt-3 space-y-2 text-xs text-slate-500">
              <div>
                Provider / Model：{status.model_policy.active_provider} /{" "}
                {status.model_policy.active_model ?? "—"}
              </div>
              <div>证据策略：{status.model_policy.data_egress}</div>
              <div>意图策略：{status.model_policy.intent_egress}</div>
              <div>
                端点绑定：
                {status.model_policy.endpoint_binding_verified
                  ? "provider + model + target hash 已精确匹配"
                  : "未精确匹配，受保护数据不可出域"}
              </div>
              <div className="break-all font-mono">
                target：{status.model_policy.endpoint_target_hash || "—"}
              </div>
              <div>策略：{status.model_policy.endpoint_policy_id}</div>
            </div>
          </div>
        </div>
        <details className="rounded-xl border border-white/7 bg-white/3 p-4">
          <summary className="cursor-pointer text-sm font-semibold text-slate-200">
            查看实际注册工具（{status.tool_registry.tool_count}）
          </summary>
          <div className="mt-3 flex flex-wrap gap-2">
            {status.tool_registry.registered_tools.map((tool) => (
              <Badge key={tool} tone="slate">
                {tool}
              </Badge>
            ))}
          </div>
        </details>
      </CardContent>
    </Card>
  )
}

function ResultsView({ result }: { result: QueryResponse }) {
  const provenance = result.provenance ?? {}
  const complete =
    provenance.complete !== false && provenance.truncated !== true
  const runtimeQuality = String(provenance.runtime_quality_status ?? "unknown")
  const runtimeQualityPassed = runtimeQuality === "pass"
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
        <Badge tone={complete ? "green" : "amber"}>
          {complete ? "结果完整" : "结果被截断"}
        </Badge>
        <span className="ml-auto max-w-full truncate font-mono text-[11px] text-slate-600">
          {result.audit.audit_id}
        </span>
      </div>
      <div
        className={cn(
          "grid gap-3 rounded-xl border p-3 text-xs sm:grid-cols-2 xl:grid-cols-4",
          complete
            ? "border-emerald-400/12 bg-emerald-400/5"
            : "border-amber-300/20 bg-amber-300/7",
        )}
      >
        <MiniStat
          label="返回 / 匹配"
          value={`${String(provenance.returned_row_count ?? result.row_count)} / ${String(provenance.matched_row_count ?? "未知")}`}
        />
        <MiniStat
          label="数据源版本"
          value={String(provenance.source_version ?? "—")}
        />
        <MiniStat
          label="策略快照"
          value={String(provenance.policy_snapshot_id ?? "—")}
        />
        <MiniStat
          label="Query fingerprint"
          value={compactHash(provenance.query_fingerprint)}
        />
        <MiniStat
          label="注册 / 运行质量"
          value={`${String(provenance.registration_quality_status ?? "unknown")} / ${runtimeQuality}`}
        />
        <MiniStat
          label="源行 / 缺失 / 非法"
          value={`${String(provenance.source_row_count ?? "—")} / ${String(provenance.missing_row_count ?? "—")} / ${String(provenance.invalid_row_count ?? "—")}`}
        />
        <MiniStat
          label="查询模板"
          value={compactHash(provenance.query_template_hash)}
        />
        <MiniStat
          label="连接与事务"
          value={
            provenance.transaction_mode
              ? `${provenance.tls_identity_verified ? "TLS 身份已核验" : "TLS 未确认"} · ${String(provenance.tls_identity_mode ?? "unknown")} · ${String(provenance.transaction_mode)}`
              : "合成基线 · 不适用"
          }
        />
        {!runtimeQualityPassed && result.data_scope !== "synthetic" ? (
          <p className="sm:col-span-2 xl:col-span-4 text-amber-100/80">
            注册通过不代表本次数据通过；运行质量为 {runtimeQuality}
            ，本结果不得用于运营决策。
          </p>
        ) : null}
        {!complete ? (
          <p className="sm:col-span-2 xl:col-span-4 text-amber-100/80">
            当前只返回授权行上限内的部分结果，不能把本表表述为全局总量、完整排名或完整分布。
          </p>
        ) : null}
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
  "列出数据库中的所有地铁站",
  "列出数据库中的所有地铁线路",
  "有哪些指标",
  "数据覆盖哪些日期",
  "数据库基本情况",
  "查询各站进站客流并排序",
  "奥体中心有 4 万人演唱会，预测客流并给出建议",
  "我要从北京交通大学到北京工业大学，给出合理的出行规划",
  "你能做什么？",
  "什么是地铁断面客流？",
]

function assistantExternalLinks(
  tools: NonNullable<RunRecord["tool_results"]>,
): Array<{ label: string; url: string }> {
  const links = tools.flatMap((tool) => {
    const summary = tool.summary ?? {}
    const candidates = [summary.navigation_links, summary.source_refs]
    return candidates.flatMap((candidate) => {
      if (!Array.isArray(candidate)) return []
      return candidate.flatMap((item) => {
        if (!item || typeof item !== "object") return []
        const record = item as Record<string, unknown>
        const label = record.label
        const url = record.url
        return typeof label === "string" &&
          typeof url === "string" &&
          url.startsWith("https://")
          ? [{ label, url }]
          : []
      })
    })
  })
  return Array.from(new Map(links.map((link) => [link.url, link])).values())
}

function AssistantRunView({ run }: { run: RunRecord }) {
  const tools = run.tool_results ?? []
  const externalLinks = assistantExternalLinks(tools)
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
  const tableEntryLimit =
    run.operation_ir?.answer_policy === "deterministic_table" ||
    tools.some(
      (tool) =>
        tool.tool === "list_observed_entities" &&
        tool.complete !== false &&
        tool.truncated !== true,
    )
      ? 1000
      : 20
  const tableEntries = tools
    .flatMap((tool) =>
      (tool.rows ?? []).map((row) => ({
        key: `${tool.step_id}-${JSON.stringify(row)}`,
        row,
      })),
    )
    .slice(0, tableEntryLimit)
  const tableRows = tableEntries.map((entry) => entry.row)
  const columns = tableRows[0] ? Object.keys(tableRows[0]).slice(0, 6) : []
  const numericColumn = columns.find((column) =>
    tableRows.some((row) => typeof row[column] === "number"),
  )
  const labelColumn = columns.find((column) => column !== numericColumn)
  const verificationPassed = run.verification?.valid === true
  const verificationFailed = run.verification?.valid === false
  const egressCalls = run.model_egress ?? []
  const approvedEgressCalls = egressCalls.filter(
    (call) => call.decision === "approved",
  ).length
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={run.status === "completed" ? "green" : "amber"}>
          {run.status}
        </Badge>
        <Badge tone="cyan">{run.intent?.task_type ?? "understand"}</Badge>
        <Badge tone="cyan">
          operation: {run.operation_ir?.operation ?? "未编译"}
        </Badge>
        <Badge tone="slate">
          capability: {run.capability_match?.capability_id ?? "未匹配"}
        </Badge>
        <Badge
          tone={
            run.operation_ir?.answer_policy?.startsWith("llm_")
              ? "cyan"
              : "green"
          }
        >
          {run.operation_ir?.answer_policy ?? "无回答策略"}
        </Badge>
        {run.failure_category ? (
          <Badge tone="amber">failure: {run.failure_category}</Badge>
        ) : null}
        <Badge tone="slate">{run.provider}</Badge>
        <Badge tone="slate">intent: {run.intent_route}</Badge>
        <Badge tone="slate">plan: {run.planner_route}</Badge>
        <span className="ml-auto font-mono text-[11px] text-slate-600">
          {run.run_id}
        </span>
      </div>
      <div className="grid gap-3 rounded-xl border border-white/8 bg-white/3 p-4 sm:grid-cols-2 xl:grid-cols-6">
        <MiniStat label="Owner" value={run.owner_subject_id} />
        <MiniStat label="策略快照" value={run.policy_snapshot_id} />
        <MiniStat
          label="模型出域调用"
          value={
            egressCalls.length
              ? `${egressCalls.length} 次 · ${approvedEgressCalls} 次批准`
              : "无模型调用"
          }
        />
        <MiniStat
          label="授权范围 hash"
          value={compactHash(run.access_scope_hash)}
        />
        <MiniStat
          label="覆盖策略"
          value={run.capability_match?.completeness_policy ?? "未匹配"}
        />
        <MiniStat
          label="能力版本"
          value={run.capability_match?.registry_version ?? "—"}
        />
      </div>
      {egressCalls.length ? (
        <details className="rounded-xl border border-violet-400/12 bg-violet-400/5 p-4">
          <summary className="cursor-pointer text-sm font-semibold text-violet-200">
            调用级模型出域审计（{egressCalls.length}）
          </summary>
          <div className="mt-3 space-y-3">
            {egressCalls.map((call) => (
              <div
                key={call.call_id}
                className="rounded-lg border border-white/7 bg-black/10 p-3 text-xs text-slate-500"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Badge
                    tone={call.decision === "approved" ? "green" : "amber"}
                  >
                    {call.purpose} · {call.decision} · {call.status}
                  </Badge>
                  <span>{call.provider}</span>
                  <span>{call.model ?? "—"}</span>
                  <span>
                    端点绑定：
                    {call.endpoint_binding_verified ? "已核验" : "未核验"}
                  </span>
                </div>
                <div className="mt-2 break-all font-mono">
                  payload：{call.exact_payload_hash} · target：
                  {call.endpoint_target_hash || "—"}
                </div>
                <div className="mt-1">
                  出域字段：{call.outbound_field_paths?.join("、") || "无"}
                </div>
                <div className="mt-1">
                  {new Date(call.started_at).toLocaleString("zh-CN")} ·{" "}
                  {call.completed_at
                    ? new Date(call.completed_at).toLocaleString("zh-CN")
                    : "未完成"}
                </div>
              </div>
            ))}
          </div>
        </details>
      ) : null}
      <div className="grid gap-3 rounded-xl border border-violet-400/12 bg-violet-400/5 p-4 sm:grid-cols-2 xl:grid-cols-3">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500">
            本次 Provider
          </div>
          <div className="mt-1 break-all text-sm font-medium text-violet-200">
            {run.model_runtime?.provider ?? run.provider}
            {run.model_runtime?.model ? ` · ${run.model_runtime.model}` : ""}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500">
            运行模式
          </div>
          <div className="mt-1 text-sm text-slate-200">
            {run.model_runtime?.mode === "local_governed_model"
              ? "Hermes 本地受治理模型"
              : run.model_runtime?.mode === "openai_compatible"
                ? "OpenAI-compatible"
                : "离线确定性"}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500">
            调用职责
          </div>
          <div className="mt-1 text-sm text-slate-200">
            {run.model_runtime?.provider_calls == null
              ? "Provider 阶段未报告"
              : `${run.model_runtime.provider_calls} 个 provider 阶段`}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500">
            真实模型
          </div>
          <div className="mt-1 text-sm text-slate-200">
            {run.model_runtime?.real_model_configured
              ? `${run.model_runtime.model_calls} 次实际 API 调用`
              : "未配置真实模型"}
          </div>
          <div className="mt-1 text-[11px] text-slate-500">
            状态：{run.model_runtime?.invocation_status ?? "not_applicable"}
          </div>
          <div className="mt-1 text-[11px] text-slate-500">
            执行角色：{run.model_runtime?.execution_role ?? "未报告"}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500">
            用量 / 时延
          </div>
          <div className="mt-1 text-sm text-slate-200">
            {run.model_runtime?.total_tokens != null
              ? `${formatNumber(run.model_runtime.total_tokens)} tokens`
              : "未报告 token"}
            {run.model_runtime?.elapsed_seconds != null
              ? ` · ${run.model_runtime.elapsed_seconds}s`
              : ""}
          </div>
          <div className="mt-1 text-[11px] text-slate-500">
            usage：{run.model_runtime?.usage_reporting ?? "not_applicable"}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500">
            Token 明细
          </div>
          <div className="mt-1 text-sm leading-6 text-slate-200">
            输入 {run.model_runtime?.input_tokens ?? "—"} · 输出{" "}
            {run.model_runtime?.output_tokens ?? "—"} · 推理{" "}
            {run.model_runtime?.reasoning_tokens ?? "—"}
          </div>
        </div>
      </div>
      <div
        className={cn(
          "rounded-xl border p-4",
          verificationPassed
            ? "border-emerald-400/12 bg-emerald-400/5"
            : verificationFailed
              ? "border-rose-400/20 bg-rose-400/8"
              : "border-white/8 bg-white/3",
        )}
      >
        <div className="flex flex-wrap items-center gap-2">
          <ShieldCheck
            className={cn(
              "h-4 w-4",
              verificationPassed
                ? "text-emerald-300"
                : verificationFailed
                  ? "text-rose-300"
                  : "text-slate-400",
            )}
          />
          <span className="text-sm font-semibold text-slate-200">
            {verificationPassed
              ? "确定性 verifier 已通过"
              : verificationFailed
                ? "核验失败：禁止采纳"
                : "等待 verifier"}
          </span>
          <Badge
            tone={
              verificationPassed
                ? "green"
                : verificationFailed
                  ? "amber"
                  : "slate"
            }
          >
            {run.verification?.supported_evidence_refs?.length ?? 0} 条证据引用
          </Badge>
        </div>
        {run.verification?.warnings?.length ? (
          <ul className="mt-2 space-y-1 text-xs text-amber-200/75">
            {run.verification.warnings.map((warning) => (
              <li key={warning}>• {warning}</li>
            ))}
          </ul>
        ) : null}
        {run.verification?.errors?.length ? (
          <ul
            className="mt-2 space-y-1 text-xs text-rose-200"
            aria-label="核验错误"
          >
            {run.verification.errors.map((error) => (
              <li key={error}>• {error}</li>
            ))}
          </ul>
        ) : null}
      </div>
      <div
        className={cn(
          "rounded-xl border p-4",
          verificationPassed
            ? "border-cyan-400/12 bg-cyan-400/5"
            : "border-rose-400/20 bg-rose-400/8",
        )}
      >
        <div
          className={cn(
            "mb-2 text-xs font-semibold uppercase tracking-wider",
            verificationPassed ? "text-cyan-300" : "text-rose-200",
          )}
        >
          {verificationPassed ? "证据化回答" : "未核验回答（禁止采纳）"}
        </div>
        {run.operation_ir?.answer_policy === "llm_general" ? (
          <div className="mb-3 rounded-lg border border-violet-400/15 bg-violet-400/7 px-3 py-2 text-xs text-violet-100">
            GPT 通用知识回答 · 未读取 metroflow
            数据库业务行；实时信息需另接外部数据源
          </div>
        ) : null}
        <p className="text-sm leading-7 text-slate-200">
          {run.response?.answer ?? "尚未生成回答"}
        </p>
        {externalLinks.length ? (
          <div className="mt-4 border-t border-white/6 pt-3">
            <div className="mb-2 text-xs font-semibold text-cyan-200">
              实时路线与核验来源
            </div>
            <div className="flex flex-wrap gap-2">
              {externalLinks.map((link) => (
                <a
                  key={link.url}
                  href={link.url}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-lg border border-cyan-400/20 bg-cyan-400/8 px-3 py-2 text-xs text-cyan-100 transition hover:border-cyan-300/40 hover:bg-cyan-400/14"
                >
                  {link.label}
                </a>
              ))}
            </div>
          </div>
        ) : null}
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
                  <Badge
                    tone={
                      tool.complete !== false && tool.truncated !== true
                        ? "green"
                        : "amber"
                    }
                  >
                    {tool.complete !== false && tool.truncated !== true
                      ? "完整"
                      : "不完整"}
                  </Badge>
                </div>
                <p className="mt-2 text-xs leading-5 text-slate-500">
                  {String(
                    tool.summary?.claim ?? `${tool.rows?.length ?? 0} rows`,
                  )}
                </p>
                <div className="mt-2 grid gap-1 font-mono text-[10px] leading-4 text-slate-600">
                  <span>
                    returned/matched: {tool.returned_row_count ?? 0}/
                    {tool.matched_count_unknown
                      ? "unknown"
                      : (tool.matched_row_count ?? "—")}
                  </span>
                  <span>query: {compactHash(tool.query_fingerprint)}</span>
                  <span>result: {compactHash(tool.result_hash)}</span>
                  <span>
                    coverage: {tool.coverage?.coverage_type ?? "unknown"} ·{" "}
                    {tool.coverage?.scope_label ?? "unknown"}
                  </span>
                  <span>
                    master: {tool.coverage?.authoritative_master ? "yes" : "no"}{" "}
                    · role: {tool.coverage?.dataset_role ?? "—"} · city:{" "}
                    {tool.coverage?.city ?? "—"}
                  </span>
                  {tool.coverage?.time_range &&
                  Object.keys(tool.coverage.time_range).length ? (
                    <span>
                      time: {tool.coverage.time_range.start ?? "—"} →{" "}
                      {tool.coverage.time_range.end ?? "—"}
                    </span>
                  ) : null}
                  {tool.block_reason ? (
                    <span className="text-amber-200/75">
                      blocked: {tool.block_reason}
                    </span>
                  ) : null}
                </div>
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
              结果数据表 · {tableRows.length} 行
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
                  <Badge
                    tone={
                      item.complete !== false && item.truncated !== true
                        ? "green"
                        : "amber"
                    }
                  >
                    {item.complete !== false && item.truncated !== true
                      ? "完整"
                      : "不完整"}
                  </Badge>
                </div>
                <p className="mt-2 text-xs leading-5 text-slate-400">
                  {item.claim}
                </p>
                <div className="mt-2 space-y-1 font-mono text-[10px] text-slate-600">
                  <div>
                    returned/matched: {item.returned_row_count ?? 0}/
                    {item.matched_count_unknown
                      ? "unknown"
                      : (item.matched_row_count ?? "—")}
                  </div>
                  <div>query: {compactHash(item.query_fingerprint)}</div>
                  <div>
                    coverage: {item.coverage?.coverage_type ?? "unknown"} ·{" "}
                    {item.coverage?.scope_label ?? "unknown"} · master{" "}
                    {item.coverage?.authoritative_master ? "yes" : "no"}
                  </div>
                  {item.source_evidence_ids?.length ? (
                    <div>sources: {item.source_evidence_ids.join(", ")}</div>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      {run.response?.recommendations?.length && verificationPassed ? (
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
      ) : run.response?.recommendations?.length && verificationFailed ? (
        <div className="rounded-xl border border-rose-400/20 bg-rose-400/8 p-4 text-sm text-rose-200">
          未核验处置建议已隐藏，禁止执行或采纳。
        </div>
      ) : null}
    </div>
  )
}

function AssistantCapabilityOverview({
  capabilities,
}: {
  capabilities: AssistantCapabilities
}) {
  return (
    <div className="space-y-5">
      <Card>
        <CardHeader>
          <div>
            <h2 className="font-semibold text-white">大模型运行结构</h2>
            <p className="mt-1 text-xs text-slate-500">
              当前 Provider：{capabilities.active_runtime.provider}
              {capabilities.active_runtime.model
                ? ` · ${capabilities.active_runtime.model}`
                : " · 不发起外部模型请求"}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge tone="slate">{capabilities.data_scope} data</Badge>
            <Badge tone="cyan">
              capability registry {capabilities.capability_registry_version}
            </Badge>
            <Badge tone="slate">
              {capabilities.operation_capabilities?.length ?? 0} 项 Operation
              能力
            </Badge>
            <Badge
              tone={
                capabilities.active_runtime.real_model_configured
                  ? "green"
                  : "cyan"
              }
            >
              {capabilities.active_runtime.real_model_configured
                ? "真实模型已配置，尚未代表本次已调用"
                : "本次不产生模型费用"}
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid gap-2 md:grid-cols-4 xl:grid-cols-7">
            {capabilities.architecture.map((stage, index) => (
              <div
                key={stage.id}
                className="rounded-xl border border-white/7 bg-white/3 p-3"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[10px] text-slate-600">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <Badge
                    tone={
                      stage.owner === "llm"
                        ? "cyan"
                        : stage.owner === "human"
                          ? "amber"
                          : "slate"
                    }
                  >
                    {stage.owner === "llm"
                      ? "大模型"
                      : stage.owner === "human"
                        ? "人工"
                        : "确定性"}
                  </Badge>
                </div>
                <div className="mt-3 text-sm font-semibold text-slate-200">
                  {stage.label}
                </div>
                <p className="mt-1 text-[11px] leading-5 text-slate-500">
                  {stage.detail}
                </p>
              </div>
            ))}
          </div>
          <div className="mt-4 grid gap-3 lg:grid-cols-3">
            <div className="rounded-xl border border-cyan-400/10 bg-cyan-400/4 p-4">
              <div className="text-xs font-semibold text-cyan-300">
                大模型负责
              </div>
              <ul className="mt-2 space-y-1 text-xs leading-5 text-slate-400">
                {capabilities.model_responsibilities.map((item) => (
                  <li key={item}>• {item}</li>
                ))}
              </ul>
            </div>
            <div className="rounded-xl border border-emerald-400/10 bg-emerald-400/4 p-4">
              <div className="text-xs font-semibold text-emerald-300">
                确定性保护
              </div>
              <ul className="mt-2 space-y-1 text-xs leading-5 text-slate-400">
                {capabilities.deterministic_controls.map((item) => (
                  <li key={item}>• {item}</li>
                ))}
              </ul>
            </div>
            <div className="rounded-xl border border-amber-300/10 bg-amber-300/4 p-4">
              <div className="text-xs font-semibold text-amber-200">
                大模型不保存客流事实
              </div>
              <ul className="mt-2 space-y-1 text-xs leading-5 text-slate-400">
                {capabilities.prohibited_model_actions.map((item) => (
                  <li key={item}>• {item}</li>
                ))}
              </ul>
            </div>
          </div>
          <details className="mt-4 rounded-xl border border-white/7 bg-white/3 p-4">
            <summary className="cursor-pointer text-sm font-semibold text-slate-200">
              查看 OperationIR 能力注册表（
              {capabilities.operation_capabilities?.length ?? 0}）
            </summary>
            <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
              {(capabilities.operation_capabilities ?? []).map((capability) => (
                <div
                  key={String(capability.id)}
                  className="rounded-lg border border-white/7 bg-black/10 p-3"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <strong className="text-xs text-cyan-200">
                      {String(capability.id)}
                    </strong>
                    <Badge
                      tone={
                        Array.isArray(capability.runtime_tools_unavailable) &&
                        capability.runtime_tools_unavailable.length
                          ? "amber"
                          : "green"
                      }
                    >
                      {String(capability.answer_policy ?? "unknown")}
                    </Badge>
                  </div>
                  <div className="mt-2 text-[11px] leading-5 text-slate-500">
                    Operation：
                    {Array.isArray(capability.operations)
                      ? capability.operations.join("、")
                      : "—"}
                    <br />
                    可用工具：
                    {Array.isArray(capability.runtime_tools_available)
                      ? capability.runtime_tools_available.join("、") || "无"
                      : "—"}
                    <br />
                    完整性：{String(capability.completeness_policy ?? "—")}
                  </div>
                </div>
              ))}
            </div>
          </details>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <div>
            <h2 className="font-semibold text-white">验证进展与生产边界</h2>
            <p className="mt-1 text-xs text-slate-500">
              展示已经真实验证的范围，同时保留尚未完成项。
            </p>
          </div>
          <Badge tone="cyan">v0.4 governed prototype</Badge>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {capabilities.validated_milestones.map((milestone) => (
              <div
                key={milestone.id}
                className="rounded-xl border border-white/7 bg-white/3 p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="text-sm font-semibold text-slate-200">
                    {milestone.label}
                  </div>
                  <Badge
                    tone={
                      milestone.status === "verified"
                        ? "green"
                        : milestone.status === "partial"
                          ? "amber"
                          : "slate"
                    }
                  >
                    {milestone.status === "verified"
                      ? "已验证"
                      : milestone.status === "partial"
                        ? "历史记录"
                        : "未完成"}
                  </Badge>
                </div>
                <div className="mt-3 font-mono text-2xl font-semibold text-cyan-300">
                  {milestone.evidence}
                </div>
                <p className="mt-2 text-xs leading-5 text-slate-500">
                  {milestone.scope}
                </p>
              </div>
            ))}
          </div>
          <div className="mt-4 rounded-xl border border-amber-300/10 bg-amber-300/4 p-4">
            <div className="text-xs font-semibold text-amber-200">
              尚未生产化
            </div>
            <div className="mt-2 grid gap-1 text-xs leading-5 text-slate-500 md:grid-cols-2">
              {capabilities.production_gaps.map((item) => (
                <div key={item}>• {item}</div>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function AssistantPage() {
  const governance = useQuery({
    queryKey: ["governance-status"],
    queryFn: getGovernanceStatus,
    staleTime: 30_000,
  })
  const capabilities = useQuery({
    queryKey: ["assistant-capabilities"],
    queryFn: getAssistantCapabilities,
    staleTime: 30_000,
  })
  const session = useQuery({
    queryKey: ["assistant-session"],
    queryFn: createAssistantSession,
    enabled: governance.data?.assistant_enabled === true,
    staleTime: Number.POSITIVE_INFINITY,
  })
  const assistantReady = governance.data?.assistant_enabled === true
  const [message, setMessage] = useState(assistantExamples[0])
  const [runs, setRuns] = useState<RunRecord[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const mutation = useMutation({
    mutationFn: async (value: string) => {
      if (!session.data) throw new Error("智能分析会话尚未就绪")
      return sendAssistantMessage(session.data.session_id, value)
    },
    onSuccess: (run) => {
      setRuns((current) => [...current, run])
      setSelectedRunId(run.run_id)
    },
  })
  const selectedRun =
    runs.find((run) => run.run_id === selectedRunId) ?? mutation.data ?? null
  function submit(event: FormEvent) {
    event.preventDefault()
    if (message.trim()) mutation.mutate(message.trim())
  }
  return (
    <div className="space-y-6">
      <PageHeading
        eyebrow="Governed agent workflow"
        title="地铁客流智能分析"
        description="问题先编译为 OperationIR 并匹配版本化能力；数据问题走真实工具，开放问题进入一次 GPT 通用回答，真正缺少起点、终点或目标时才追问。"
        action={
          governance.isPending || capabilities.isPending ? (
            <Badge tone="slate">正在检测运行时</Badge>
          ) : governance.isError || capabilities.isError ? (
            <Badge tone="amber">运行时状态未知</Badge>
          ) : governance.data && !governance.data.assistant_enabled ? (
            <Badge tone="amber">
              {assistantStatusLabels[governance.data.assistant_status]}
            </Badge>
          ) : (
            <Badge
              tone={
                capabilities.data?.active_runtime.real_model_configured
                  ? "green"
                  : "cyan"
              }
            >
              {capabilities.data?.active_runtime.real_model_configured
                ? `已配置：${capabilities.data.active_runtime.model}（尚未调用）`
                : "当前运行：离线确定性基线"}
            </Badge>
          )
        }
      />
      {governance.isError ? <ApiError error={governance.error} /> : null}
      {governance.data ? (
        <GovernanceGateBanner status={governance.data} />
      ) : null}
      {capabilities.isError ? (
        <div className="space-y-2">
          <ApiError error={capabilities.error} />
          <button
            type="button"
            className="text-xs text-cyan-300 hover:text-cyan-200"
            onClick={() => capabilities.refetch()}
          >
            重新读取运行能力
          </button>
        </div>
      ) : capabilities.data ? (
        <AssistantCapabilityOverview capabilities={capabilities.data} />
      ) : (
        <div className="h-44 animate-pulse rounded-2xl border border-white/6 bg-white/3" />
      )}
      <div className="grid gap-5 xl:grid-cols-[380px_1fr]">
        <Card className="h-fit">
          <CardHeader>
            <div>
              <h2 className="font-semibold text-white">业务问题</h2>
              <p className="mt-1 text-xs text-slate-500">
                运行时 Provider 由后端环境选择，界面不会把 shadow
                验证冒充生产部署
              </p>
            </div>
            <Sparkles className="h-5 w-5 text-cyan-300" />
          </CardHeader>
          <CardContent>
            {runs.length ? (
              <div className="mb-4 max-h-72 space-y-3 overflow-auto rounded-xl border border-white/7 bg-black/10 p-3">
                {runs.map((run) => (
                  <button
                    type="button"
                    key={run.run_id}
                    aria-pressed={run.run_id === selectedRun?.run_id}
                    onClick={() => setSelectedRunId(run.run_id)}
                    className={cn(
                      "block w-full space-y-1 rounded-lg border p-1 text-left text-xs",
                      run.run_id === selectedRun?.run_id
                        ? "border-cyan-400/30 bg-cyan-400/5"
                        : "border-transparent hover:border-white/10",
                    )}
                  >
                    <div className="rounded-lg bg-cyan-400/7 p-2 text-cyan-100">
                      用户：{run.original_question}
                    </div>
                    <div className="rounded-lg bg-white/4 p-2 leading-5 text-slate-400">
                      助手：
                      {run.verification?.valid === false
                        ? `未核验（禁止采纳）· ${run.response?.answer ?? run.status}`
                        : (run.response?.answer ?? run.status)}
                    </div>
                  </button>
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
                  disabled={!assistantReady || mutation.isPending}
                />
              </Field>
              <div className="flex justify-between text-[11px] text-slate-600">
                <span aria-live="polite">
                  {mutation.isPending
                    ? "状态机执行中，请勿重复提交"
                    : assistantReady
                      ? "最多 4000 个字符"
                      : "治理门禁未允许创建会话"}
                </span>
                <span>{message.length}/4000</span>
              </div>
              {governance.data?.data_scope === "production-shadow" ? (
                <div className="rounded-lg border border-amber-300/15 bg-amber-300/5 px-3 py-2 text-[11px] leading-5 text-amber-100/80">
                  大型活动问题会调用真实客流上下文并检查预测准入；在场馆映射、相似活动实绩、模型回测和
                  SOP 未核验前，系统不会生成伪预测值或运营处置方案。
                </div>
              ) : null}
              <div className="flex flex-wrap gap-2">
                {assistantExamples.map((example) => (
                  <button
                    type="button"
                    className="rounded-lg border border-white/8 px-2.5 py-1.5 text-left text-[11px] text-slate-500 hover:text-cyan-300"
                    key={example}
                    onClick={() => setMessage(example)}
                    disabled={!assistantReady}
                  >
                    {example}
                  </button>
                ))}
              </div>
              <Button
                className="w-full"
                disabled={
                  !assistantReady ||
                  !session.data ||
                  mutation.isPending ||
                  !message.trim()
                }
              >
                {mutation.isPending ? (
                  <RefreshCw className="h-4 w-4 animate-spin" />
                ) : (
                  <Sparkles className="h-4 w-4" />
                )}
                {mutation.isPending
                  ? "正在执行状态机"
                  : assistantReady
                    ? "开始智能分析"
                    : "治理门禁已阻断"}
              </Button>
            </form>
          </CardContent>
        </Card>
        <Card className="min-w-0">
          <CardHeader>
            <div>
              <h2 className="font-semibold text-white">回答、证据与轨迹</h2>
              <p className="mt-1 text-xs text-slate-500">
                {session.data?.session_id ??
                  (assistantReady ? "正在创建会话" : "会话未创建")}
              </p>
            </div>
            {selectedRun?.verification?.valid === true ? (
              <Badge tone="green">Evidence verified</Badge>
            ) : selectedRun?.verification?.valid === false ? (
              <Badge tone="amber">核验失败 · 禁止采纳</Badge>
            ) : (
              <Badge tone="slate">等待任务</Badge>
            )}
          </CardHeader>
          <CardContent>
            {!assistantReady && governance.data ? (
              <EmptyState
                text={`当前不可提交智能分析：${assistantStatusLabels[governance.data.assistant_status]}`}
              />
            ) : session.isError ? (
              <ApiError error={session.error} />
            ) : mutation.isError ? (
              <div className="space-y-3" aria-live="assertive">
                <ApiError error={mutation.error} />
                <p className="text-xs text-slate-500">
                  本次失败不会自动切换 Provider、绕过 verifier
                  或重复调用模型；可确认问题后重新提交。
                </p>
              </div>
            ) : selectedRun ? (
              <AssistantRunView run={selectedRun} />
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
  const governance = useQuery({
    queryKey: ["governance-status"],
    queryFn: getGovernanceStatus,
    staleTime: 30_000,
  })
  const [metric, setMetric] = useState("entries")
  const [dimension, setDimension] = useState<
    QueryRequest["dimensions"][number] | "none"
  >("station")
  const [line, setLine] = useState("all")
  const [station, setStation] = useState("all")
  const [direction, setDirection] = useState("all")
  const mutation = useMutation({ mutationFn: runQuery })
  const selectedMetric = catalog.data?.metrics.some(
    (item) => item.id === metric,
  )
    ? metric
    : (catalog.data?.metrics[0]?.id ?? metric)

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!catalog.data || !governance.data) return
    const filters: QueryRequest["filters"] = []
    if (line !== "all")
      filters.push({ field: "line_id", operator: "eq", value: line })
    if (station !== "all")
      filters.push({ field: "station_id", operator: "eq", value: station })
    if (direction !== "all")
      filters.push({ field: "direction", operator: "eq", value: direction })
    mutation.mutate({
      ...buildQuery(
        catalog.data,
        selectedMetric,
        dimension === "none" ? [] : [dimension],
        Math.min(100, governance.data.access_scope.row_limit),
      ),
      filters,
    })
  }

  return (
    <div className="space-y-6">
      <PageHeading
        eyebrow="Governed analytics"
        title="受约束客流查询"
        description="只选择注册指标、维度和过滤条件；浏览器不会接收或提交自由 SQL。每次执行都会生成可回读的审计摘要。"
      />
      {catalog.isError ? <ApiError error={catalog.error} /> : null}
      {governance.isError ? <ApiError error={governance.error} /> : null}
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
                  value={selectedMetric}
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
              <div className="rounded-xl border border-emerald-400/12 bg-emerald-400/5 p-3 text-xs leading-5 text-slate-400">
                本次最多返回{" "}
                {Math.min(100, governance.data?.access_scope.row_limit ?? 100)}
                行；最长授权时间范围{" "}
                {governance.data?.access_scope.max_time_range_hours ?? "—"}
                小时。城市、源版本和策略快照由后端状态自动带入。
              </div>
              <Button
                className="w-full"
                disabled={
                  !catalog.data || !governance.data || mutation.isPending
                }
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
  const governance = useQuery({
    queryKey: ["governance-status"],
    queryFn: getGovernanceStatus,
    staleTime: 30_000,
  })
  const [referenceDate, setReferenceDate] = useState("")
  const [targetDate, setTargetDate] = useState("")
  const [schemeId, setSchemeId] = useState(1)
  const mutation = useMutation({ mutationFn: runForecast })
  const forecastAllowed =
    governance.data?.data_scope === "synthetic" &&
    governance.data.access_scope.allowed_dataset_roles.includes("forecast")
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
    if (!governance.data || !forecastAllowed) return
    mutation.mutate({
      reference_date: defaultReference,
      target_date: defaultTarget,
      scheme_id: schemeId,
      limit: Math.min(1000, governance.data.access_scope.row_limit),
    })
  }
  const rows = mutation.data?.rows ?? []
  const forecastMetrics = useMemo(
    () =>
      (["entries", "exits", "transfers", "net_inflow"] as const).filter(
        (metric) => rows.some((row) => typeof row[metric] === "number"),
      ),
    [rows],
  )
  const chartMetric = forecastMetrics[0]
  const stationTotals = useMemo(() => {
    const totals = new Map<string, number>()
    if (!chartMetric) return []
    for (const row of rows)
      totals.set(
        String(row.station_id),
        (totals.get(String(row.station_id)) ?? 0) +
          Number(row[chartMetric] ?? 0),
      )
    return [...totals.entries()]
  }, [chartMetric, rows])

  return (
    <div className="space-y-6">
      <PageHeading
        eyebrow="Scenario preview"
        title="指定日基线预测"
        description="把参考日的站点进出站模式映射到目标日，用于验证预测链路和界面；方法明确标注为 reference_day_copy，不代表机器学习精度。"
        action={<Badge tone="amber">非 ML 模型</Badge>}
      />
      {catalog.isError ? <ApiError error={catalog.error} /> : null}
      {governance.isError ? <ApiError error={governance.error} /> : null}
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
                {forecastAllowed
                  ? "输出复制参考日客流结构，仅用于受治理的 baseline preview。页面不会声称模型准确率。"
                  : "当前数据范围或身份未授权 forecast；生产 shadow 不会把参考日复制误作生产预测。"}
              </div>
              <Button
                className="w-full"
                disabled={
                  !forecastAllowed || !defaultReference || mutation.isPending
                }
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
                {chartMetric ? (
                  <MetricChart
                    labels={stationTotals.map(([station]) => station)}
                    values={stationTotals.map(([, value]) => value)}
                    name={`预测${metricMeta[chartMetric].label}`}
                    color="#fbbf24"
                  />
                ) : null}
                <div className="overflow-auto rounded-xl border border-white/8">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>时间</th>
                        <th>线路</th>
                        <th>车站</th>
                        <th>方向</th>
                        {forecastMetrics.map((metric) => (
                          <th key={metric}>{metricMeta[metric].label}</th>
                        ))}
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
                          {forecastMetrics.map((metric) => (
                            <td key={metric}>{formatNumber(row[metric])}</td>
                          ))}
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
    <div className="min-w-0 rounded-xl bg-white/4 p-3">
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
  const governance = useQuery({
    queryKey: ["governance-status"],
    queryFn: getGovernanceStatus,
    staleTime: 30_000,
  })
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
              governance.refetch()
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
          status={
            governance.data?.data_source.runtime_quality_status === "pass"
          }
          detail={
            governance.data
              ? `${governance.data.data_source.city ?? "—"} · 注册 ${governance.data.data_source.registration_quality_status} / 运行 ${governance.data.data_source.runtime_quality_status}`
              : "等待治理状态"
          }
        />
        <SystemCard
          icon={ShieldCheck}
          label="接口契约"
          value="OpenAPI generated"
          status
          detail="TypeScript 客户端自动生成"
        />
      </div>
      {governance.isError ? <ApiError error={governance.error} /> : null}
      {governance.data ? <GovernanceDetails status={governance.data} /> : null}
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
              `FastAPI ${health.data?.data_scope ?? "受治理"} 数据服务`,
              "受约束 QueryIR 查询",
              ...(governance.data?.access_scope.allowed_dataset_roles.includes(
                "forecast",
              ) && governance.data.data_scope === "synthetic"
                ? ["指定日 baseline preview"]
                : []),
              "脱敏审计摘要",
              "React + ECharts 展示",
            ]}
          />
          <Boundary
            title="明确未启用"
            items={[
              "自由 SQL / 模型生成 SQL",
              ...(!governance.data?.assistant_enabled
                ? ["被治理门禁阻断的 Assistant 会话"]
                : []),
              "自动写入与处置",
              ...(!governance.data?.identity.multi_user_isolation
                ? ["多用户 IdP 与强隔离（当前为单主体静态令牌）"]
                : []),
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
  const governance = useQuery({
    queryKey: ["governance-status"],
    queryFn: getGovernanceStatus,
    staleTime: 30_000,
  })
  const runtimeLabel =
    governance.data?.data_scope === "production-shadow"
      ? "Real MySQL · Local shadow"
      : governance.data?.data_scope === "production-readonly"
        ? "Production read-only"
        : governance.data?.data_scope === "synthetic"
          ? "Synthetic environment"
          : "Detecting environment"
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
              <span
                className={cn(
                  "h-2 w-2 rounded-full",
                  governance.data?.data_scope === "production-shadow"
                    ? "bg-amber-400"
                    : "bg-emerald-400",
                )}
              />
              <span className="text-xs text-slate-400">{runtimeLabel}</span>
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
