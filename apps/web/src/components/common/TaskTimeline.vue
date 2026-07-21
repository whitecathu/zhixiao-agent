<template>
  <el-timeline>
    <el-timeline-item
      v-for="(step, idx) in timeline"
      :key="step.id || idx"
      :type="statusTag(step.status)"
      :timestamp="formatTs(step)"
      placement="top"
    >
      <el-card shadow="hover" class="step-card" @click="onExpand(step.id)">
        <div class="row">
          <span class="agent">{{ step.role }} · {{ step.name }}</span>
          <el-tag size="small" :type="statusTag(step.status)">{{ statusText(step.status) }}</el-tag>
          <span class="dur">步骤 #{{ step.sequence }}</span>
        </div>
        <el-collapse-transition>
          <div v-if="expanded === step.id" class="detail">
            <div class="blk"><strong>输入</strong><pre>{{ formatData(step.input) }}</pre></div>
            <div class="blk"><strong>输出</strong><pre>{{ formatData(step.output) }}</pre></div>
            <div v-if="step.error_message" class="blk error"><strong>错误</strong><pre>{{ step.error_message }}</pre></div>
          </div>
        </el-collapse-transition>
      </el-card>
    </el-timeline-item>
  </el-timeline>
</template>

<script setup lang="ts">
import { ref } from "vue";
import type { AgentStep } from "@/types";

defineProps<{ timeline: AgentStep[] }>();

const expanded = ref<number | null>(null);
function onExpand(id?: number) { expanded.value = expanded.value === id ? null : (id ?? null); }

function statusTag(s: string) {
  return ({ pending: "info", running: "warning", succeeded: "success",
            failed: "danger", interrupted: "info" } as const)[s as "pending"] ?? "info";
}
function statusText(s: string) {
  return ({ pending: "待执行", running: "执行中", succeeded: "已完成",
            failed: "失败", interrupted: "已中断" } as const)[s as "pending"] ?? s;
}
function formatTs(step: AgentStep) {
  return step.started_at ? `${step.started_at}${step.finished_at ? " → " + step.finished_at : ""}` : "—";
}
function formatData(value?: Record<string, unknown> | null) {
  return value ? JSON.stringify(value, null, 2) : "无";
}
</script>

<style scoped lang="scss">
.step-card { cursor: pointer; }
.row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; font-size: 14px; }
.agent { font-weight: 600; }
.tool { margin-right: 4px; }
.detail { margin-top: 8px; }
.blk { margin: 6px 0; }
pre { white-space: pre-wrap; word-break: break-word; background: var(--pre-bg, #f5f5f5); padding: 8px; border-radius: 4px; }
.error pre { color: #f56c6c; }
</style>
