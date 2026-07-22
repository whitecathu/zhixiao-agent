<template>
  <section v-loading="loading" class="run-page">
    <header class="run-header">
      <div><button class="back-link" @click="$router.push('/tasks')">← 工程任务</button><div class="title-line"><h1>{{ taskState.currentTask?.title || `任务 #${taskId}` }}</h1><el-tag :type="statusTag(taskState.currentTask?.status)">{{ statusText(taskState.currentTask?.status) }}</el-tag><span class="live-dot" :class="{ online: connected }">{{ connected ? '实时连接' : '已断开' }}</span></div><p>{{ taskState.currentTask?.prompt }}</p></div>
      <div class="ops"><el-button v-if="isRunning" type="warning" @click="onInterrupt">中断</el-button><el-button v-if="isInterrupted" type="primary" @click="onResume">恢复</el-button><el-button @click="copyDiff">复制 Diff</el-button><el-button @click="refresh">刷新</el-button></div>
    </header>

    <div class="run-strip"><div v-for="stage in stages" :key="stage.key" class="run-stage" :class="stageClass(stage.key)"><span>{{ stage.index }}</span><div><strong>{{ stage.label }}</strong><small>{{ stage.hint }}</small></div></div></div>

    <el-alert v-for="approval in pendingApprovals" :key="approval.id" class="approval-banner" type="warning" :closable="false" show-icon><template #title><div class="approval-content"><span><strong>等待 {{ approval.operation }} 审批</strong> · {{ approval.reason }}</span><span><el-button size="small" @click="decide(approval.id, 'rejected')">拒绝</el-button><el-button size="small" type="primary" @click="decide(approval.id, 'approved')">批准并继续</el-button></span></div></template></el-alert>

    <div class="run-grid">
      <el-card shadow="never" class="timeline-panel"><template #header><div class="card-header"><span>执行时间轴</span><small>{{ taskState.timeline.length }} 步</small></div></template><TaskTimeline :timeline="taskState.timeline" /></el-card>
      <el-card shadow="never" class="work-panel"><el-tabs v-model="tab">
        <el-tab-pane label="实时输出" name="output"><div v-if="subtaskKeys.length"><el-tabs v-model="activeSub" tab-position="left"><el-tab-pane v-for="key in subtaskKeys" :key="key" :label="key" :name="key"><MarkdownView :content="taskState.streamedChunks[key] || ''" /></el-tab-pane></el-tabs></div><el-empty v-else description="Agent 尚未产生内容输出" /></el-tab-pane>
        <el-tab-pane label="终端" name="terminal"><pre class="terminal"><code v-if="taskState.terminalLines.length">{{ taskState.terminalLines.join('\n') }}</code><span v-else class="terminal-empty">$ 等待命令执行...</span></pre></el-tab-pane>
        <el-tab-pane label="Diff" name="diff"><div class="diff-toolbar"><span>{{ diffStats }}</span><el-button size="small" @click="copyDiff">复制</el-button></div><pre class="diff-view"><code>{{ taskState.diff || '尚未生成变更' }}</code></pre></el-tab-pane>
        <el-tab-pane label="测试结果" name="tests"><div v-for="test in taskState.tests" :key="test.id" class="test-row"><span class="test-state" :class="test.status">{{ test.status === 'passed' ? '✓' : test.status === 'failed' ? '×' : '•' }}</span><div><strong>{{ test.command }}</strong><p>{{ test.summary || '无输出摘要' }}</p></div><small>{{ test.duration_ms ? `${test.duration_ms} ms` : '' }}</small></div><el-empty v-if="!taskState.tests.length" description="尚未运行验证" /></el-tab-pane>
        <el-tab-pane label="制品" name="artifacts"><div class="artifact-grid"><div v-for="artifact in taskState.artifacts" :key="artifact.id" class="artifact"><span>{{ artifactIcon(artifact.kind) }}</span><div><strong>{{ artifact.name }}</strong><small>{{ artifact.path || artifact.kind }} · {{ artifact.size }} bytes</small></div></div></div><el-empty v-if="!taskState.artifacts.length" description="暂无任务制品" /></el-tab-pane>
      </el-tabs></el-card>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";
import TaskTimeline from "@/components/common/TaskTimeline.vue";
import MarkdownView from "@/components/common/MarkdownView.vue";
import { useTaskStore } from "@/stores/task";
import { subscribeTask, type SSEStream } from "@/composables/useSSE";
import { taskStatusTag, taskStatusText } from "@/utils/status";
import type { Approval, Artifact } from "@/types";

const route = useRoute(); const taskId = Number(route.params.id); const taskState = useTaskStore(); const loading = ref(false); const connected = ref(false); const tab = ref("output"); const activeSub = ref(""); let sse: SSEStream | null = null;
const stages = [{ key: "planning", index: "01", label: "计划", hint: "探测与拆解" }, { key: "running", index: "02", label: "实现", hint: "隔离编辑" }, { key: "verifying", index: "03", label: "验证", hint: "测试与修复" }, { key: "reviewing", index: "04", label: "复核", hint: "质量门禁" }, { key: "succeeded", index: "05", label: "交付", hint: "Diff 与知识" }] as const;
const subtaskKeys = computed(() => Object.keys(taskState.streamedChunks).sort());
const pendingApprovals = computed(() => taskState.approvals.filter((item) => item.status === "pending"));
const isRunning = computed(() => ["awaiting_approval", "queued", "running"].includes(taskState.currentTask?.status || ""));
const isInterrupted = computed(() => taskState.currentTask?.status === "interrupted");
const diffStats = computed(() => { const lines = taskState.diff.split("\n"); return `${lines.filter((line) => line.startsWith("+") && !line.startsWith("+++")).length} additions · ${lines.filter((line) => line.startsWith("-") && !line.startsWith("---")).length} deletions`; });
watch(subtaskKeys, (keys) => { if (!activeSub.value && keys[0]) activeSub.value = keys[0]; }, { immediate: true });

