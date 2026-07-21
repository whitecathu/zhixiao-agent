import { createRouter, createWebHistory, RouteRecordRaw } from "vue-router";

import { getAuthToken, getSpaceId } from "@/utils/auth";

const routes: RouteRecordRaw[] = [
  {
    path: "/login",
    name: "Login",
    component: () => import("@/views/Login/Login.vue"),
    meta: { public: true, title: "登录" },
  },
  {
    path: "/",
    component: () => import("@/layouts/DefaultLayout.vue"),
    redirect: "/workspace",
    children: [
      { path: "/workspace", name: "Workspace", component: () => import("@/views/Workspace/Workspace.vue"), meta: { title: "工作台" } },
      { path: "/repositories", name: "Repositories", component: () => import("@/views/Repository/RepositoryList.vue"), meta: { title: "代码仓库" } },
      { path: "/task/:id", name: "TaskExec", component: () => import("@/views/Task/TaskExec.vue"), meta: { title: "任务执行" } },
      { path: "/tasks", name: "TaskList", component: () => import("@/views/Task/TaskList.vue"), meta: { title: "任务列表" } },
      { path: "/knowledge", name: "Knowledge", component: () => import("@/views/Knowledge/Knowledge.vue"), meta: { title: "知识看板" } },
      { path: "/knowledge/:id", name: "KnowledgeDetail", component: () => import("@/views/Knowledge/KnowledgeDetail.vue"), meta: { title: "知识详情" } },
      { path: "/workflows", name: "Workflows", component: () => import("@/views/Workflow/WorkflowStudio.vue"), meta: { title: "工作流" } },
      { path: "/agents", name: "Agents", component: () => import("@/views/Agent/AgentCatalog.vue"), meta: { title: "Agent 与工具" } },
      { path: "/models", name: "Models", component: () => import("@/views/Model/ModelOps.vue"), meta: { title: "模型与微调" } },
      { path: "/intelligence", name: "Intelligence", component: () => import("@/views/Intelligence/IntelligenceHub.vue"), meta: { title: "图谱与评测" } },
      { path: "/team", name: "Team", component: () => import("@/views/Team/Team.vue"), meta: { title: "团队" } },
      { path: "/profile", name: "Profile", component: () => import("@/views/Profile/Profile.vue"), meta: { title: "个人中心" } },
    ],
  },
  { path: "/:pathMatch(.*)*", name: "NotFound", component: () => import("@/views/NotFound.vue"), meta: { public: true } },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach((to, _from, next) => {
  document.title = (to.meta.title as string) || "智效工坊";
  if (to.meta.public) return next();
  if (!getAuthToken()) return next({ name: "Login", query: { redirect: to.fullPath } });
  // 业务页强制需要 X-Space-Id（除个人中心外）
  if (to.name !== "Profile" && !getSpaceId()) return next({ name: "Team" });
  next();
});

export default router;
