# 受治理客流智能体工作流

本智能体采用固定外层状态机和可替换模型边界。它不是让模型自由调用数据库或任意函数，而是让模型在确定性基线、工具白名单、证据和核验器保护下完成语言理解与表达。

## 运行闭环

```text
RECEIVE → UNDERSTAND → CLARIFY → PLAN → EXECUTE_TOOLS
        → OBSERVE → REPLAN → SYNTHESIZE → VERIFY → RESPOND
```

正常的真实模型路径通常包含三次模型调用：

1. 用户语言 → `IntentEnvelope`；
2. `IntentEnvelope` → `TaskPlan`；
3. `EvidencePacket` → `AssistantResponse`。

工具失败时可增加一次受限重规划，但模型只能建议重试“原计划中已失败、无依赖、参数完全相同”的调用。它不能借失败新增工具、改变参数或扩大数据范围；不满足约束就不执行重试。默认 `FakeProvider` 是确定性代码，不产生真实模型调用；`RunRecord.model_runtime` 会区分 Provider 调用尝试、真实模型调用、token 报告可用性与耗时。

## Protected baseline

当前版本在工具执行前同时生成：

- catalog-aware 的确定性 protected intent 与模型候选 intent；
- 确定性 protected plan 与模型候选 plan。

`verify_intent` 检查任务类型、实体、指标、时间、歧义、活动和换乘规格；`verify_plan` 检查任务类型、步骤、工具、参数、依赖、预期证据和回答格式。关键字段漂移时，在调用业务工具前拒绝。

这保证当前原型稳健，但也意味着模型的实际规划自由度和增益有意受限。扩大权限前，必须用真实业务 Gold Cases、hard negatives 和基线对照证明净增益。

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
- `assistant/context_builder.py`：有界指标目录、业务字典、近期历史和工具上下文。
- `assistant/orchestrator.py`：状态机、澄清门、依赖调度、并行、失败继续与一次重规划。
- `assistant/provider.py`：离线与真实模型适配边界。
- `assistant/tool_registry.py`：受控查询、统计、预测、换乘、GIS、SOP 和报告工具。
- `assistant/evidence.py`：工具结果到 `EvidencePacket` 的规范化。
- `assistant/verifier.py`：意图/计划漂移、证据引用、有限数和回答数字支持硬门。
- `assistant/trace_store.py`：可回放 session/run 轨迹和人工反馈。

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

活动、跨网、GIS、实时和 SOP 数据当前均为合成夹具。活动因子用于验证架构，不是预测准确率结论。

## HTTP 接口

- `GET  /api/v1/assistant/capabilities`
- `POST /api/v1/assistant/sessions`
- `POST /api/v1/assistant/sessions/{session_id}/messages`
- `GET  /api/v1/assistant/runs/{run_id}`
- `GET  /api/v1/assistant/runs/{run_id}/events`
- `POST /api/v1/assistant/runs/{run_id}/feedback`

Web“智能分析”页面展示多轮对话、核验回答、任务类型、Provider、模型实际调用信息、工具时间线、状态机、证据卡、结果表、图表、限制和人工确认建议。

## 评测

```bash
python scripts/build_assistant_gold_cases.py
python scripts/evaluate_assistant.py --output /tmp/assistant-eval.json
python scripts/evaluate_gpt56_shadow.py \
  --case-id assistant-001 --case-id assistant-021 --case-id assistant-081 \
  --output /tmp/gpt56-shadow.json
```

100 条用例检查任务类型、工具集合、参数、状态机、工具状态、证据类型、artifact、非因果限制和人工确认边界。通过表示结构化本地轨迹满足已有断言，不等于生产准确率。

只有工具成功、证据完整、核验通过，并进一步通过 Gold Case 或获得真实人工采纳的轨迹，才可能进入未来数据集候选。系统不伪造人工标签。

## 生产准入缺口

- 权威运营数据与真实活动/摄像头/公交/GIS 数据；
- 正式认证授权、RBAC/ABAC、字段级脱敏和审计保留策略；
- 真实预测准确率、性能、并发、成本和灾备验收；
- 生产 OpenAI-compatible 端点与批准的 secret manager；
- 正式 SOP、调度、通知和运营联动责任流程；
- 真实模型 100 条 Gold Cases 与相对确定性基线的净增益证明。

在这些闸门完成前，本项目应表述为“本地受治理原型”，不能表述为已上线的生产客流决策系统。