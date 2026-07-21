# 项目结构

```text
metro-passenger-flow-agent/
├── src/metro_agent/
│   ├── api/                    FastAPI、请求模型、统一数据服务与生产 shadow 工厂
│   ├── assistant/              智能体契约、Provider、状态机、工具、证据、核验与轨迹
│   ├── access.py               服务端身份范围、查询/对象/导出/模型出域授权
│   ├── contracts.py            指标、Gold Cases 与数据契约校验
│   ├── query_engine.py         QueryIR 编译、参数化查询、聚合与审计
│   ├── database.py             受限 MySQL 只读适配器
│   ├── source_registry.py      逻辑数据产品与仓库外物理 mapping 的严格校验
│   ├── mcp_facade.py           复用 ToolRegistry 的无 SQL 薄 MCP 边界
│   ├── forecasting.py          指定日基线预测转换
│   └── cli.py                  validate/query/eval/database/forecast 命令
├── clients/
│   ├── web/                    React 19 Web 客户端与 Playwright 测试
│   ├── wechat-miniprogram/     原生微信小程序体验客户端
│   └── wechat-multiapp/        Android/iOS/HarmonyOS 多端工程
├── schemas/                    QueryIR 与 Gold Case JSON Schema
├── config/                     可版本化逻辑 registry 与 blocked promotion gate
├── examples/
│   ├── synthetic_data/         可公开、非敏感的确定性夹具
│   └── query_ir/               QueryIR 示例
├── evals/                      业务准确性与 Hermes 可靠性评测说明
├── scripts/                    契约导出、评测、数据集导出和结构检查
├── tests/                      Python 契约、安全、API、智能体和仓库边界测试
├── docs/                       Read the Docs / MkDocs 文档
├── infra/                      CloudBase 等受限部署适配
├── .github/workflows/          CI、质量和安全自动化
├── mkdocs.yml                  文档导航与主题
└── pyproject.toml              Python 包、依赖和 CLI 入口
```

## 智能体目录

| 文件 | 主要对象 | 修改前应先验证 |
| --- | --- | --- |
| `schemas.py` | `IntentEnvelope`、`TaskPlan`、`ToolResult`、`RunRecord` | OpenAPI、前端生成类型、序列化兼容性 |
| `operation_ir.py` | `OperationCompiler`、稳定操作语义 | 同义问法、复杂意图优先级、必要槽位 |
| `capabilities.py` | `CapabilityRegistry`、运行时能力匹配 | 注册表版本、数据范围、物理工具裁剪 |
| `provider.py` | `LLMProvider`、Fake/Hermes/OpenAI-compatible Provider | 结构化输出、错误脱敏、usage 统计 |
| `orchestrator.py` | `AssistantService` 状态机 | 工具执行前硬门、并发、重规划、轨迹 |
| `tool_registry.py` | 工具名到 Python handler 的白名单映射 | 参数校验、合成/真实边界、统一 `ToolResult` |
| `evidence.py` | `EvidencePacket` v2 构造 | schema、计数、完整性、hash、上游证据 |
| `verifier.py` | 意图、计划和回答核验 | 漂移、未引用数字、语义对象交换 |
| `trace_store.py` | owner 隔离的 session/run 原子存储 | 路径、IDOR、访问范围、并发与回放 |
| `failure_analysis.py` | 失败聚类与回归候选 | 问题样例留存边界、类别稳定性 |

## 数据流与代码流

1. 前端调用 FastAPI，不直接访问数据库。
2. FastAPI 调用 `AssistantService` 或 `SyntheticApiService`。
3. 智能体用 `ContextBuilder` 构造有界上下文。
4. 高置信意图由确定性解析器直接产生；abstain 时模型只能提出经 catalog/权限硬校验的候选。
5. Intent 编译为 `OperationIR`，匹配版本化能力注册表的槽位、工具、完整性和回答策略。
6. 确定性 Planner 生成计划；生产 `ToolRegistry` 按模式物理裁剪 handler，计划不得逃逸已匹配能力。
7. handler 调用 QueryIR 或确定性计算，返回 `CoverageEvidence`；完整性不足时拒绝派生结果。
8. 清单/目录由确定性 renderer 零模型回答；复杂分析才把核验证据交给 GPT 组织语言。
9. EvidencePacket v2、Operation、能力、失败类别、回答、核验、owner 与模型出域摘要统一进入 `RunRecord`。

## 运行产物

`artifacts/`、浏览器测试结果、覆盖率、构建目录和本地数据库/审计属于运行态，不应作为业务源码提交。生产凭证、生产行数据、schema inventory 和带敏感参数的 URL 禁止进入仓库。
