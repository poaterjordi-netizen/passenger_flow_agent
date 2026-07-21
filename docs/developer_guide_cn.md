# 开发者指南

## 开发原则

1. 先稳定业务契约，再改界面或模型提示词。
2. 新数字必须由确定性工具产生，并进入 `EvidencePacket`。
3. 模型不能获得自由 SQL、任意函数或生产写入能力。
4. 合成验证、真实模型 shadow 和生产验收必须分别记录。
5. 后端契约是前端类型的唯一事实源；生成代码不得手改。

## 新增分析算法

以“站点拥挤风险评分”为例：

1. 编写纯分析函数，明确字段、单位、空值和极端值；
2. 增加正常、空数据、零容量、边界值和失败路径测试；
3. 在 `ToolRegistry` 增加包装 handler；
4. 注册唯一白名单工具名；
5. 让确定性 planner 在明确任务类型下生成该步骤；
6. 返回统一 `ToolResult`；
7. 检查 `EvidencePacket` 的证据类型和内容上限；
8. 增加回答数字与语义对象核验测试；
9. 更新 Gold Case、文档和必要的前端展示。

只有当该能力需要脱离智能体被独立调用时，才新增专用 API；不要为每个工具建立一套平行接口。

## 修改 API 契约

```bash
.venv/bin/python scripts/export_openapi.py
cd clients/web
npm run generate-client
npm run check
```

提交前连续生成两次并确认没有随机漂移。`clients/web/src/client/` 是生成目录。

## 测试矩阵

```bash
# Python 与契约
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check .
.venv/bin/metro-agent validate \
  --metrics examples/synthetic_data/metrics.json \
  --gold-cases examples/synthetic_data/gold_cases.json \
  --data examples/synthetic_data/passenger_flow.csv

# 智能体评测
.venv/bin/python scripts/evaluate_assistant.py \
  --output /tmp/metro-assistant-eval.json

# Web
cd clients/web
npm run lint
npm run build
npm run test:e2e

# 文档
cd ../..
.venv/bin/mkdocs build --strict
```

项目说明 PPT 的可重复生成入口是 `scripts/build_project_briefing_ppt.py`。它是可选文档工具，不属于服务运行依赖：

```bash
.venv/bin/python -m pip install python-pptx
.venv/bin/python scripts/build_project_briefing_ppt.py
officecli validate docs/assets/metro-passenger-flow-agent-overview-cn.pptx
```

行为改动应增加最小回归测试。只改变文档时至少运行严格文档构建和链接/导航检查。

## 代码审查重点

- 输入是否经过 Pydantic/QueryIR schema；
- 工具是否在白名单中，参数是否可控；
- SQL 是否固定模板并参数化；
- 数字是否能回到工具结果和 evidence_id；
- 失败是否脱敏、可观测且不会留下误导性旧产物；
- 真实数据、通知、权限或运营动作是否越过人工闸门；
- 合成能力是否被误写成生产能力或预测准确率。

## 协作边界

- 通过 Issue/PR 描述问题、验收标准和验证命令；
- 一个变更只解决一个主要问题，不顺带重构；
- 不提交 `.env`、密钥、token、生产数据、运行审计和本地构建目录；
- `git push`、公开发布、生产访问、权限变化、通知和破坏性操作需要项目负责人确认。

## 常见扩展点

| 需求 | 推荐承载层 |
| --- | --- |
| 新增指标或维度 | 指标目录 + QueryIR + QueryEngine + Gold Cases |
| 新增统计/预测算法 | 纯函数 + ToolRegistry handler + Evidence + Verifier |
| 更换模型 | `LLMProvider` 实现，不改业务工具 |
| 更换前端 | 复用 OpenAPI 与 `RunRecord` |
| 更换数据库 | 只读 repository/adapter，不改前端契约 |
| 新增生产动作 | 独立权限、审计、幂等与人工审批流程，不能塞进现有只读工具 |