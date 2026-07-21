# 项目结构

```text
metro-passenger-flow-agent/
├── src/metro_agent/
│   ├── api/                    FastAPI、请求模型、设置与合成服务
│   ├── assistant/              智能体契约、Provider、状态机、工具、证据、核验与轨迹
│   ├── contracts.py            指标、Gold Cases 与数据契约校验
│   ├── query_engine.py         QueryIR 编译、参数化查询、聚合与审计
│   ├── database.py             受限 MySQL 只读适配器
│   ├── forecasting.py          指定日基线预测转换
│   └── cli.py                  validate/query/eval/database/forecast 命令
├── clients/
│   ├── web/                    React 19 Web 客户端与 Playwright 测试
│   ├── wechat-miniprogram/     原生微信小程序体验客户端
│   └── wechat-multiapp/        Android/iOS/HarmonyOS 多端工程
├── schemas/                    QueryIR 与 Gold Case JSON Schema
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
| `provider.py` | `LLMProvider`、Fake/Hermes/OpenAI-compatible Provider | 结构化输出、错误脱敏、usage 统计 |
| `orchestrator.py` | `AssistantService` 状态机 | 工具执行前硬门、并发、重规划、轨迹 |
| `tool_registry.py` | 工具名到 Python handler 的白名单映射 | 参数校验、合成/真实边界、统一 `ToolResult` |
| `evidence.py` | `EvidencePacket` 构造 | evidence_id、截断、缺失证据 |
| `verifier.py` | 意图、计划和回答核验 | 漂移、未引用数字、语义对象交换 |
| `trace_store.py` | session/run 原子存储 | 路径校验、并发与回放 |

## 数据流与代码流

1. 前端调用 FastAPI，不直接访问数据库。
2. FastAPI 调用 `AssistantService` 或 `SyntheticApiService`。
3. 智能体用 `ContextBuilder` 构造有界上下文。
4. Provider 生成结构化候选；Verifier 与 protected baseline 比较。
5. `ToolRegistry` 只执行已注册 handler。
6. handler 调用 QueryIR、统计、预测或报告代码，返回 `ToolResult`。
7. 证据、回答、核验和轨迹统一进入 `RunRecord`。

## 运行产物

`artifacts/`、浏览器测试结果、覆盖率、构建目录和本地数据库/审计属于运行态，不应作为业务源码提交。生产凭证、生产行数据、schema inventory 和带敏感参数的 URL 禁止进入仓库。