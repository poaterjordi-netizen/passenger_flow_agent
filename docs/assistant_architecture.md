# 受治理客流智能体工作流

本智能体采用固定外层状态机和可替换模型边界。它不是让模型自由调用数据库或任意函数，而是让模型在确定性基线、工具白名单、证据和核验器保护下完成语言理解与表达。

## 运行闭环

```text
RECEIVE → UNDERSTAND → COMPILE_OPERATION → CLARIFY → PLAN → EXECUTE_TOOLS
        → OBSERVE → REPLAN → SYNTHESIZE → VERIFY → RESPOND
```

模型调用由确定性 route selection 决定，而不是固定三次调用：

“列出所有站点/线路”使用 `list_observed_entities`：它从已准入事实时间窗执行完整去重查询并由确定性 renderer 直接回答；若发生截断则拒绝宣称完整，并明确它不是跨表主数据扫描。此路径不调用 GPT。

1. 确定性解析器高置信命中时直接产生 `IntentEnvelope`；
2. 解析器仅产生有限候选或 abstain，且模型端点策略允许时，模型才提出 Intent 候选；
3. 城市、数据角色、来源版本、指标版本和粒度由服务端锁定，候选还必须通过 catalog、实体、时间和 AccessContext 硬校验；
4. 已验证 Intent 编译成稳定的 `OperationIR`，再匹配 `config/assistant_capabilities.json` 中版本化能力；
5. `TaskPlan` 始终由确定性 planner 生成，且使用的工具必须属于所匹配能力；
6. 工具结果必须附带 `CoverageEvidence`，明确观测时间窗、目录范围、是否权威主数据、返回/匹配数、完整性和截断状态；
7. 能力的 `answer_policy` 决定回答层：目录、日期、实体清单和数据概况使用零模型 renderer，复杂分析才允许 Evidence synthesis；
8. 只有数据出域策略批准时，真实 Provider 才接收 `EvidencePacket`。否则使用确定性 renderer。

## OperationIR 与能力发现

`OperationIR` 是问法和工具之间的稳定层。目前覆盖 `list_entities`、`describe_entity`、`list_metrics`、`list_available_dates`、`summarize_dataset`、`query_metric`、`rank_entities`、`compare_periods`、`travel_plan`、`capability_help`、`general_answer`、预测、预警、换乘、GIS、相关、诊断、趋势、报告和能力准入检查。诸如“有哪些车站”“车站清单”“把数据库里的地铁站给我”会编译成同一个操作，不再为每种措辞添加后端特判。

能力注册表声明每个 Operation 的可用数据范围、实体类型、必需槽位、工具集合、完整性策略和回答策略。运行时 `/api/v1/assistant/capabilities` 返回注册表版本以及经过当前数据范围物理裁剪后的可用/不可用工具；Web 页面直接显示这些信息。

`travel_plan` 把校园、场馆等外部地点与客流数据库实体分开处理。规则解析支持“从 A 到 B 怎么走”“出行规划”以及常见错字“出现规划”，仅起点和终点是必需槽位，不会追问客流指标或数据库日期。已登记地点对由 `config/travel_routes.json` 提供带来源的静态建议，同时始终生成实时地图入口；未登记地点对直接交给实时地图解析，不编造静态线路。此路径使用 `external_navigation` 覆盖证据和确定性回答，不调用 GPT。

开放问题采用两级泛化兜底，而不是继续扩大互斥业务枚举：`capability_help` 从当前能力注册表生成“能做什么”清单，零模型调用；`general_answer` 为有明确语义但不需要客流工具的问题准备不含业务数据行的边界上下文，然后调用 GPT 一次。通用回答可以使用稳定的一般知识，但必须明确未读取 metroflow 数据库；涉及新闻、价格、法规、运营状态等实时事实而当前又没有外部工具时，回答必须指出所需数据源，不能把模型记忆冒充实时查询。只有问题本身缺少分析对象、目标或执行所需槽位时才进入澄清。

路由优先级为：高置信确定性业务 Operation → 能力帮助或通用回答 → 低置信模型候选。已存在的客流查询、排行、对比和预测不会被通用兜底截获；“比较北京和上海旅游”“预测明天天气”等非客流问题不会再误调用客流工具。通用路径仍生成 ToolResult、CoverageEvidence、EvidencePacket、模型出域记录和 verifier 结果，因此不是绕过治理的自由聊天接口。

发现型工具包括：

- `list_observed_entities` / `describe_observed_entity`：已准入实际事实时间窗内的实体，不冒充跨表权威主数据；
- `list_metrics`：版本化受控指标目录；
- `list_available_dates`：登记的数据日期范围；
- `describe_data_scope`：数据范围、城市、来源版本、指标数、日期数和质量摘要。

所有发现型回答都要求完整且未截断。复杂统计、排行、比较和预测仍通过 QueryIR 与确定性工具取得数字；GPT 只组织已存在证据，不生成 SQL 或数字。

工具失败时的一次重试也由确定性 planner 产生。重试计划保留原图的完整下游闭包并重映射依赖，因此失败根节点成功后下游计算也会真正重跑；最终 Evidence 只使用本次重试图的成功结果。默认 `FakeProvider` 不产生真实模型调用。