function stageClass(stage: string) {
  const current = taskState.currentTask?.status || "awaiting_approval";
  const progress = current === "succeeded" ? 5 : current === "running" ? 1 : 0;
  const stageIndex = stages.findIndex((item) => item.key === stage);
  return { active: stageIndex === progress, done: current === "succeeded" || stageIndex < progress };
}
function statusTag(status?: string) { return taskStatusTag(status); }
function statusText(status?: string) { return taskStatusText(status); }
function artifactIcon(kind: Artifact["kind"]) { return ({ diff: "±", test_report: "✓", log: ">_", dataset: "▦", adapter: "◎", report: "▤", other: "◇" } as const)[kind]; }
async function refresh() { loading.value = true; try { await Promise.all([taskState.load(taskId), taskState.loadRunDetails(taskId)]); } finally { loading.value = false; } }
async function decide(id: number, decision: Approval["status"]) { if (decision === "pending") return; await taskState.decideApproval(id, decision); ElMessage.success(decision === "approved" ? "已批准，任务将继续执行" : "已拒绝操作"); }
async function onInterrupt() { await taskState.interrupt(taskId); ElMessage.warning("已请求安全中断"); await refresh(); }
async function onResume() { await taskState.resume(taskId); ElMessage.success("任务已恢复"); await refresh(); }
async function copyDiff() { await navigator.clipboard.writeText(taskState.diff); ElMessage.success("Diff 已复制"); }
onMounted(async () => { taskState.reset(); await refresh(); sse = subscribeTask(taskId, { onEvent: (payload) => { connected.value = true; taskState.handleSSE(payload); if (["artifact", "approval", "task_end"].includes(payload.event)) taskState.loadRunDetails(taskId); }, onClose: () => { connected.value = false; }, onError: () => { connected.value = false; } }, { lastEventId: taskState.lastEventId, reconnect: true }); });
onUnmounted(() => sse?.cancel());
</script>

<style scoped lang="scss">
.run-page { min-width: 0; }.run-header { display:flex; align-items:flex-start; justify-content:space-between; gap:24px; margin-bottom:18px; }.run-header h1 { margin:6px 0; font-size:27px; }.run-header p { margin:0; color:var(--text-muted); max-width:780px; }.back-link { border:0; background:none; color:var(--brand); cursor:pointer; padding:0; }.title-line,.ops,.approval-content,.card-header,.diff-toolbar { display:flex; align-items:center; gap:12px; }.approval-content,.card-header,.diff-toolbar { justify-content:space-between; width:100%; }.live-dot { font-size:12px; color:var(--text-muted); }.live-dot::before { content:""; display:inline-block; width:7px; height:7px; margin-right:6px; border-radius:50%; background:#88919d; }.live-dot.online::before { background:#2ed184; box-shadow:0 0 0 4px rgba(46,209,132,.12); }.run-strip { display:grid; grid-template-columns:repeat(5,1fr); border:1px solid var(--border); background:var(--surface); margin-bottom:14px; }.run-stage { display:flex; gap:10px; padding:14px 16px; opacity:.48; border-right:1px solid var(--border); }.run-stage:last-child { border:0; }.run-stage>span { font-family:var(--mono); color:var(--text-muted); }.run-stage strong,.run-stage small { display:block; }.run-stage small { color:var(--text-muted); margin-top:2px; }.run-stage.active { opacity:1; background:var(--brand-soft); }.run-stage.done { opacity:1; }.run-stage.done>span { color:#17a768; }.approval-banner { margin-bottom:14px; }.run-grid { display:grid; grid-template-columns:minmax(320px, 36%) minmax(0, 1fr); gap:14px; min-height:600px; }.timeline-panel,.work-panel { height:calc(100vh - 310px); min-height:560px; overflow:auto; }.terminal,.diff-view { min-height:480px; margin:0; padding:18px; overflow:auto; border-radius:2px; font:13px/1.65 var(--mono); }.terminal { color:#bbf7d0; background:#101512; }.terminal-empty { color:#6f8075; }.diff-view { background:#11151a; color:#d8dee9; }.test-row { display:grid; grid-template-columns:32px 1fr auto; gap:12px; align-items:start; padding:14px 4px; border-bottom:1px solid var(--border); }.test-row p { margin:4px 0 0; color:var(--text-muted); }.test-state { width:24px; height:24px; display:grid; place-items:center; border-radius:50%; background:var(--surface-soft); }.test-state.passed { color:#17a768; }.test-state.failed { color:#e34d59; }.artifact-grid { display:grid; grid-template-columns:repeat(2, minmax(0,1fr)); gap:10px; }.artifact { display:flex; gap:12px; align-items:center; color:inherit; text-decoration:none; border:1px solid var(--border); padding:14px; }.artifact>span { font:20px var(--mono); color:var(--brand); }.artifact small,.artifact strong { display:block; }.artifact small { color:var(--text-muted); margin-top:4px; }
@media(max-width:1000px){.run-header{display:block}.ops{margin-top:14px}.run-strip{overflow:auto;grid-template-columns:repeat(5,170px)}.run-grid{grid-template-columns:1fr}.timeline-panel,.work-panel{height:auto;min-height:420px}}
</style>
