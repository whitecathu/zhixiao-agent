<template>
  <section v-loading="loading" class="run-page page-shell">
    <header class="run-header">
      <div>
        <button
          class="back-link"
          aria-label="返回工程任务列表"
          @click="$router.push('/tasks')"
        >
          ← 工程任务
        </button>
        <div class="title-line">
          <h1>{{ taskState.currentTask?.title || `任务 #${taskId}` }}</h1>
          <el-tag :type="statusTag(taskState.currentTask?.status)">
            {{ statusText(taskState.currentTask?.status) }}
          </el-tag>
          <span
            class="live-dot"
            :class="{ online: connected }"
            role="status"
            aria-live="polite"
            aria-atomic="true"
          >
            {{ connected ? "实时连接" : "已断开" }}
          </span>
        </div>
        <p>{{ taskState.currentTask?.prompt }}</p>
      </div>
      <div class="ops" role="toolbar" aria-label="任务运行操作">
        <el-button
          v-if="isRunning"
          type="warning"
          aria-label="中断任务运行"
          @click="onInterrupt"
        >
          中断
        </el-button>
        <el-button
          v-if="isInterrupted"
          type="primary"
          aria-label="恢复任务运行"
          @click="onResume"
        >
          恢复
        </el-button>
        <el-button aria-label="复制任务 Diff" @click="copyDiff">复制 Diff</el-button>
        <el-button
          type="success"
          plain
          :disabled="!canRequestPr"
          aria-label="请求创建拉取请求"
          @click="onRequestPr"
        >
          开 PR
        </el-button>
        <el-button aria-label="刷新任务运行详情" @click="refresh">刷新</el-button>
      </div>
    </header>

    <ExecutionGraph :events="taskState.sseEvents" />

    <el-alert
      v-for="approval in pendingApprovals"
      :key="approval.id"
      class="approval-banner"
      type="warning"
      :closable="false"
      show-icon
    >
      <template #title>
        <div class="approval-content">
          <span>
            <strong>等待 {{ approval.operation }} 审批</strong> · {{ approval.reason }}
          </span>
          <span>
            <el-button size="small" @click="decide(approval.id, 'rejected')">拒绝</el-button>
            <el-button size="small" type="primary" @click="decide(approval.id, 'approved')">
              批准并继续
            </el-button>
          </span>
        </div>
      </template>
    </el-alert>

    <div class="run-grid">
      <el-card shadow="never" class="timeline-panel">
        <template #header>
          <div class="card-header">
            <span>执行时间轴</span>
            <small>{{ taskState.timeline.length }} 步</small>
          </div>
        </template>
        <TaskTimeline :timeline="taskState.timeline" />
      </el-card>

      <el-card shadow="never" class="work-panel">
        <el-tabs v-model="tab">
          <el-tab-pane label="实时输出" name="output">
            <div v-if="subtaskKeys.length">
              <el-tabs v-model="activeSub" tab-position="left">
                <el-tab-pane v-for="key in subtaskKeys" :key="key" :label="key" :name="key">
                  <MarkdownView :content="taskState.streamedChunks[key] || ''" />
                </el-tab-pane>
              </el-tabs>
            </div>
            <el-empty v-else description="Agent 尚未产生内容输出" />
          </el-tab-pane>

          <el-tab-pane label="终端" name="terminal">
            <pre class="terminal"><code v-if="taskState.terminalLines.length">{{ taskState.terminalLines.join("\n") }}</code><span v-else class="terminal-empty">$ 等待命令执行...</span></pre>
          </el-tab-pane>

          <el-tab-pane label="Diff" name="diff">
            <div class="diff-toolbar">
              <span>{{ diffStats }}</span>
              <el-button size="small" @click="copyDiff">复制</el-button>
            </div>
            <pre class="diff-view"><code>{{ taskState.diff || "尚未生成变更" }}</code></pre>
          </el-tab-pane>

          <el-tab-pane label="测试结果" name="tests">
            <div v-for="test in taskState.tests" :key="test.id" class="test-row">
              <span class="test-state" :class="test.status">
                {{ test.status === "passed" ? "✓" : test.status === "failed" ? "×" : "•" }}
              </span>
              <div>
                <strong>{{ test.command }}</strong>
                <p>{{ test.summary || "无输出摘要" }}</p>
              </div>
              <small>{{ test.duration_ms ? `${test.duration_ms} ms` : "" }}</small>
            </div>
            <el-empty v-if="!taskState.tests.length" description="尚未运行验证" />
          </el-tab-pane>

          <el-tab-pane label="制品" name="artifacts">
            <div class="artifact-grid">
              <div v-for="artifact in taskState.artifacts" :key="artifact.id" class="artifact">
                <span>{{ artifactIcon(artifact.kind) }}</span>
                <div>
                  <strong>{{ artifact.name }}</strong>
                  <small>{{ artifact.path || artifact.kind }} · {{ artifact.size }} bytes</small>
                </div>
              </div>
            </div>
            <el-empty v-if="!taskState.artifacts.length" description="暂无任务制品" />
          </el-tab-pane>
        </el-tabs>
      </el-card>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";
