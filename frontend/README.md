# 旧 React 前端原型

本目录保留早期学生端和教师端页面，以及媒体生命周期、接口协议的回归测试。
当前团队运行入口为 [Vue 学生端与管理端](../frontend-vue/README.md)；项目安装见 [根目录 README](../README.md)。

## 运行与验证

在仓库根目录执行：

```powershell
npm --prefix frontend ci
npm --prefix frontend run dev
```

旧前端使用 5173，与 Vue 管理端共用端口，启动时应二选一。

```powershell
npm --prefix frontend test
npm --prefix frontend run build
```

历史交接见 [旧 React 前端交接文档](../docs/前端交接文档.md)。
