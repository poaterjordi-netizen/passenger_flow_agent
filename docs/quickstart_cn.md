# 快速开始

本页用于在本机合成数据上启动后端与 Web，并完成一次可核验的客流查询。默认过程不需要生产数据库或模型密钥。

## 1. 准备 Python 环境

```bash
git clone https://github.com/poaterjordi-netizen/passenger_flow_agent.git
cd passenger_flow_agent
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e .
```

要求 Python 3.11 或更高版本。

## 2. 验证数据契约

```bash
metro-agent validate \
  --metrics examples/synthetic_data/metrics.json \
  --gold-cases examples/synthetic_data/gold_cases.json \
  --data examples/synthetic_data/passenger_flow.csv
```

成功意味着指标目录、合成数据和确定性 Gold Cases 的结构一致；它不代表真实生产数据已经接入。

## 3. 启动 FastAPI

```bash
metro-agent-api
```

默认入口：

- 健康检查：<http://127.0.0.1:8000/health>
- OpenAPI：<http://127.0.0.1:8000/openapi.json>
- 交互式接口：<http://127.0.0.1:8000/docs>

默认 Provider 是离线的 `FakeProvider`，用于开发、CI、演示和可复现评测。

## 4. 启动 Web

新开终端：

```bash
cd clients/web
npm ci
npm run dev
```

打开 <http://127.0.0.1:5173>，进入“智能分析”，输入：

```text
查询各站进站客流并排序
```

页面应显示：结构化任务、工具步骤、工具结果、Evidence Packet、核验状态与模型运行信息。

## 5. 运行质量门

```bash
python3 -m unittest discover -s tests -v
ruff check .
python3 scripts/evaluate_assistant.py --output /tmp/metro-assistant-eval.json
cd clients/web
npm run lint
npm run build
npm run test:e2e
```

如果 8000 或 5173 端口已有本项目服务，可使用 `PLAYWRIGHT_REUSE_SERVERS=1 npm run test:e2e`；先确认该服务确实来自当前项目。

## 6. 可选模型模式

真实模型不是快速开始的前置条件。需要模型实验时，先阅读[智能体工作流](assistant_architecture.md)。

- `METRO_ASSISTANT_PROVIDER=hermes-codex`：本机隔离 shadow 路线，不是生产部署方式。
- `METRO_ASSISTANT_PROVIDER=openai`：OpenAI-compatible 适配器，凭证只在运行时注入。

不要把密钥、生产数据、查询结果或审计产物提交到 Git。