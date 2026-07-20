# 开源前后端复用评估

本评估面向 `metro-passenger-flow-agent` 的服务器后端与网页前端建设。判断标准不是项目名称是否相似，而是许可证、现有代码完成度、技术栈兼容性、维护活跃度、可验证性和迁移成本。

## 当前项目基线

当前仓库已经具备：

- FastAPI `/api/v1` 服务；
- 受约束的客流查询、指定日基线预测和审计摘要接口；
- synthetic 数据契约、测试和 OpenAPI；
- 只读 MySQL adapter；
- 微信小程序客户端。

因此不应替换现有后端业务内核。最经济的路线是保留现有 FastAPI、QueryIR、审计和数据库安全边界，只复用成熟项目的 Web 前端骨架、OpenAPI 客户端生成、Docker Compose、反向代理、健康检查和端到端测试结构。

## 候选项目

| 项目 | 许可证与活跃度（2026-07-20 查询） | 可复用能力 | 主要问题 | 结论 |
|---|---|---|---|---|
| [fastapi/full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template) | MIT；44,314 stars；2026-07-14 有提交 | FastAPI + React 19 + TypeScript + Vite + Tailwind/shadcn；OpenAPI 客户端；Playwright；Docker Compose；Traefik/HTTPS；健康检查；CI/CD | 自带 SQLModel/PostgreSQL、用户管理和认证，不能直接覆盖现有 QueryIR/审计后端 | **主基座**：移植 frontend 与部署结构，保留本项目后端 |
| [ant-design/ant-design-pro](https://github.com/ant-design/ant-design-pro) | MIT；38,560 stars；2026-07-15 有提交 | 成熟中后台布局、表格、筛选、监控页、国际化、暗色主题、D3/plots | React 19 + Umi Max 4，整仓较重；与 Vite 主基座并用会形成两套前端框架 | **组件/交互参考**，不整仓引入 |
| [mizhexiaoxiao/vue-fastapi-admin](https://github.com/mizhexiaoxiao/vue-fastapi-admin) | MIT；2,203 stars；最后提交 2025-07-04 | Vue 3 + Naive UI + FastAPI；RBAC、动态路由、JWT、Docker | 会复制一套后端、权限模型和路由；与当前 FastAPI 内核整合成本较高 | 备选；只有团队明确偏好 Vue 时采用 |
| [insistence/RuoYi-Vue3-FastAPI](https://github.com/insistence/RuoYi-Vue3-FastAPI) | MIT；1,443 stars；2026-05-19 有提交 | 中文后台生态、Vue 3 + Element Plus + FastAPI、RBAC、代码生成 | 功能面过大；若依体系会把客流产品变成通用后台，维护熵高 | 不作为当前主线 |
| [sinchang/shmetro-passenger-flow](https://github.com/sinchang/shmetro-passenger-flow) | MIT；已 archived；最后提交 2018-10-27 | 上海地铁客流静态可视化、历史数据展示方式 | 技术陈旧、单页文件、数据截至 2018；无现代 API/测试/部署结构 | 仅参考客流图形表达，不复制架构 |
| [cnmetro/metro-passenger-flow-api](https://github.com/cnmetro/metro-passenger-flow-api) | MIT；已 archived；最后提交 2019-11-22 | 北上广地铁客流数据 API 的字段和采集思路 | 老 Node.js/SQLite 服务；数据来源和当前可用性需重新核实；安全/审计弱于现项目 | 仅参考历史数据接口，不替换后端 |
| [adityabavkar03/metroflow](https://github.com/adityabavkar03/metroflow) | MIT；1 star；2026-07-11 有提交 | 名称和目标最接近；FastAPI + React/Vite + SQLite | README 明确数据、模型、FastAPI、React dashboard、部署仍未完成；后端 API 目录只有早期实现，不能作为成熟基座 | 不采用；其完成度低于当前项目 |
| [zavet-g/passenger-flow](https://github.com/zavet-g/passenger-flow) | GitHub 未识别许可证；README 说明仅限毕业设计内部使用 | FastAPI + Streamlit + Postgres + 多预测模型 + Docker 的完整目录结构 | 非开放复用许可；Streamlit 也不适合作为长期运营 Web 前端 | **禁止复制代码**；只能阅读公开的高层架构思想 |
| [leo271828/MRT](https://github.com/leo271828/MRT) | 无 LICENSE；0 stars；2026-05-24 有提交 | 很接近地铁运营屏：线路图、站点排行、时段筛选、进出站 KPI、暗色主题 | 无复用许可证；主要是大体积静态 HTML/设计稿，无服务器后端 | **禁止复制代码**；可独立重做同类信息结构 |

## 采用决策

选择 `fastapi/full-stack-fastapi-template` 作为工程基座来源，但不 fork 后覆盖现仓库，也不引入它的 SQLModel 业务后端。采用“受控移植”方式：

1. 保留 `src/metro_agent/`、QueryIR、只读数据库 adapter、审计和现有测试作为 protected baseline。
2. 新建 `clients/web/`，移植官方模板的 React/TypeScript/Vite、TanStack Query/Router、Tailwind/shadcn、OpenAPI client generation 和 Playwright 结构。
3. Web 前端只调用现有 `/api/v1/catalog`、`/api/v1/queries`、`/api/v1/forecasts/designated-day`、`/api/v1/audits/{audit_id}`。
4. 以本项目 `openapi.json` 生成 TypeScript client，禁止另写一套漂移的手工 API 类型。
5. 从官方模板适配 Dockerfile、Compose、健康检查和 Nginx/反向代理；第一版先做本地可运行的 `frontend + backend`，PostgreSQL、Traefik、邮件和完整用户系统不在当前范围。
6. 以 Ant Design Pro 和 MRT 项目公开页面的信息层级作为视觉研究对象，但不复制 MRT 的代码或资产；图表采用许可证清晰的 Apache ECharts 或 Ant Design Charts。
7. 在第三方声明中保留所有实际复制组件的 MIT copyright/permission notice。

## 第一版网页范围

- 总览：进站、出站、换乘、净流入 KPI；站点排行；时序趋势；数据范围/口径状态。
- 受约束查询：metric、dimensions、线路、车站、方向、时间范围和 limit 表单；不提供 SQL 输入框。
- 查询结果：图表、表格、QueryIR 摘要、row count、audit id。
- 指定日预测预览：reference date、target date、scheme id；明确标注 `reference_day_copy`，不冒充 ML 精度。
- 审计详情：状态、操作类型、数据源、fingerprint、时间和行数；不暴露敏感原始参数。
- 系统状态：后端健康、environment、data scope、版本。

## 明确不做

- 不用新模板替换现有后端或降低查询/数据库安全门。
- 不接生产数据库、不部署公网、不配置域名/HTTPS、不发送通知；这些动作另过人类闸门。
- 不因外部项目写有“AI prediction”就声称本项目已有真实预测精度。
- 不复制无许可证或限制内部使用项目的源码、样式文件、数据或品牌资产。

## 来源证据

- FastAPI full-stack template README、LICENSE、`frontend/package.json`、`compose.yml`：<https://github.com/fastapi/full-stack-fastapi-template>
- Ant Design Pro README、LICENSE、`package.json`：<https://github.com/ant-design/ant-design-pro>
- Vue FastAPI Admin README、LICENSE：<https://github.com/mizhexiaoxiao/vue-fastapi-admin>
- RuoYi Vue3 FastAPI LICENSE：<https://github.com/insistence/RuoYi-Vue3-FastAPI>
- Shanghai metro passenger flow repo 与 LICENSE：<https://github.com/sinchang/shmetro-passenger-flow>
- Metro passenger flow API 与 LICENSE：<https://github.com/cnmetro/metro-passenger-flow-api>
- MetroFlow README、LICENSE 和源树：<https://github.com/adityabavkar03/metroflow>
- Moscow passenger-flow README 和源树：<https://github.com/zavet-g/passenger-flow>
- Taipei MRT DESIGN 和源树：<https://github.com/leo271828/MRT>
