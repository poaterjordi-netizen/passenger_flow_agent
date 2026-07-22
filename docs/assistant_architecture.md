# 受治理客流智能体工作流

本智能体采用 GPT 优先的通用语义编译层和固定执行状态机。无限自然语言由模型理解；有限业务语义、实体 ID、指标、QueryIR、数据库执行、证据与核验由后端确定。模型不会生成 SQL 或直接访问数据库。

## 运行闭环

```text
RECEIVE → SEMANTIC_FRAME → LINK_SEMANTICS → COMPILE_OPERATION → CLARIFY
        → PLAN → EXECUTE_TOOLS → OBSERVE → REPLAN → SYNTHESIZE → VERIFY → RESPOND
```

每个自由问题优先调用一次 GPT-5.6 Sol 产生严格 `SemanticFrame`。清单、实体概况和目录查询通常只需这一次理解调用；复杂分析、一般知识和混合问题再调用一次证据合成；数据库工具本身不调用模型。

“列出所有站点/线路”在语义编译后使用 `list_observed_entities`，由确定性 renderer 直接回答；若发生截断则拒绝宣称完整，并明确它不是跨表主数据扫描。此路径只有语义编译一次模型调用，不做第二次文案合成。

1. 模型只输出 `data/general/hybrid/external/clarify` 路线、业务动作、目标类型、实体原文、指标候选、时间表达和证据需求；
2. `SemanticFrame` 的严格 Schema 不含 `resolved_id`、SQL、物理表字段或查询结果；实体原文还必须来自当前问题，承接上文时必须显式声明 `inherit_context`；
3. 后端从登记目录或当前准入数据时间窗确定性链接实体和指标。唯一高置信候选自动采用，并列候选才追问，没有候选则明确“数据库未观测到”；
4. 城市、数据角色、来源版本、指标版本、时间范围和粒度由服务端锁定，再编译为稳定 `IntentEnvelope` / `OperationIR` 并匹配版本化能力；
5. `TaskPlan` 始终由确定性 planner 生成，且使用的工具必须属于所匹配能力；
6. 工具结果必须附带 `CoverageEvidence`，明确观测时间窗、目录范围、是否权威主数据、返回/匹配数、完整性和截断状态；
7. 能力的 `answer_policy` 决定回答层：目录、日期、实体清单和数据概况使用确定性 renderer；复杂分析使用 Evidence synthesis；`hybrid` 使用区分“数据库证据/一般知识”的专用合成；
8. 只有数据出域策略批准时，真实 Provider 才接收 `EvidencePacket`。否则使用确定性 renderer。

## OperationIR 与能力发现

`SemanticFrame` 是问法和业务语义之间的开放层，`OperationIR` 是业务语义和工具之间的稳定层。目前还包含 `external_answer`。诸如“说说一号线”“数据库里 1 号线啥情况”“把一号线画像讲明白”由模型编译成相同业务动作，而不是继续添加说法规则。

能力注册表声明每个 Operation 的可用数据范围、实体类型、必需槽位、工具集合、完整性策略和回答策略。运行时 `/api/v1/assistant/capabilities` 返回注册表版本以及经过当前数据范围物理裁剪后的可用/不可用工具；Web 页面直接显示这些信息。

`travel_plan` 把校园、场馆等外部地点与客流数据库实体分开处理。语义模型标记起点和终点角色，后端只在确实缺少其中一个时追问。已登记地点对由 `config/travel_routes.json` 提供带来源的静态建议，同时始终生成实时地图入口；未登记地点对直接交给实时地图解析，不编造静态线路。

系统显式支持五条路线：`data` 读取数据库，`general` 使用稳定一般知识，`hybrid` 合并数据库证据与一般解释，`external` 要求天气、活动、实时运营或导航工具，`clarify` 只处理真正改变结果的缺失字段。未接入外部实时工具时，`external_answer` 返回机器可见的能力边界，不把模型记忆冒充当前事实。

真实 Provider 配置并获策略批准时，模型语义是主路由；旧确定性解析器每次仍生成影子 `SemanticFrame` 用于差异审计，只在模型不可用、输出不满足 Schema、捏造问题中不存在的实体原文或端点策略拒绝时接管。降级会写入 `semantic_source`、`semantic_shadow_frame`、`semantic_disagreements` 和 `SEMANTIC_FALLBACK` 事件。

保守中文归一化仍用于模型输出后的实体链接和离线降级，例如统一全角数字、中文线路序号和少量无歧义错字；它不再承担真实模型主路由。用户未指定指标或日期且 `defaults_allowed=true` 时，后端采用当前准入时间窗和登记的默认进站量，无需无意义追问。

发现型工具包括：

- `list_observed_entities` / `describe_observed_entity`：已准入实际事实时间窗内的实体，不冒充跨表权威主数据；
- `list_metrics`：版本化受控指标目录；
- `list_available_dates`：登记的数据日期范围；
- `describe_data_scope`：数据范围、城市、来源版本、指标数、日期数和质量摘要。

所有发现型回答都要求完整且未截断。复杂统计、排行、比较和预测仍通过 QueryIR 与确定性工具取得数字；GPT 只组织已存在证据，不生成 SQL 或数字。

