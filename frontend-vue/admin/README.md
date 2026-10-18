# 心晴 · 管理端

Vue 3 + TypeScript + Vite，使用 Element Plus、Pinia、Vue Router 和 ECharts。

## 安装与运行

在仓库根目录执行，Node.js 要求见 [前端运行说明](../README.md)：

```powershell
npm --prefix frontend-vue/admin ci
npm --prefix frontend-vue/admin run dev
```

管理端地址：<http://127.0.0.1:5173>。后端默认 <http://127.0.0.1:8000>，通过 `.env.development` 中的 `VITE_API_BASE` 配置。
后端环境和模型准备见 [队友本地运行指南](../../docs/队友本地运行指南.md)。

## 构建

```powershell
npm --prefix frontend-vue/admin run build
```

命令先运行 TypeScript 检查，再构建 `dist/index.html`；当前配置将管理端打包为单个 HTML 文件。

## 对接文档

- [管理端对接文档](../docs/管理端-对接文档.md)
- [新版前端接入说明](../docs/新前端接入说明.md)
- [项目文档索引](../../docs/README.md)
