<template>
  <section class="page-stack" v-loading="loading">
    <header class="page-heading">
      <div>
        <p class="eyebrow">OPERATIONS &amp; SLO</p>
        <h1>运行观测</h1>
        <p>从任务、队列、工具和模型四个层面定位交付风险。</p>
      </div>
      <div class="heading-actions">
        <el-select v-model="windowRange" aria-label="观测时间窗口" @change="load">
          <el-option label="最近 1 小时" value="1h" />
          <el-option label="最近 24 小时" value="24h" />
          <el-option label="最近 7 天" value="7d" />
        </el-select>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </header>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />

    <div v-if="summary" class="metric-grid" aria-live="polite">
      <article v-for="metric in metrics" :key="metric.label" class="metric-card" :class="metric.tone">
        <span>{{ metric.label }}</span>
        <strong>{{ metric.value }}</strong>
        <small>{{ metric.hint }}</small>
      </article>
    </div>

    <div v-if="summary" class="ops-grid">
      <el-card shadow="never">
        <template #header><div class="card-header"><span>实时运行面</span><small>{{ summary.window }}</small></div></template>
        <div class="run-counters">
          <div><strong>{{ summary.tasks.running }}</strong><span>执行中</span></div>
          <div><strong>{{ summary.tasks.queued }}</strong><span>等待队列</span></div>
          <div><strong>{{ summary.tasks.awaiting_approval }}</strong><span>等待审批</span></div>
          <div><strong>{{ summary.tasks.failed }}</strong><span>失败</span></div>
        </div>
        <dl class="detail-list">
          <div><dt>队列深度</dt><dd>{{ summary.queue.depth }}</dd></div>
          <div><dt>最老等待任务</dt><dd>{{ duration(summary.queue.oldest_age_seconds * 1000) }}</dd></div>
          <div><dt>工具调用</dt><dd>{{ summary.tools.invocations }}</dd></div>
          <div><dt>工具失败率</dt><dd>{{ percent(summary.tools.failure_rate) }}</dd></div>
          <div><dt>工具 p95</dt><dd>{{ duration(summary.tools.p95_duration_ms) }}</dd></div>
          <div><dt>待审批</dt><dd>{{ summary.approvals.pending }}</dd></div>
          <div><dt>审批等待 p95</dt><dd>{{ duration(summary.approvals.p95_wait_seconds * 1000) }}</dd></div>
        </dl>
      </el-card>

      <el-card shadow="never">
        <template #header>模型消耗</template>
        <el-table :data="summary.models" empty-text="当前窗口暂无模型调用">
          <el-table-column prop="provider" label="提供商" width="110" />
          <el-table-column prop="model" label="模型" min-width="150" />
          <el-table-column prop="calls" label="调用" width="80" />
          <el-table-column label="Token" width="110"><template #default="{ row }">{{ number(row.tokens) }}</template></el-table-column>
          <el-table-column label="成本" width="100"><template #default="{ row }">{{ money(row.cost_usd, 3) }}</template></el-table-column>
        </el-table>
      </el-card>
    </div>

    <el-card v-if="summary" shadow="never">
      <template #header><div class="card-header"><span>近期失败任务</span><small>点击任务编号进入证据时间线</small></div></template>
      <el-table :data="summary.recent_failures" empty-text="当前窗口没有失败任务">
        <el-table-column label="任务" min-width="220"><template #default="{ row }"><router-link :to="`/task/${row.run_id}`">#{{ row.run_id }} {{ row.title }}</router-link></template></el-table-column>
        <el-table-column prop="error" label="错误根因" min-width="360" show-overflow-tooltip />
        <el-table-column label="发生时间" width="180"><template #default="{ row }">{{ date(row.occurred_at) }}</template></el-table-column>
      </el-table>
    </el-card>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { Refresh } from "@element-plus/icons-vue";
import dayjs from "dayjs";

import { observabilityApi } from "@/api/product";
import type { ObservabilitySummary } from "@/types";

const loading = ref(false);
const error = ref("");
const windowRange = ref("24h");
const summary = ref<ObservabilitySummary | null>(null);

