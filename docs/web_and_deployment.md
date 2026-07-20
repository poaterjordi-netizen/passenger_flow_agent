# Web 前端与服务器部署

网页第一版位于 `clients/web/`，采用 React 19、TypeScript、Vite、Tailwind CSS、shadcn 风格本地组件、TanStack Query 和 Apache ECharts。业务类型与请求函数由 FastAPI 的 `openapi.json` 自动生成，前端不维护第二套手工 API 类型。

## 本地开发

在仓库根目录启动后端：

```bash
.venv/bin/metro-agent-api
```

在另一终端启动前端：

```bash
cd clients/web
npm ci
npm run dev
```

打开 <http://127.0.0.1:5173>。Vite 将 `/api` 和 `/health` 代理到本地 FastAPI。

后端契约变化后重新生成客户端：

```bash
.venv/bin/python scripts/export_openapi.py
cd clients/web
npm run generate-client
npm run check
```

`clients/web/openapi.json` 和 `src/client/` 都是可回读的契约产物。不得手工修改 `src/client/`。

## 容器运行

本地具备 Docker Compose 时，在仓库根目录运行：

```bash
docker compose up --build
```

默认只绑定 `127.0.0.1:8080`，不会公开到局域网或公网。可通过 `METRO_WEB_BIND` 和 `METRO_WEB_PORT` 明确覆盖。Nginx 提供前端静态文件，并把同源 `/api/` 与 `/health` 反向代理到内部 FastAPI 容器；FastAPI 不对宿主机单独暴露端口。

Compose 复用了成熟模板的前后端分容器、健康依赖、只读业务边界和反向代理结构，但没有引入 PostgreSQL、SQLModel、通用 CRUD、用户系统、Traefik、域名或 HTTPS。公网部署、域名、TLS、认证、生产数据库和权限策略必须另过人类闸门。

## 验证

```bash
cd clients/web
npm run generate-client
npm run lint
npm run build
npx playwright install chromium
npm run test:e2e
```

网页验收覆盖总览加载、QueryIR 查询与审计状态、以及预测方法的明确标注。后端仍运行仓库既有的 unittest、Ruff 和 contract validation。

## 第三方来源

工程结构参考 MIT 许可的 `fastapi/full-stack-fastapi-template`，但业务页面、样式和 API 适配为本项目独立实现。依赖许可证由对应 npm/Python package 管理；归属说明见 `THIRD_PARTY_NOTICES.md`。
