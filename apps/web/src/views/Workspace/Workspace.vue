<template>
  <section class="workspace page-shell">
    <div class="workspace-hero">
      <div>
        <p class="eyebrow">AGENT COMMAND CENTER</p>
        <h1>把工程目标交给可验证的执行闭环</h1>
        <p>Agent 会先理解仓库和项目指令，再计划、隔离编辑、运行测试与交付可审查的 Diff。</p>
        <div class="hero-actions">
          <el-button type="primary" size="large" @click="$router.push('/tasks?create=1')">创建工程任务</el-button>
          <el-button size="large" @click="$router.push('/repositories')">管理代码仓库</el-button>
        </div>
      </div>
      <div class="loop-visual">
        <span v-for="(step, index) in loop" :key="step" :class="{ hot: index < 3 }">
          <b>{{ String(index + 1).padStart(2, "0") }}</b>{{ step }}
        </span>
      </div>
    </div>

    <div class="cards">
      <article v-for="card in cards" :key="card.key" class="metric-card">
        <span>{{ card.title }}</span>
        <strong>{{ card.display }}</strong>
        <small>{{ card.note }}</small>
      </article>
    </div>

    <div class="dashboard-grid">
      <el-card class="recent table-chrome" shadow="never">
        <template #header>
          <div class="card-header">
            <span>最近任务</span>
            <el-button text @click="$router.push('/tasks')">查看全部 →</el-button>
          </div>
        </template>
        <el-skeleton v-if="loading" :rows="4" animated />
        <el-table v-else :data="recent" class="clickable-table" @row-click="onTaskClick">
          <el-table-column label="任务">
            <template #default="{ row }">
              <strong>{{ row.title }}</strong>
              <div class="muted">#{{ row.id }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="110">
            <template #default="{ row }">
              <el-tag :type="taskStatusTag(row.status)">{{ taskStatusText(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" width="190" />
        </el-table>
        <el-empty v-if="!loading && !recent.length" description="还没有工程任务">
          <el-button type="primary" @click="$router.push('/tasks?create=1')">创建第一个任务</el-button>
        </el-empty>
      </el-card>

      <el-card shadow="never" class="quick">
        <template #header>常用场景</template>
        <button
          v-for="template in templates"
          :key="template.title"
          class="quick-row"
          @click="startTemplate(template)"
        >
          <span>{{ template.icon }}</span>
          <div>
            <strong>{{ template.title }}</strong>
            <small>{{ template.description }}</small>
          </div>
          <b>→</b>
        </button>
      </el-card>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { statsApi } from "@/api/stats";
import { taskStatusTag, taskStatusText } from "@/utils/status";
import type { SpaceOverview, TaskItem } from "@/types";

const router = useRouter();
const loading = ref(true);
const overview = ref<SpaceOverview>({
  total_tasks: 0,
  succeeded: 0,
  tasks_last_30d: 0,
  knowledge_total: 0,
  reuse_rate: 0,
});
const recent = ref<Array<Pick<TaskItem, "id" | "title" | "status" | "created_at">>>([]);
const loop = ["探测", "计划", "实现", "验证", "复核", "交付"];
const templates = [
  { icon: "BUG", title: "修复缺陷", description: "定位根因、补回归测试并生成最小 Diff" },
  { icon: "API", title: "实现跨栈功能", description: "同步修改接口、类型、前端与集成验证" },
  { icon: "REV", title: "代码审查", description: "按风险分级输出可定位的审查结论" },
];
const cards = computed(() => [
  { key: "total", title: "累计任务", display: overview.value.total_tasks, note: "全部工程运行" },
  { key: "success", title: "成功交付", display: overview.value.succeeded, note: "通过质量门禁" },
  { key: "month", title: "30 天活跃", display: overview.value.tasks_last_30d, note: "新建任务" },
  {
    key: "knowledge",
    title: "知识资产",
    display: overview.value.knowledge_total,
    note: `复用率 ${(overview.value.reuse_rate * 100).toFixed(1)}%`,
  },
]);

function onTaskClick(row: Pick<TaskItem, "id">) {
  router.push(`/task/${row.id}`);
}

function startTemplate(template: { title: string; description: string }) {
  router.push({ path: "/tasks", query: { create: "1", title: template.title, goal: template.description } });
}

onMounted(async () => {
  loading.value = true;
  const [stats, tasks] = await Promise.allSettled([statsApi.overview(), statsApi.recentTasks()]);
  if (stats.status === "fulfilled") overview.value = stats.value;
  if (tasks.status === "fulfilled") recent.value = tasks.value as typeof recent.value;
  loading.value = false;
});
</script>

<style scoped lang="scss">
.workspace-hero {
  display: grid;
  grid-template-columns: 1.25fr 0.75fr;
  gap: var(--space-8);
  padding: var(--space-7) var(--space-7);
  color: #edf7ee;
  background:
    linear-gradient(135deg, rgba(40, 125, 60, 0.12), transparent 50%),
    #122018;
  border: 1px solid #27452f;
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.workspace-hero h1 {
  max-width: 680px;
  margin: 6px 0 12px;
  font-size: clamp(26px, 2.8vw, 34px);
  font-weight: 650;
  line-height: var(--leading-tight);
  letter-spacing: -0.9px;
}

.workspace-hero p:not(.eyebrow) {
  max-width: 640px;
  color: #9fb2a3;
  line-height: var(--leading-relaxed);
  font-size: var(--text-base);
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: var(--space-6);
}

.loop-visual {
  display: grid;
  align-content: center;
  gap: 2px;
}

.loop-visual span {
  display: flex;
  gap: 16px;
  padding: 8px 14px;
  color: #6e8073;
  border-left: 2px solid #39513f;
  font-size: 13px;
  transition: color var(--duration-fast) ease, background var(--duration-fast) ease;
}

.loop-visual span.hot {
  color: #c9f7c8;
  border-left-color: var(--brand-accent);
  background: linear-gradient(90deg, rgba(158, 239, 107, 0.1), transparent);
}

.loop-visual b {
  font: 11px var(--font-mono);
  min-width: 20px;
}

.cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-3);
}

.metric-card {
  padding: 16px 18px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  transition: border-color var(--duration-fast) ease, box-shadow var(--duration-fast) ease;
}

.metric-card:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-sm);
}