工具失败时的一次重试也由确定性 planner 产生。重试计划保留原图的完整下游闭包并重映射依赖，因此失败根节点成功后下游计算也会真正重跑；最终 Evidence 只使用本次重试图的成功结果。默认 `FakeProvider` 不产生真实模型调用。

每次真实 Provider 调用都有独立 `ModelEgressRecord`，调用目的为 `semantic_compile` 或 `synthesis`。语义包只含当前问题、有限目录契约、语义能力卡、最近用户问题和不含事实行的 `SemanticMemory`；Synthesis 包只含问题、数据范围与已核验 Evidence。

## 确定性基线与模型净增益

系统不要求模型语义与 `FakeProvider` 影子结果完全相等，但记录 route、operations、实体类型和关键缺失字段差异。模型语义通过 Schema 后成为主路由；规划仍保持确定性，因此模型可以泛化无限表达，却不能扩张查询范围。

## Provider 模式

### 离线默认模式

```bash
export METRO_ASSISTANT_PROVIDER=fake
metro-agent-api
```

`FakeProvider` 适合开发、CI、演示和可复现 Gold Case 评测，不需要网络或凭证。

### 本机 Hermes Codex shadow

```bash
export METRO_ASSISTANT_PROVIDER=hermes-codex
export METRO_ASSISTANT_MODEL=gpt-5.6-sol
export METRO_ASSISTANT_HERMES_COMMAND=hermes
metro-agent-api
```

该适配器使用隔离的一次性 `hermes --safe-mode` 调用，由 Hermes 自己解析既有 OAuth；本项目不读取或复制凭证。它用于本机 shadow 验证，不是生产部署路线，也不提供逐 token SSE。

### OpenAI Responses API 适配器

```bash
export METRO_ASSISTANT_PROVIDER=openai
export METRO_ASSISTANT_MODEL=gpt-5.6-sol
export METRO_ASSISTANT_REASONING_EFFORT=medium
export OPENAI_API_KEY='由密钥管理器在运行时注入'
# 仅兼容网关需要：
export OPENAI_BASE_URL='https://gateway.example/v1'
metro-agent-api
```

该适配器只调用 `/v1/responses`，把系统约束放入 `instructions`、业务上下文放入
`input`，严格结构化输出放入 `text.format`；每次显式发送 `reasoning.effort`，并以
`store:false` 保持无状态。生产使用仍需另行完成密钥管理、费用限额、超时、限流、
审计和业务验收。

统一接口：

- `generate_structured(...)`
- `generate_tool_calls(...)`
- `synthesize_from_evidence(...)`
- `stream_text(...)`

## 稳定模块

- `assistant/schemas.py`：SemanticFrame、意图、计划、工具、证据、回答、运行时、会话和反馈契约。
- `assistant/semantic.py`：模型语义校验、影子对比、实体/指标链接、Intent 转换和语义记忆。
- `assistant/operation_ir.py`：把有限语义动作编译成稳定操作。
- `assistant/capabilities.py`：加载并校验版本化能力注册表。
- `assistant/context_builder.py`：有界指标目录、业务字典、近期历史和工具上下文。
- `assistant/orchestrator.py`：状态机、澄清门、依赖调度、并行、失败继续与一次重规划。
- `assistant/provider.py`：离线与真实模型适配边界。
- `assistant/tool_registry.py`：受控查询、统计、预测、换乘、GIS、SOP 和报告工具。
- `assistant/evidence.py`：工具结果到 `EvidencePacket` 的规范化。
- `assistant/verifier.py`：意图/计划漂移、证据引用、有限数和回答数字支持硬门。
- `assistant/trace_store.py`：绑定 owner、tenant、访问范围哈希和策略快照的可回放轨迹。
- `assistant/failure_analysis.py`：按失败类别、Operation 和能力聚类轨迹，生成回归候选。
- `access.py`：服务端生成的 AccessContext、查询授权、对象级授权、导出和模型出域策略。

## 工具覆盖

当前白名单包括：

- 指标目录、QueryIR 查询、时段比较和站点排序；
- 线路并行比较、票种/线路/小时合成统计；
- 增长、Pearson/滞后相关、异常、趋势分解和时间序列基线；
- 参考日与活动规则预测、回测样例；
- 合成轨道/公交交易、换乘窗口和阈值比较；
- 合成站点地理编码、OD 热力图和通勤画像；
- 合成容量阈值、SOP、运营指标、人工确认动作候选；
- 候选原因树和本地分析报告。
- 已核验地点对的出行建议与实时地图导航交接。
- 能力自述以及带数据库/实时信息边界的 GPT 通用问答。

活动、跨网、GIS、实时和 SOP 数据当前均为合成夹具。活动因子用于验证架构，不是预测准确率结论。

## HTTP 接口

- `GET  /api/v1/assistant/capabilities`
- `POST /api/v1/assistant/sessions`
- `POST /api/v1/assistant/sessions/{session_id}/messages`
- `GET  /api/v1/assistant/runs/{run_id}`
- `GET  /api/v1/assistant/runs/{run_id}/events`
- `POST /api/v1/assistant/runs/{run_id}/feedback`

