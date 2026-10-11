# frontend-vue · 心晴新前端（Vue 3）

本目录是「心晴」校园心理健康筛查系统的**新版前端**，与仓库里原有的旧版前端 `../frontend/`（React）并存，二者互不影响。

## 目录结构

| 目录 | 说明 | 开发端口 |
| --- | --- | --- |
| `admin/` | 管理端（教师 / 管理员） | 5173 |
| `student/` | 学生端 | 5174 |
| `docs/` | 新版前端的设计与对接文档 | — |

技术栈：Vue 3 + TypeScript + Vite + Pinia + Vue Router；管理端额外使用 Element Plus，两端均使用 ECharts。

## 环境要求

- **Node.js ≥ 20.19（或 ≥ 22.12），建议直接用 22 LTS 或更高。** 本项目使用 Vite 8，Node 版本过低时 `npm install` / `npm run dev` 会报错。
- npm（随 Node 一起安装即可）。
- 后端需在本机运行（默认 `http://127.0.0.1:8000`），安装与启动见 [../docs/队友本地运行指南.md](../docs/队友本地运行指南.md)。

> `node_modules/`、`dist/` 不入库，**克隆仓库后必须自己执行一次 `npm install`**。

## 首次运行

分别进入两个子目录安装依赖并启动（各开一个终端）：

```powershell
# 学生端 → http://127.0.0.1:5174
cd frontend-vue/student
npm install
npm run dev
```

```powershell
# 管理端 → http://127.0.0.1:5173
cd frontend-vue/admin
npm install
npm run dev
```

后端地址在各自的 `.env.development` 中通过 `VITE_API_BASE` 配置（默认 `http://127.0.0.1:8000`），一般无需改动。后端 CORS 已默认放行 `http://localhost:5173`、`http://127.0.0.1:5173`、`http://localhost:5174`、`http://127.0.0.1:5174`。

## 一键启动

仓库根目录的 `../一键启动.bat` 会自动探测 Python 并依次拉起 Ollama、后端与两个前端。

> 该脚本**只负责启动，不负责安装依赖**：首次仍需按上面「首次运行」各执行一次 `npm install`；后端环境与模型见 [队友本地运行指南](../docs/队友本地运行指南.md)。

## 构建

```powershell
npm run build
```

- 学生端：常规 Vite 产物（输出到 `dist/`）。
- 管理端：使用 `vite-plugin-singlefile` 打成**单个 `index.html`**，可直接双击打开（无需服务器）。

## 接口约定

见 [docs/新前端接入说明.md](docs/新前端接入说明.md)：后端返回裸 JSON（不是 `{ code, data, message }` 包裹）、错误统一为 `{ error: { code, message } }`、无鉴权。
