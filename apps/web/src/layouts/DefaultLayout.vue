<template>
  <el-container class="layout">
    <div v-if="sidebarOpen" class="sidebar-backdrop" @click="sidebarOpen = false" />

    <el-aside class="aside" :class="{ open: sidebarOpen }" width="248px">
      <div class="logo">
        <span class="logo-mark">Z</span>
        <div>
          <strong>智效工坊</strong>
          <small>FULL-STACK AGENT</small>
        </div>
      </div>
      <el-menu :default-active="activeMenu" router class="nav" @select="sidebarOpen = false">
        <div class="nav-label">总览</div>
        <el-menu-item index="/workspace"><el-icon><Odometer /></el-icon><span>工作台</span></el-menu-item>
        <el-menu-item v-if="userStore.isSpaceAdmin" index="/observability"><el-icon><Monitoring /></el-icon><span>运行观测</span></el-menu-item>
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
      <div class="runner-status">
        <span class="runner-dot" />
        <div>
          <strong>Runner Ready</strong>
          <small>本地隔离执行器</small>
        </div>
      </div>
    </el-aside>

    <el-container class="main-shell">
      <el-header class="header">
        <div class="left">
          <el-button class="menu-toggle" text :icon="Expand" aria-label="打开导航菜单" @click="sidebarOpen = true" />
          <div class="crumb-group">
            <span class="crumb">{{ route.meta.title }}</span>
            <span v-if="parentCrumb" class="crumb-parent">{{ parentCrumb }}</span>
          </div>
          <el-dropdown v-if="userStore.spaces.length" trigger="click" @command="onSpaceSwitch">
            <button type="button" class="space-tag">
              <el-icon><OfficeBuilding /></el-icon>
              <span class="space-name">{{ currentSpaceName }}</span>
              <el-icon class="caret"><CaretBottom /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item
                  v-for="space in userStore.spaces"
                  :key="space.id"
                  :command="space.id"
                  :class="{ active: space.id === userStore.currentSpaceId }"
                >
                  {{ space.name }}
                </el-dropdown-item>
                <el-dropdown-item divided command="manage">管理空间</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
        <div class="right">
          <el-tooltip content="切换深浅色主题" placement="bottom">
            <el-switch
              v-model="isDark"
              inline-prompt
              active-text="深"
              inactive-text="浅"
              @change="toggleTheme"
            />
          </el-tooltip>
          <el-dropdown trigger="click" @command="onUserCmd">
            <button type="button" class="user-chip">
              <span class="avatar">{{ userInitials }}</span>
              <span class="user-name">{{ displayName }}</span>
              <el-icon><CaretBottom /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile">个人中心</el-dropdown-item>
                <el-dropdown-item command="onboarding">重新播放上手引导</el-dropdown-item>
                <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="main">
        <router-view v-slot="{ Component, route: viewRoute }">
          <transition name="page-fade" mode="out-in">
            <component :is="Component" :key="viewRoute.path" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
    <OnboardingGuide ref="onboarding" :space-id="userStore.currentSpaceId" />
  </el-container>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { CaretBottom, Expand, OfficeBuilding } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";

import OnboardingGuide from "@/components/onboarding/OnboardingGuide.vue";
import { useUserStore } from "@/stores/user";
import { applyTheme, isDarkTheme } from "@/utils/theme";

const route = useRoute();
const router = useRouter();
const userStore = useUserStore();

const sidebarOpen = ref(false);
const isDark = ref(isDarkTheme());
const onboarding = ref<{ replay: () => Promise<void> } | null>(null);

const activeMenu = computed(() => (route.path.startsWith("/task/") ? "/tasks" : route.path));

const parentCrumb = computed(() => {
  if (route.path.startsWith("/task/")) return "工程任务";
  if (route.path.startsWith("/knowledge/")) return "知识看板";
  return "";
});

const currentSpaceName = computed(
  () => userStore.spaces.find((s) => s.id === userStore.currentSpaceId)?.name || "选择空间",
);

const displayName = computed(
  () => userStore.user?.nickname || userStore.user?.username || "未登录",
);

const userInitials = computed(() => {
  const name = displayName.value.trim();
  if (!name || name === "未登录") return "?";
  return name.slice(0, 1).toUpperCase();
});

function toggleTheme(v: boolean) {
  applyTheme(v ? "dark" : "light");
  isDark.value = v;
}

function onSpaceSwitch(id: number | "manage") {
  if (id === "manage") {
    router.push("/team");
    return;
  }
  userStore.switchSpace(id);
  ElMessage.success("已切换工作空间");
}

function onUserCmd(cmd: string) {
  if (cmd === "logout") userStore.logout().then(() => router.replace("/login"));
  else if (cmd === "profile") router.push("/profile");
  else if (cmd === "onboarding") onboarding.value?.replay();
}
</script>

<style scoped lang="scss">
.layout {
  height: 100dvh;
  min-height: 100vh;
}

.main-shell {
  min-width: 0;
  background: var(--main-bg);
}

.aside {
  position: relative;
  display: flex;
  flex-direction: column;
  background: var(--aside-bg);
  color: #fff;
  border-right: 1px solid var(--aside-border);
  z-index: 30;
}

