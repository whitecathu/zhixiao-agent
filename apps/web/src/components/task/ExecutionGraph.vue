<template>
  <section
    class="execution-graph"
    role="region"
    aria-labelledby="execution-graph-title"
  >
    <div class="graph-meta">
      <div>
        <strong id="execution-graph-title">实时执行图</strong>
        <small aria-live="polite" aria-atomic="true">{{ detail }}</small>
      </div>
      <div class="legend" aria-label="执行状态图例">
        <span class="lg idle">待执行</span>
        <span class="lg waiting">等待</span>
        <span class="lg running">进行中</span>
        <span class="lg succeeded">完成</span>
        <span class="lg failed">失败</span>
      </div>
    </div>
    <div class="flow-shell" role="group" aria-label="任务执行阶段">
      <VueFlow
        v-model:nodes="nodes"
        v-model:edges="edges"
        :nodes-draggable="false"
        :nodes-connectable="false"
        :elements-selectable="false"
        :min-zoom="0.4"
        :max-zoom="1.4"
        fit-view-on-init
        :default-viewport="{ zoom: 0.85, x: 20, y: 10 }"
      >
        <Background pattern-color="var(--border-strong)" :gap="18" />
        <Controls position="bottom-right" :show-interactive="false" />
        <template #node-default="{ data }">
          <article
            class="exec-node"
            :class="[`status-${data.status || 'idle'}`, { active: data.active }]"
            :aria-label="`${data.label}，状态：${statusLabel(data.status)}`"
            :aria-current="data.active ? 'step' : undefined"
          >
            <span>{{ data.id }}</span>
            <strong>{{ data.label }}</strong>
            <small class="node-hint">{{ data.hint }}</small>
            <small class="status-text">状态：{{ statusLabel(data.status) }}</small>
          </article>
        </template>
      </VueFlow>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, shallowRef, watch } from "vue";
import { Background } from "@vue-flow/background";
import { Controls } from "@vue-flow/controls";
import { VueFlow } from "@vue-flow/core";
import type { Edge, Node } from "@vue-flow/core";
import "@vue-flow/core/dist/style.css";
import "@vue-flow/core/dist/theme-default.css";
import "@vue-flow/controls/dist/style.css";

import type { SSEPayload } from "@/types";
import { designTokens } from "@/utils/theme";
import {
  DEFAULT_EXECUTION_EDGES,
  deriveExecutionGraph,
  layoutDefaultNodes,
} from "@/utils/executionGraph";

const props = defineProps<{
  events: Array<Pick<SSEPayload, "event" | "data">>;
}>();

const nodes = shallowRef<Node[]>([]);
const edges = shallowRef<Edge[]>([]);

const snapshot = computed(() => deriveExecutionGraph(props.events));
const detail = computed(() => snapshot.value.detail);
const STATUS_LABELS: Record<string, string> = {
  idle: "待执行",
  waiting: "等待",
  running: "进行中",
  succeeded: "完成",
  failed: "失败",
};

function statusLabel(status: unknown): string {
  return typeof status === "string" && STATUS_LABELS[status]
    ? STATUS_LABELS[status]
    : STATUS_LABELS.idle;
}

const EDGE = {
  idle: "#9aae9d",
  active: designTokens.status.running,
  repair: designTokens.status.warning,
} as const;

function syncGraph() {
  const { statuses, activeNodeId } = snapshot.value;
  nodes.value = layoutDefaultNodes(statuses, activeNodeId).map((node) => ({
    id: node.id,
    position: node.position,
    data: node.data,
    draggable: false,
    selectable: false,
  }));
  edges.value = DEFAULT_EXECUTION_EDGES.map((edge) => {
    const towardActive = edge.target === activeNodeId;
    const bothDone =
      (statuses[edge.source] === "succeeded" || statuses[edge.source] === "failed") &&
      statuses[edge.target] !== "idle";
    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      animated: towardActive || (edge.kind === "repair" && statuses.repair === "running"),
      label: edge.kind === "repair" ? "repair" : undefined,
      style: {
        stroke:
          bothDone || towardActive
            ? edge.kind === "repair"
              ? EDGE.repair
              : EDGE.active
            : EDGE.idle,
        strokeWidth: towardActive ? 2.5 : 1.5,
      },
    };
  });
}

watch(() => props.events, syncGraph, { deep: true, immediate: true });
</script>

<style scoped lang="scss">
.execution-graph {
  border: 1px solid var(--border);
  background: var(--surface);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.graph-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--border);
  background: var(--surface-soft);
}

.graph-meta strong,
.graph-meta small {
  display: block;
}

.graph-meta strong {
  font-size: var(--text-base);
  font-weight: 650;
}

.graph-meta small {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: var(--text-sm);
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: var(--text-sm);
  color: var(--text-muted);
}

.lg::before {
  content: "";
  display: inline-block;
  width: 8px;
  height: 8px;
  margin-right: 5px;
  border-radius: 50%;
  background: var(--status-idle);
}

.lg.waiting::before {
  background: var(--status-warning);
}

.lg.running::before {
  background: var(--status-running);
}

.lg.succeeded::before {
  background: var(--status-success);
}

.lg.failed::before {
  background: var(--status-danger);
}

.flow-shell {
  height: 280px;
  background: var(--surface-soft);
}

.exec-node {
  width: 128px;
  min-height: 72px;
  padding: 10px 11px;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  box-shadow: 2px 2px 0 rgba(77, 115, 84, 0.1);
  opacity: 0.55;
  transition: border-color var(--duration-fast) ease, opacity var(--duration-fast) ease;
}

.exec-node span,
.exec-node strong,
.exec-node small {
  display: block;
}

.exec-node span {
  color: var(--brand);
  font: 700 9px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.6px;
}

.exec-node strong {
  margin: 6px 0 3px;
  font-size: 13px;
  font-weight: 650;
}

.exec-node small {
  color: var(--text-muted);
  font-size: var(--text-xs);
  line-height: 1.35;
}

.exec-node .status-text {
  margin-top: 5px;
  color: var(--text);
  font-weight: 600;
}

.exec-node.status-waiting,
.exec-node.status-running,
.exec-node.status-succeeded,
.exec-node.status-failed {
  opacity: 1;
}

.exec-node.status-waiting {
  border-color: var(--status-warning);
  background: var(--status-warning-soft);
  box-shadow: 2px 2px 0 rgba(196, 125, 14, 0.16);
}

.exec-node.status-running,
.exec-node.active {
  border-color: var(--status-running);
  background: var(--status-running-soft);
  box-shadow: 2px 2px 0 rgba(45, 138, 114, 0.18);
}

.exec-node.status-succeeded {
  border-color: var(--status-success);
  background: var(--status-success-soft);
}

.exec-node.status-failed {
  border-color: var(--status-danger);
  background: var(--status-danger-soft);
  box-shadow: 2px 2px 0 rgba(217, 83, 79, 0.16);
}

:deep(.vue-flow__node) {
  border: 0;
  background: transparent;
  padding: 0;
  box-shadow: none;
}

:deep(.vue-flow__controls) {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}

@media (max-width: 1000px) {
  .graph-meta {
    flex-direction: column;
    align-items: flex-start;
  }

  .flow-shell {
    height: 240px;
  }
}
</style>