每次真实 Provider 调用都有独立 `ModelEgressRecord`：调用目的、批准/拒绝决定、provider/model/target hash 精确绑定、出域最小包字段路径、精确包 hash、开始/完成时间和成败状态。记录在调用前先落轨迹，失败也会收口为 `failed`。Intent 和 Evidence 使用分离策略；Intent 包不含完整业务字典/权限/工具目录，Synthesis 包只含问题、数据范围与已核验 Evidence。

## 确定性基线与模型净增益

系统不再要求模型 Intent/Plan 与 `FakeProvider` 整份完全相等。确定性高置信路由直接执行；模型仅在 abstain 路由提出语义候选，并接受不可绕过的字段锁定和权限校验。规划保持确定性，因此模型的可测净增益集中在困难意图/实体消歧和证据表达，而不会扩张查询范围。扩大模型路由前，仍必须用真实业务 Gold Cases、hard negatives 和基线对照证明净增益。

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

### OpenAI-compatible 适配器

```bash
export METRO_ASSISTANT_PROVIDER=openai
export METRO_ASSISTANT_MODEL=gpt-5.6-sol
export OPENAI_API_KEY='由密钥管理器在运行时注入'
# 仅兼容网关需要：
export OPENAI_BASE_URL='https://gateway.example/v1'
metro-agent-api
```

生产使用仍需另行完成内网端点、密钥管理、超时、限流、审计和业务验收。

统一接口：

- `generate_structured(...)`
- `generate_tool_calls(...)`
- `synthesize_from_evidence(...)`
- `stream_text(...)`

## 稳定模块

- `assistant/schemas.py`：意图、计划、工具、证据、回答、运行时、会话和反馈契约。
- `assistant/operation_ir.py`：把不同自然语言问法编译成稳定操作。
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

Web“智能分析”页面展示多轮对话、核验回答、任务类型、Provider、模型实际调用信息、工具时间线、状态机、证据卡、结果表、图表、限制和人工确认建议；出行规划结果额外展示可点击的实时导航与核验来源。
页面同时展示 Operation、能力、回答策略、失败类别和 CoverageEvidence；完整发现型结果不会被前端 20 行预览截断。

## 评测

```bash
python scripts/build_assistant_gold_cases.py
python scripts/evaluate_assistant.py --output /tmp/assistant-eval.json
python scripts/evaluate_gpt56_shadow.py \
  --case-id assistant-001 --case-id assistant-021 --case-id assistant-081 \
  --output /tmp/gpt56-shadow.json
python scripts/summarize_assistant_failures.py /path/to/assistant/traces \
  --output /tmp/assistant-failure-clusters.json
```

100 条用例检查任务类型、工具集合、参数、状态机、工具状态、证据类型、artifact、非因果限制和人工确认边界。通过表示结构化本地轨迹满足已有断言，不等于生产准确率。

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
- `ContextBuilder` 只注入有界目录、质量状态、查询默认值和最近会话，不注入物理表清单或凭据。
- Prompt 只管理策略和结构化输出契约，并在运行轨迹记录版本与哈希。
- 本地 `TraceStore` 已执行 subject/tenant/访问范围对象级隔离；生产存储仍需接入正式身份、加密和保留策略。
- 客流事实不进入长期记忆，始终由受控工具按需查询并封装为 EvidencePacket。
- `EvidencePacket` 在合成前重新计算工具结果 hash，并核验 source lineage、policy snapshot、access scope、完整性和无环依赖；缺 Evidence 或不完整 Evidence 是硬失败，不是 warning。
- `MetroMcpFacade` 仅是 ToolRegistry 的薄协议边界，不提供 SQL、任意表、写操作或通知动作。需要完整上游证据的排名/增长工具不直接暴露给 MCP，避免外部客户端伪造 rows。
- `production-shadow` 必须通过版本化逻辑 registry 与仓库外物理 mapping 双层登记，并记录两者版本/哈希；动态 `current/latest` 来源别名被拒绝。
- production Planner 在计划阶段与实际注册工具取交集：大型活动请求使用真实 actual 上下文和 `assess_event_forecast_readiness`，未准入的其他任务转为 `assess_task_readiness`，不再以 422 掩盖能力缺口，也不调用合成预测、SOP、公交或 GIS 工具。
- 生产实体解析在权威实体 registry 未接入前不会注册，不用合成实体映射冒充生产能力。
- 生产 Assistant 默认关闭；`METRO_PRODUCTION_ASSISTANT_ENABLED=true` 只是提出启用请求，运行时还会机器检查 promotion gate，二者必须同时通过。真实 Intent/Evidence 默认不出域；即使策略允许，provider、model 和 endpoint target hash 任一不精确匹配也 fail closed。
- `config/production_promotion_gates.json` 的 owner、数值阈值、artifact 状态与 approval ref 会被后端实际读取；任一不完整即 fail closed。`GET /api/v1/governance/status` 向已授权前端返回安全摘要，Web 据此控制会话、查询和预测按钮。
