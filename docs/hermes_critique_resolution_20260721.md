# Hermes 批评复核与修正记录（2026-07-21）

## 结论

Hermes 的架构批评总体成立，尤其是身份/对象授权、截断结果派生计算、模型路由和真实证据出域四项 Critical。它引用的“103 项测试、干净仓库、旧四个 Prompt”来自修改前基线，与复核时已有的 111 项测试和未提交实施改动不一致；另外，生产 ToolRegistry 当时已经按运行模式做过一次裁剪，并非只在 capabilities 标记。但这些时间点差异不影响 Critical 风险成立。

## 已完成修正

| 批评 | 判断 | 实施结果 |
|---|---|---|
| production-shadow 缺少身份/owner | 同意 | 新增服务端 `AccessContext`；query、session、run、audit 绑定 subject、tenant、policy snapshot 和 access scope hash；回读重新授权并覆盖 IDOR 负例。生产配置不完整即启动失败。 |
| 截断结果再排名/增长 | 同意 | ToolResult/Evidence 明示 complete/truncated/matched/returned；派生工具声明完整输入门；全局 Top-N 重新执行完整范围聚合排序，不使用 Evidence 前 20 行。 |
| GPT 与 FakeProvider 整份相等 | 同意 | 改成 route selection：高置信确定性解析直接执行；abstain 时模型只提 Intent 候选；protected fields 服务端锁定并硬校验；Planner 和 replan 均确定性。 |
| 真实 Evidence 出域不明确 | 同意 | 新增 endpoint policy 与 `deny/synthetic-only/aggregate-approved` 策略；生产默认 deny，改用确定性 renderer；run 记录决定、字段摘要和 hash。 |
| registry 全部不入 Git 过粗 | 同意 | 拆为可版本化逻辑 registry 和仓库外物理 mapping；运行证据同时记录 logical/physical version 与 hash。 |
| `approved-current` 不可审计 | 同意 | 当前实现采取更严格策略：完全拒绝 current/latest 动态别名，只接受不可变 source version。 |
| QueryIR 时间语义不足 | 同意 | 增加 time basis、timezone、service day、calendar version、explicit comparison periods、cross-midnight policy 和 data-as-of。比较不再在工具内部隐式切半。 |
| EvidencePacket 接近任意 rows | 同意 | 升级 EvidencePacket v2：结构化 claims/result schema、计数、完整性、查询/计划/结果 hash、上游证据、计算方法、策略与授权快照。 |
| ToolRegistry 只标记未裁剪 | 部分已做但需加强 | 生产模式现在物理排除预测、公交、GIS、SOP、报告和导出；未知工具执行前 fail closed。 |
| DataService 可能巨型化 | 同意 | DataService 改为组合 SemanticCatalog、QueryExecutor、ForecastExecutor、AuditRepository、QualityService 的薄 façade；Authorization 和 Evidence 独立；新增 backend conformance 断言。 |
| 缺少人类 Decision Record | 同意 | 新增未批准 decision record 模板，不伪造 owner 或签字。 |
| 业务/数据/代码任务混在一起 | 同意 | promotion gate 明确 required artifacts 和 owner，代码完成不再等价于业务/数据批准。 |
| Prompt 关系不清 | 同意其方向，引用已过时 | 文档改为确定性 route/planner/replan；VERIFY 仍为确定性硬门，模型 critic 不能替代。 |
| 报告导出不应是生产 P0 | 同意 | production-shadow ToolRegistry 不再注册任何报告/导出工具；合成模式导出也受 export policy。 |
| 验收阈值没有机器状态 | 同意 | 新增 `config/production_promotion_gates.json`；零泄漏/零漂移等已设，待业务批准的正确率、成本、超时阈值保持 null，状态为 blocked。 |

## 仍需外部完成的门禁

代码不能代替业务 owner、数据 owner 和安全 owner 的签字。正式网关/IdP、加密并带保留策略的 TraceRepository、真实数据 profile、物理映射批准、数据出域决定、真实 Gold Cases、数据库负载测试和 UAT 仍为外部输入。`production-shadow` Assistant 默认关闭，仓库仍不提供 `production-readonly` promotion 开关。

## 第二轮批评复核与实施

第二轮批评总体成立。其中“promotion gate 没有连到运行时”属于旧快照：当前 API 已在创建 Assistant session 前同时强制 runtime flag 与 promotion gate，Web 也按同一后端状态禁用提交。但这一时点差异不影响其他问题，已按下表修正。

| 批评 | 判断 | 前后端实施 |
|---|---|---|
| 模型出域只有 run 级策略摘要 | 同意 | Intent/Evidence 分策略；绑定 provider/model/target hash；每次调用在调用前记录最小包 hash、字段路径、时间和成败。Web 显示可展开的调用级审计。 |
| `NULL`/missing 被 `or 0` 合并 | 同意 | 缺列、NULL、字符串、bool、非有限数和负数全部 fail closed。Web 分开展示注册/运行质量与缺失/非法计数。 |
| MCP 排名/增长可接受伪造 rows | 同意 | 从 MCP 能力和 schema 物理移除，伪造调用 fail closed；内部状态机仍可用服务端上游结果执行派生计算。 |
| replan 只重试 root，下游未重跑 | 同意 | 重建并重映射完整下游闭包；最终 Evidence 仅采用重试图成功结果。 |
| Evidence 完整性仅 warning，hash/lineage/scope 未复算 | 同意 | 合成前复算 result hash，核验 source lineage、scope、policy、无环性；缺失/不完整 Evidence 硬失败。 |
| QueryIR 字段被接受但忽略 | 同意 | 当前未实现的 grain/service-day/calendar/as-of/cross-midnight 语义在执行前明确拒绝。 |
| Hermes 通过原意图实现完全匹配 | 同意 | 删除 protected reference intent 与精确复述指令；模型仅在 abstain 路由产生候选，并经独立校验。 |
| Forecast 返回未授权指标列 | 同意 | 后端按 AccessContext 投影列；Web 根据实际返回指标动态绘图/建表，不再硬编码三列。 |
| 物理 mapping hash 未绑定实际映射 | 同意 | hash 改由实际固定 SQL adapter 源码 + adapter version 计算并在启动时精确比对；查询模板 hash 进入 provenance/audit。 |
| 生产实体解析与多用户 IdP 能力被高估 | 同意其边界，不伪造外部系统 | 生产 registry 移除实体解析；governance API/Web 明示 `static-token-single-subject` 且 `multi_user_isolation=false`。权威实体库与 IdP 仍是生产外部门禁。 |

修正原则是：代码能强制的边界就 fail closed 并在 API/Web 暴露运行证据；需要真实 IdP、权威实体库或 owner 签字的能力则明确关闭，不用本地 mock 冒充完成。
