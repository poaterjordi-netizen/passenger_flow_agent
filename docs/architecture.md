# 总体架构

## 设计目标

系统要回答客流问题，但更重要的是回答中的数字可追溯、计算可复现、失败可定位、高风险动作有人负责。为此，语言理解、确定性计算、核验、审计和人工授权被拆成不同责任层。

## 分层结构

```text
React / 微信客户端
        │  只提交业务问题或受约束参数
        ▼
FastAPI 接口层
        │  capabilities / sessions / messages / runs / feedback
        ▼
AssistantService 状态机
        │  Context → Intent → Plan → Execute → Evidence → Verify
        ├───────────────┬─────────────────┐
        ▼               ▼                 ▼
LLM Provider      ToolRegistry       TraceStore
语言与语义候选     确定性业务能力       会话、运行与审计轨迹
        │               │
        │               ▼
        │         QueryIR / 统计 / 预测 / GIS / 报告
        │               │
        └──────────► EvidencePacket
                        │
                        ▼
                    Verifier
                        │
                        ▼
                  RunRecord 返回前端
```

## 核心模块与责任

| 模块 | 责任 | 不承担什么 |
| --- | --- | --- |
| `assistant/orchestrator.py` | 运行状态机、上下文、计划执行、证据与轨迹 | 不直接计算业务数字 |
| `assistant/provider.py` | 统一模型接口、离线 Provider、隔离模型适配 | 不连接数据库或绕过白名单 |
| `assistant/tool_registry.py` | 工具白名单与 Python handler 路由 | 不接受任意函数名或自由 SQL |
| `assistant/evidence.py` | 把工具结果标准化为 `EvidencePacket` | 不创造新的业务事实 |
| `assistant/verifier.py` | 核对意图/计划漂移、证据引用和回答数字 | 不替代业务人员作价值判断 |
| `query_engine.py` | QueryIR 校验、参数化查询、聚合和审计 | 不接受模型自由生成 SQL |
| `database.py` | 受限 MySQL 只读适配、TLS、限行和回滚 | 不提供写库路径 |
| `api/` | 提供 HTTP 契约和错误脱敏 | 不向客户端泄露内部异常 |
| `clients/web/` | 业务交互、证据和轨迹展示 | 不直连数据库 |

## 四个稳定契约

1. `IntentEnvelope`：任务类型、实体、指标、时间和歧义。
2. `TaskPlan / ToolStep`：工具、参数和依赖关系。
3. `ToolResult`：`summary / rows / artifact_refs / warnings / error_code`。
4. `EvidencePacket / AssistantResponse / VerificationReport`：证据、表达与核验结果。

这些契约使前端、模型、数据源和分析算法可以分别演进，而不会互相绑死。

## 不变量

1. 大模型不直接执行 SQL。
2. 数字来自工具结果和证据，不来自模型记忆。
3. 未注册的指标、维度、操作符、字段和工具默认拒绝。
4. 查询范围、行数、运行时间和导出量必须有界。
5. 生产访问、通知、权限和运营动作保留人工闸门。
6. 合成数据验证、模型可靠性评测和真实业务验收必须分开表述。

## 当前阶段

- 已实现：P0 契约与合成数据、P1 确定性查询、只读数据库适配、指定日基线预测、FastAPI、Web、微信客户端和本地受治理智能体原型。
- 已验证：103 项 Python 自动测试、100 条智能体 Gold Cases、Web 类型检查/构建/lint 与 11 条浏览器端到端测试可在当前代码上复跑。
- 未生产化：权威数据接入、正式身份权限、真实预测准确率、性能容量、生产模型端点、外网发布、自动通知和运营联动。