.metric-card span,
.metric-card small,
.metric-card strong {
  display: block;
}

.metric-card span,
.metric-card small {
  color: var(--text-muted);
  font-size: var(--text-xs);
}

.metric-card strong {
  margin: 8px 0 5px;
  font: 700 26px var(--font-mono);
  letter-spacing: -0.5px;
  color: var(--text);
}

.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(300px, 0.7fr);
  gap: var(--space-4);
}

.recent,
.quick {
  border-radius: var(--radius-sm);
}

.quick-row {
  width: 100%;
  display: grid;
  grid-template-columns: 42px 1fr 20px;
  gap: 11px;
  align-items: center;
  padding: 13px 4px;
  text-align: left;
  color: inherit;
  background: none;
  border: 0;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: background var(--duration-fast) ease, padding-left var(--duration-fast) ease;

  &:last-child {
    border-bottom: 0;
  }

  &:hover {
    background: var(--surface-soft);
    padding-left: 8px;
  }
}

.quick-row > span {
  color: var(--brand);
  font: 700 11px var(--font-mono);
  letter-spacing: 0.5px;
}

.quick-row strong,
.quick-row small {
  display: block;
}

.quick-row small {
  color: var(--text-muted);
  margin-top: 4px;
  font-size: var(--text-sm);
  line-height: var(--leading-snug);
}

.quick-row > b {
  color: var(--brand);
  font-weight: 500;
}

@media (max-width: 1000px) {
  .workspace-hero,
  .dashboard-grid {
    grid-template-columns: 1fr;
  }

  .cards {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 560px) {
  .cards {
    grid-template-columns: 1fr;
  }
}
</style>