.logo {
  height: 64px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 var(--space-5);
  border-bottom: 1px solid var(--aside-border);
  flex-shrink: 0;
}

.logo-mark {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  color: #0d1710;
  background: var(--brand-accent);
  font: 800 17px var(--font-mono);
  border-radius: var(--radius-sm);
  transform: rotate(-3deg);
  flex-shrink: 0;
}

.logo strong,
.logo small {
  display: block;
}

.logo strong {
  font-size: var(--text-md);
  font-weight: 650;
  letter-spacing: -0.2px;
  line-height: 1.2;
}

.logo small {
  font: 9px var(--font-mono);
  letter-spacing: 1.5px;
  color: var(--aside-text-muted);
  margin-top: 3px;
}

.nav {
  flex: 1;
  border: 0;
  padding: var(--space-2) var(--space-2) var(--space-3);
  background: transparent;
  overflow-y: auto;
}

.nav-label {
  padding: var(--space-4) var(--space-3) var(--space-2);
  color: var(--aside-text-muted);
  font: 700 10px var(--font-mono);
  letter-spacing: 1.4px;
  text-transform: uppercase;
}

.nav-label:first-child {
  padding-top: var(--space-2);
}

.nav :deep(.el-menu-item) {
  height: 38px;
  color: var(--aside-text);
  border-radius: var(--radius-sm);
  margin: 1px 0;
  padding: 0 var(--space-3) !important;
  font-size: 13px;
  transition: background var(--duration-fast) ease, color var(--duration-fast) ease;
}

.nav :deep(.el-menu-item .el-icon) {
  font-size: 16px;
  margin-right: 10px;
  color: inherit;
  opacity: 0.85;
}

.nav :deep(.el-menu-item:hover) {
  background: rgba(255, 255, 255, 0.05);
  color: #fff;
}

.nav :deep(.el-menu-item.is-active) {
  color: var(--brand-on-dark);
  background: rgba(158, 239, 107, 0.1);
  font-weight: 600;
}

.nav :deep(.el-menu-item.is-active .el-icon) {
  opacity: 1;
}

.runner-status {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: var(--space-3);
  padding: var(--space-3);
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--aside-border);
  border-radius: var(--radius-sm);
  flex-shrink: 0;
}

.runner-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--status-success);
  box-shadow: 0 0 0 4px rgba(23, 167, 104, 0.15);
  animation: pulse 2s ease-in-out infinite;
  flex-shrink: 0;
}

.runner-status strong,
.runner-status small {
  display: block;
  font-size: var(--text-xs);
}

.runner-status strong {
  font-weight: 600;
  color: #d5e0d7;
}

.runner-status small {
  color: var(--aside-text-muted);
  margin-top: 2px;
}

@keyframes pulse {
  0%,
  100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.header {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-5);
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  gap: var(--space-4);
  flex-shrink: 0;
}

.left,
.right {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}

.crumb-group {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 1px;
}

.crumb {
  font-weight: 650;
  font-size: var(--text-md);
  line-height: 1.2;
  letter-spacing: -0.2px;
}

.crumb-parent {
  color: var(--text-muted);
  font-size: var(--text-xs);
  line-height: 1.2;
}

.menu-toggle {
  display: none;
}

.space-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 200px;
  height: 30px;
  padding: 0 10px;
  color: var(--text-muted);
  background: var(--surface-soft);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  cursor: pointer;
  transition:
    border-color var(--duration-fast) ease,
    color var(--duration-fast) ease,
    background var(--duration-fast) ease;

  &:hover {
    border-color: var(--brand);
    color: var(--text);
    background: var(--brand-soft);
  }

  .space-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .caret {
    font-size: 12px;
    flex-shrink: 0;
  }
}

.user-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 34px;
  padding: 3px 10px 3px 3px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface-soft);
  cursor: pointer;
  transition: border-color var(--duration-fast) ease, background var(--duration-fast) ease;

  &:hover {
    border-color: var(--border-strong);
    background: var(--surface);
  }
}

.avatar {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--brand-soft);
  color: var(--brand);
  font: 700 12px var(--font-mono);
  flex-shrink: 0;
}

.user-name {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}

.main {
  padding: var(--space-5) var(--space-6);
  background: var(--main-bg);
  overflow: auto;
}

.sidebar-backdrop {
  display: none;
}

:global(html.dark) .aside {
  background: var(--aside-bg);
}

:global(html.dark) .main-shell,
:global(html.dark) .main {
  background: var(--main-bg);
}

:global(.el-dropdown-menu__item.active) {
  color: var(--brand);
  font-weight: 600;
}

@media (max-width: 900px) {
  .menu-toggle {
    display: inline-flex;
  }

  .user-name {
    display: none;
  }

  .main {
    padding: var(--space-4);
  }

  .aside {
    position: fixed;
    inset: 0 auto 0 0;
    transform: translateX(-100%);
    transition: transform 0.2s var(--ease-out);
    box-shadow: none;
  }

  .aside.open {
    transform: translateX(0);
    box-shadow: 8px 0 24px rgba(0, 0, 0, 0.25);
  }

  .sidebar-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.45);
    z-index: 20;
  }
}

@media (prefers-reduced-motion: reduce) {
  .runner-dot {
    animation: none;
  }

  .aside {
    transition: none;
  }
}
</style>