const metrics = computed(() => summary.value ? [
  { label: "任务成功率", value: percent(summary.value.slo.task_success_rate), hint: "已进入终态的任务", tone: summary.value.slo.task_success_rate >= 0.9 ? "good" : "warn" },
  { label: "首次测试通过率", value: percent(summary.value.slo.first_pass_rate), hint: "无需自动修复的验证", tone: summary.value.slo.first_pass_rate >= 0.75 ? "good" : "warn" },
  { label: "p95 执行耗时", value: duration(summary.value.slo.p95_run_duration_ms), hint: "任务端到端延迟", tone: "neutral" },
  { label: "错误率", value: percent(summary.value.slo.error_rate), hint: "API 与 Worker 错误", tone: summary.value.slo.error_rate <= 0.02 ? "good" : "danger" },
  { label: "模型成本", value: money(summary.value.slo.cost_usd), hint: summary.value.slo.cost_usd == null ? "Provider 用量尚未接入" : `预算 $${summary.value.slo.budget_usd.toFixed(2)}`, tone: summary.value.slo.cost_usd == null || summary.value.slo.cost_usd <= summary.value.slo.budget_usd ? "neutral" : "danger" },
] : []);

function percent(value: number) { return `${(value * 100).toFixed(1)}%`; }
function number(value: number) { return new Intl.NumberFormat("zh-CN").format(value); }
function money(value: number | null, digits = 2) { return value == null ? "—" : `$${value.toFixed(digits)}`; }
function duration(ms: number) { if (ms < 1000) return `${Math.round(ms)} ms`; if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`; return `${(ms / 60_000).toFixed(1)} min`; }
function date(value: string) { return value ? dayjs(value).format("YYYY-MM-DD HH:mm") : "—"; }

async function load() {
  loading.value = true;
  error.value = "";
  try { summary.value = await observabilityApi.summary(windowRange.value); }
  catch { error.value = "无法读取观测汇总，请确认当前空间权限及观测服务状态。"; }
  finally { loading.value = false; }
}

onMounted(load);
</script>

<style scoped lang="scss">
.heading-actions { display: flex; align-items: center; gap: 8px; }
.heading-actions .el-select { width: 150px; }
.metric-grid { display: grid; grid-template-columns: repeat(5, minmax(150px, 1fr)); gap: 12px; }
.metric-card { padding: 17px; border: 1px solid var(--border); border-top: 3px solid #859189; background: var(--surface); }
.metric-card span, .metric-card small { display: block; color: var(--text-muted); }
.metric-card strong { display: block; margin: 10px 0 6px; font: 700 clamp(22px, 3vw, 32px) var(--mono); }
.metric-card.good { border-top-color: #3b9a57; }
.metric-card.warn { border-top-color: #d89927; }
.metric-card.danger { border-top-color: #d9534f; }
.ops-grid { display: grid; grid-template-columns: minmax(320px, .8fr) minmax(480px, 1.2fr); gap: 14px; }
.run-counters { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.run-counters div { padding: 13px 8px; text-align: center; background: var(--surface-soft); border: 1px solid var(--border); }
.run-counters strong, .run-counters span { display: block; }
.run-counters strong { font: 700 24px var(--mono); }
.run-counters span { margin-top: 4px; color: var(--text-muted); font-size: 12px; }
.detail-list { margin: 14px 0 0; }
.detail-list div { display: flex; justify-content: space-between; padding: 9px 0; border-bottom: 1px solid var(--border); }
.detail-list dt { color: var(--text-muted); }
.detail-list dd { margin: 0; font-family: var(--mono); }
.card-header small { color: var(--text-muted); font-weight: 400; }
a { color: var(--brand); text-decoration: none; }
@media (max-width: 1100px) { .metric-grid { grid-template-columns: repeat(2, 1fr); } .ops-grid { grid-template-columns: 1fr; } }
@media (max-width: 620px) { .metric-grid { grid-template-columns: 1fr; } .run-counters { grid-template-columns: repeat(2, 1fr); } .heading-actions { width: 100%; } }
</style>