import TaskTimeline from "@/components/common/TaskTimeline.vue";
import ExecutionGraph from "@/components/task/ExecutionGraph.vue";
import MarkdownView from "@/components/common/MarkdownView.vue";
import { useTaskStore } from "@/stores/task";
import { subscribeTask, type SSEStream } from "@/composables/useSSE";
import { taskStatusTag, taskStatusText } from "@/utils/status";
import type { Approval, Artifact } from "@/types";

const route = useRoute();
const taskId = Number(route.params.id);
const taskState = useTaskStore();
const loading = ref(false);
const connected = ref(false);
const tab = ref("output");
const activeSub = ref("");
let sse: SSEStream | null = null;

const subtaskKeys = computed(() => Object.keys(taskState.streamedChunks).sort());
const pendingApprovals = computed(() => taskState.approvals.filter((item) => item.status === "pending"));
const canRequestPr = computed(
  () =>
    taskState.currentTask?.status === "succeeded" &&
    taskState.currentTask?.permission_mode === "full" &&
    Boolean(taskState.diff.trim()),
);
const isRunning = computed(() =>
  ["awaiting_approval", "queued", "running"].includes(taskState.currentTask?.status || ""),
);
const isInterrupted = computed(() => taskState.currentTask?.status === "interrupted");
const diffStats = computed(() => {
  const lines = taskState.diff.split("\n");
  return `${lines.filter((line) => line.startsWith("+") && !line.startsWith("+++")).length} additions · ${lines.filter((line) => line.startsWith("-") && !line.startsWith("---")).length} deletions`;
});

watch(
  subtaskKeys,
  (keys) => {
    if (!activeSub.value && keys[0]) activeSub.value = keys[0];
  },
  { immediate: true },
);

function statusTag(status?: string) {
  return taskStatusTag(status);
}
function statusText(status?: string) {
  return taskStatusText(status);
}
function artifactIcon(kind: Artifact["kind"]) {
  return (
    {
      diff: "±",
      test_report: "✓",
      log: ">_",
      dataset: "▦",
      adapter: "◎",
      report: "▤",
      other: "◇",
    } as const
  )[kind];
}
async function refresh() {
  loading.value = true;
  try {
    await Promise.all([taskState.load(taskId), taskState.loadRunDetails(taskId)]);
  } finally {
    loading.value = false;
  }
}
async function decide(id: number, decision: Approval["status"]) {
  if (decision === "pending") return;
  await taskState.decideApproval(id, decision);
  ElMessage.success(decision === "approved" ? "已批准，任务将继续执行" : "已拒绝操作");
}
async function onInterrupt() {
  await taskState.interrupt(taskId);
  ElMessage.warning("已请求安全中断");
  await refresh();
}
async function onResume() {
  await taskState.resume(taskId);
  ElMessage.success("任务已恢复");
  await refresh();
}
async function copyDiff() {
  await navigator.clipboard.writeText(taskState.diff);
  ElMessage.success("Diff 已复制");
}
async function onRequestPr() {
  const pending = pendingApprovals.value.find((item) => item.operation === "git_publish");
  if (pending) {
    ElMessage.info("已有待处理的 PR 发布审批");
    return;
  }
  if (!canRequestPr.value) {
    ElMessage.warning("开 PR 要求 full 权限、任务成功且已生成 Diff");
    return;
  }
  await taskState.requestApproval(taskId, "git_publish");
  ElMessage.success("已提交独立的 git_publish 审批请求");
}

