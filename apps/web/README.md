# 智效工坊 前端应用 (zhixiao-frontend)

> GOAL-04 产出：Vue 3 + TypeScript + Element Plus + Pinia + Vite 企业级工程化前端

## 一、目录结构

```
zhixiao-frontend/
├── index.html
├── package.json                 # 依赖与脚本
├── tsconfig.json
├── vite.config.ts               # 含 SSE 反代关闭缓冲
├── .env.development            # 默认开发环境变量
├── public/
└── src/
    ├── main.ts                  # 应用入口
    ├── App.vue
    ├── api/                     # 各业务 API 封装（auth/space/task/knowledge/stats）
    ├── assets/
    ├── components/common/       # 核心组件
    │   ├── TaskTimeline.vue     # 任务执行时间轴（节点状态/展开详情）
    │   ├── MarkdownView.vue     # Markdown + 代码高亮
    │   ├── SearchBox.vue        # 通用搜索框（防抖/语义检索）
    │   └── PagedTable.vue       # 分页表格
    ├── composables/
    │   └── useSSE.ts            # SSE 客户端（fetch + ReadableStream，支持鉴权）
    ├── layouts/DefaultLayout.vue
    ├── router/index.ts          # 路由守卫 + 懒加载 + 404
    ├── stores/                  # Pinia 状态：user / task
    ├── styles/index.scss        # 主题变量与全局样式
    ├── types/index.ts           # 接口请求/响应 TS 类型声明
    ├── utils/
    │   ├── request.ts           # Axios 拦截器（鉴权/无感刷新/错误码统一）
    │   ├── auth.ts              # localStorage token / spaceId 工具
    │   └── errorCodes.ts        # 与后端错误码同步
    └── views/
        ├── Login/Login.vue
        ├── Workspace/Workspace.vue
        ├── Task/{TaskList,TaskExec}.vue
        ├── Knowledge/{Knowledge,KnowledgeDetail}.vue
        ├── Team/Team.vue
        ├── Profile/Profile.vue
        └── NotFound.vue
```

## 二、开发与构建

```bash
npm install                 # 或 pnpm install
npm run dev                 # 本地 5173，反代 /api、/sse 到 8000
npm run build:test          # 测试环境构建
npm run build:prod          # 生产构建（chunk 分包 + sourcemap off）
npm run lint                # ESLint 自动修
npm run format              # Prettier 格式化
```

环境变量可在项目根 `.env.development / .env.test / .env.production` 中区分。

## 三、6 个核心页面

| 页面 | 路径 | 关键交互 |
|------|------|----------|
| 登录注册 | /login | 表单校验 / 密码强度 / 登录态持久 / 无感刷新 |
| 工作台 | /workspace | 4 张统计卡片 / 模板快速创建 / 最近任务 |
| 任务列表 | /tasks | 分页 + 状态筛选 + 新建对话框 |
| 任务执行（核心） | /task/:id | 左时间轴 + 右流式输出区，中断/恢复/导出/复制 |
| 知识看板 | /knowledge | 分类树 + 标签 + 语义检索 + 高亮摘要 |
| 知识详情 | /knowledge/:id | Markdown 渲染 + 关联任务跳转 |
| 团队空间 | /team | 我的空间、新建、切换、成员管理 |
| 个人中心 | /profile | 资料修改 / 改密 |

## 四、Axios 拦截器亮点

- **请求拦截**：注入 `Authorization / X-Space-Id / X-Trace-Id`
- **响应拦截**：统一 `ApiResponse` 解构；业务码非 0 自动 ElMessage
- **无感刷新**：access 过期自动调 `/auth/refresh`，并发请求排队等待新 token
- **数据脱敏**：`utils/auth` 永不外泄 refresh token 给业务调用方
- **错误码映射**：`utils/errorCodes.ts` 与后端完全对齐

## 五、SSE 流式渲染

`useSSE.ts` 用 `fetch + ReadableStream` 代替原生 EventSource，因为后者不支持自定义 Header：
- 携带 `Authorization`
- 自动解析 `event:` / `data:` 双行块
- 心跳 `:heartbeat` 自动忽略
- 组件级别 `cancel()` 在 `onUnmounted` 调用释放长连接

任务执行页通过 `taskState.handleSSE` 将 token 流按 `subtask_id` 累积到 `streamedChunks`，右侧 Tab 切换即可看到每个子任务内容流式追加。

## 六、Pinia 状态

- **useUserStore**：user / spaces / currentSpaceId / login / logout / refreshMe / loadSpaces / switchSpace
- **useTaskStore**：currentTask / timeline / streamedChunks / sseEvents / handleSSE / interrupt / resume / load

## 七、路由守卫

- 非公开页面缺 access token → 跳转 `/login?redirect=xxx`
- 业务页缺 `X-Space-Id` → 跳 `/team`
- 404 自动渲染 `views/NotFound.vue`

## 八、性能优化

- 路由懒加载 `() => import(...)`
- 业务依赖 chunk 分包：`element-plus` / `vue-vendor` / `markdown`
- 代码高亮、KaTeX 仅在 `MarkdownView` 引入
- 深色模式通过 `html.dark` class 控制 CSS 变量，零额外打包

## 九、与后端契约

- 凡业务接口需 `X-Space-Id: <spaceId>` Header（由 user store 切换空间时设置）
- 写接口可附 `X-Request-Token` UUID 做幂等
- SSE 域与 API 同基址；vite dev 反代将其转发至后端，关闭 `proxy_buffering`