Web“智能分析”页面展示 SemanticFrame 路线/目标/动作/置信度、实体原文到数据库 ID 的链接、指标解析、语义记忆快照、旧路由影子差异、模型调用、Operation、能力、工具、证据与核验。`hybrid` 回答在页面明确提示数据库事实和一般推断的边界。

## 评测

```bash
python scripts/build_assistant_gold_cases.py
python scripts/evaluate_assistant.py --output /tmp/assistant-eval.json
python scripts/evaluate_gpt56_shadow.py \
  --case-id assistant-001 --case-id assistant-021 --case-id assistant-081 \
  --output /tmp/gpt56-shadow.json
python scripts/evaluate_semantic_expressions.py \
  --case-id semantic-001 --case-id semantic-006 --case-id semantic-008 \
  --output /tmp/semantic-expression-eval.json
python scripts/summarize_assistant_failures.py /path/to/assistant/traces \
  --output /tmp/assistant-failure-clusters.json
```

原有 100 条用例检查任务类型、工具集合、参数、状态机、证据和人工确认边界。新增 20 条开放表达集覆盖同义改写、错字、口语、多轮、混合问题、不存在实体、非地铁问题与实时问题，并报告路线准确率、实体提及召回、不必要追问、错误通用兜底和平均模型调用次数。二者均不等于生产准确率。

只有工具成功、证据完整、核验通过，并进一步通过 Gold Case 或获得真实人工采纳的轨迹，才可能进入未来数据集候选。系统不伪造人工标签。

失败或追问轨迹会记录机器可读 `failure_category`。聚类脚本按类别、Operation 和能力汇总，输出问题 hash、有限样例、工具错误码及回归测试候选；输出文件必须保留在本地评测目录，不提交真实问题或生产数据到 Git。

## 生产准入缺口

- 权威运营数据与真实活动/摄像头/公交/GIS 数据；
- 正式网关/身份提供方适配、字段级脱敏、加密 TraceRepository 和审计保留策略；
- 真实预测准确率、性能、并发、成本和灾备验收；
- 生产 OpenAI-compatible 端点与批准的 secret manager；
- 正式 SOP、调度、通知和运营联动责任流程；
- 真实模型 100 条 Gold Cases 与相对确定性基线的净增益证明。

在这些闸门完成前，本项目应表述为“本地受治理原型”，不能表述为已上线的生产客流决策系统。

## 数据服务、Prompt、记忆与 MCP 边界

- `PassengerFlowDataService` 只是组合 `SemanticCatalog`、`QueryExecutor`、`ForecastExecutor`、`AuditRepository` 与 `QualityService` 的薄 façade；授权和证据构造保持独立。
- `ContextBuilder` 只注入有界目录、质量状态和查询默认值，不注入物理表清单或凭据；语义模型只收到最近用户问题和语义记忆，不收到上一轮数据库答案正文。
- Prompt 只管理策略和结构化输出契约，并在运行轨迹记录版本与哈希。
- 本地 `TraceStore` 已执行 subject/tenant/访问范围对象级隔离；生产存储仍需接入正式身份、加密和保留策略。
- 客流事实不进入长期记忆；`SemanticMemory` 只保存当前线路/车站 ID、指标、时间范围、上次动作和路线，事实始终由受控工具按需查询并封装为 EvidencePacket。
- `EvidencePacket` 在合成前重新计算工具结果 hash，并核验 source lineage、policy snapshot、access scope、完整性和无环依赖；缺 Evidence 或不完整 Evidence 是硬失败，不是 warning。
- `MetroMcpFacade` 仅是 ToolRegistry 的薄协议边界，不提供 SQL、任意表、写操作或通知动作。需要完整上游证据的排名/增长工具不直接暴露给 MCP，避免外部客户端伪造 rows。
- `production-shadow` 必须通过版本化逻辑 registry 与仓库外物理 mapping 双层登记，并记录两者版本/哈希；动态 `current/latest` 来源别名被拒绝。
- production Planner 在计划阶段与实际注册工具取交集：大型活动请求使用真实 actual 上下文和 `assess_event_forecast_readiness`，未准入的其他任务转为 `assess_task_readiness`，不再以 422 掩盖能力缺口，也不调用合成预测、SOP、公交或 GIS 工具。
- 生产实体解析从当前准入实际客流时间窗读取真实 ID/名称候选并标记为 `observed_database_entity`；它不冒充跨表权威主数据，未来仍可替换为正式实体 registry。
- 生产 Assistant 默认关闭；`METRO_PRODUCTION_ASSISTANT_ENABLED=true` 只是提出启用请求，运行时还会机器检查 promotion gate，二者必须同时通过。真实 Intent/Evidence 默认不出域；即使策略允许，provider、model 和 endpoint target hash 任一不精确匹配也 fail closed。
- `config/production_promotion_gates.json` 的 owner、数值阈值、artifact 状态与 approval ref 会被后端实际读取；任一不完整即 fail closed。`GET /api/v1/governance/status` 向已授权前端返回安全摘要，Web 据此控制会话、查询和预测按钮。