onMounted(async () => {
  taskState.reset();
  await refresh();
  sse = subscribeTask(
    taskId,
    {
      onEvent: (payload) => {
        connected.value = true;
        taskState.handleSSE(payload);
        if (["artifact", "approval", "task_end"].includes(payload.event)) {
          taskState.loadRunDetails(taskId);
        }
      },
      onClose: () => {
        connected.value = false;
      },
      onError: () => {
        connected.value = false;
      },
    },
    { lastEventId: taskState.lastEventId, reconnect: true },
  );
});

onUnmounted(() => sse?.cancel());
</script>

<style scoped lang="scss">
.run-page {
  min-width: 0;
  max-width: none;
}

.run-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-6);
}

.run-header h1 {
  margin: 6px 0;
  font-size: var(--text-2xl);
  font-weight: 650;
  letter-spacing: -0.5px;
  line-height: var(--leading-tight);
}

.run-header p {
  margin: 0;
  color: var(--text-muted);
  max-width: 780px;
  font-size: var(--text-base);
  line-height: var(--leading-snug);
}

.back-link {
  border: 0;
  background: none;
  color: var(--brand);
  cursor: pointer;
  padding: 0;
  font-size: var(--text-sm);
  font-weight: 500;

  &:hover {
    color: var(--brand-hover);
  }
}

.title-line,
.ops,
.approval-content,
.card-header,
.diff-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.title-line {
  flex-wrap: wrap;
}

.approval-content,
.card-header,
.diff-toolbar {
  justify-content: space-between;
  width: 100%;
}

.card-header small {
  color: var(--text-muted);
  font: var(--text-xs) var(--font-mono);
}

.diff-toolbar span {
  color: var(--text-muted);
  font: var(--text-sm) var(--font-mono);
}

.live-dot {
  font-size: var(--text-sm);
  color: var(--text-muted);
}

.live-dot::before {
  content: "";
  display: inline-block;
  width: 7px;
  height: 7px;
  margin-right: 6px;
  border-radius: 50%;
  background: var(--status-idle);
}

.live-dot.online::before {
  background: var(--status-success);
  box-shadow: 0 0 0 4px rgba(23, 167, 104, 0.12);
}

.approval-banner {
  margin-bottom: 0;
}

.run-grid {
  display: grid;
  grid-template-columns: minmax(320px, 36%) minmax(0, 1fr);
  gap: var(--space-4);
  min-height: 600px;
}

.timeline-panel,
.work-panel {
  height: calc(100vh - 430px);
  min-height: 480px;
  overflow: auto;
  border-radius: var(--radius-sm);
}

.terminal,
.diff-view {
  min-height: 480px;
  margin: 0;
  padding: 18px;
  overflow: auto;
  border-radius: var(--radius-sm);
  font: 13px / 1.65 var(--font-mono);
}

.terminal {
  color: #bbf7d0;
  background: var(--surface-sunken, #101512);
  border: 1px solid var(--border);
}

.terminal-empty {
  color: #6f8075;
}

.diff-view {
  background: #11151a;
  color: #d8dee9;
  border: 1px solid var(--border);
}

.test-row {
  display: grid;
  grid-template-columns: 32px 1fr auto;
  gap: var(--space-3);
  align-items: start;
  padding: 14px 4px;
  border-bottom: 1px solid var(--border);
}

.test-row p {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-size: var(--text-sm);
}

.test-state {
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--surface-soft);
  font-size: 12px;
}

.test-state.passed {
  color: var(--status-success);
  background: var(--status-success-soft);
}

.test-state.failed {
  color: var(--status-danger);
  background: var(--status-danger-soft);
}

.artifact-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.artifact {
  display: flex;
  gap: var(--space-3);
  align-items: center;
  color: inherit;
  text-decoration: none;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 14px;
  background: var(--surface-soft);
  transition: border-color var(--duration-fast) ease;

  &:hover {
    border-color: var(--border-strong);
  }
}

.artifact > span {
  font: 20px var(--font-mono);
  color: var(--brand);
}

.artifact small,
.artifact strong {
  display: block;
}

.artifact small {
  color: var(--text-muted);
  margin-top: 4px;
  font-size: var(--text-xs);
}

@media (max-width: 1000px) {
  .run-header {
    display: block;
  }

  .ops {
    margin-top: var(--space-4);
  }

  .run-grid {
    grid-template-columns: 1fr;
  }

  .timeline-panel,
  .work-panel {
    height: auto;
    min-height: 420px;
  }

  .artifact-grid {
    grid-template-columns: 1fr;
  }
}
</style>
