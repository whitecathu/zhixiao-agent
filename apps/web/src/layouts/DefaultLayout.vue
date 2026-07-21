<template>
  <el-container class="layout">
    <el-aside class="aside" width="244px">
      <div class="logo"><span class="logo-mark">Z</span><div><strong>智效工坊</strong><small>FULL-STACK AGENT</small></div></div>
      <el-menu :default-active="activeMenu" router class="nav">
        <div class="nav-label">总览</div>
        <el-menu-item index="/workspace"><el-icon><Odometer /></el-icon><span>工作台</span></el-menu-item>
        <div class="nav-label">工程</div>
        <el-menu-item index="/repositories"><el-icon><FolderOpened /></el-icon><span>代码仓库</span></el-menu-item>
        <el-menu-item index="/tasks"><el-icon><List /></el-icon><span>任务列表</span></el-menu-item>
        <el-menu-item index="/workflows"><el-icon><Share /></el-icon><span>工作流</span></el-menu-item>
        <div class="nav-label">智能资产</div>
        <el-menu-item index="/knowledge"><el-icon><Collection /></el-icon><span>知识看板</span></el-menu-item>
        <el-menu-item index="/agents"><el-icon><Cpu /></el-icon><span>Agent 与工具</span></el-menu-item>
        <el-menu-item index="/models"><el-icon><SetUp /></el-icon><span>模型与微调</span></el-menu-item>
        <el-menu-item index="/intelligence"><el-icon><DataAnalysis /></el-icon><span>图谱与评测</span></el-menu-item>
        <div class="nav-label">组织</div>
        <el-menu-item index="/team"><el-icon><User /></el-icon><span>团队空间</span></el-menu-item>
        <el-menu-item index="/profile"><el-icon><Setting /></el-icon><span>个人中心</span></el-menu-item>
      </el-menu>
      <div class="runner-status"><span></span><div><strong>Runner Ready</strong><small>本地隔离执行器</small></div></div>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="left">
          <span class="crumb">{{ route.meta.title }}</span><span v-if="userStore.currentSpaceId" class="space-tag">{{ currentSpaceName }}</span>
        </div>
        <div class="right">
          <el-switch v-model="isDark" inline-prompt active-text="深" inactive-text="浅" @change="toggleTheme" />
          <el-dropdown @command="onUserCmd">
            <span class="user-name">{{ userStore.user?.nickname || userStore.user?.username || '未登录' }} <el-icon><CaretBottom /></el-icon></span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile">个人中心</el-dropdown-item>
                <el-dropdown-item command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="main"><router-view v-slot="{ Component }">
        <component :is="Component" />
      </router-view></el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { useUserStore } from "@/stores/user";

const route = useRoute();
const router = useRouter();
const userStore = useUserStore();

const activeMenu = computed(() => route.path.startsWith("/task/") ? "/tasks" : route.path);
const isDark = ref(document.documentElement.classList.contains("dark"));

const currentSpaceName = computed(() =>
  userStore.spaces.find((s) => s.id === userStore.currentSpaceId)?.name || "未选择",
);

function toggleTheme(v: boolean) {
  document.documentElement.classList.toggle("dark", v);
  isDark.value = v;
}

function onUserCmd(cmd: string) {
  if (cmd === "logout") userStore.logout().then(() => router.replace("/login"));
  else if (cmd === "profile") router.push("/profile");
}
</script>

<style scoped lang="scss">
.layout { height: 100vh; }
.aside { position:relative; display:flex; flex-direction:column; background: #101612; color: #fff; border-right:1px solid #273029; }
.logo { height:72px; display:flex; align-items:center; gap:11px; padding:0 20px; border-bottom:1px solid #273029; }.logo-mark { width:32px; height:32px; display:grid; place-items:center; color:#0d1710; background:#9eef6b; font:800 18px var(--mono); transform:rotate(-3deg); }.logo strong,.logo small { display:block; }.logo small { font:9px var(--mono); letter-spacing:1.7px; color:#849188; margin-top:3px; }
.nav { flex:1; border:0; padding:10px; background:transparent; }.nav-label { padding:15px 12px 6px; color:#637069; font:10px var(--mono); letter-spacing:1.3px; text-transform:uppercase; }.nav :deep(.el-menu-item) { height:40px; color:#aeb9b1; border-radius:3px; margin:2px 0; }.nav :deep(.el-menu-item:hover) { background:#19221c; color:white; }.nav :deep(.el-menu-item.is-active) { color:#b7ff8b; background:#1d2c20; }.runner-status { display:flex; align-items:center; gap:10px; margin:12px; padding:12px; background:#161f19; border:1px solid #29352d; }.runner-status>span { width:8px;height:8px;border-radius:50%;background:#6ee7a4;box-shadow:0 0 0 5px rgba(110,231,164,.1);}.runner-status strong,.runner-status small{display:block;font-size:11px}.runner-status small{color:#718078;margin-top:3px}
.header { height:58px; display: flex; align-items: center; justify-content: space-between; padding: 0 22px; background:var(--surface); border-bottom:1px solid var(--border); }
.left { display:flex; align-items:center; gap:12px; }.crumb { font-weight:650; }.main { padding: 22px; background: var(--main-bg); overflow:auto; }
.user-name { cursor: pointer; }
.space-tag { padding: 3px 9px; color:var(--text-muted); background: var(--surface-soft); border:1px solid var(--border); border-radius: 2px; font-size:12px; }
:global(html.dark) .aside { background: #1d1e1f; }
:global(html.dark) .main { background: #141414; }
</style>
