<template>
  <section class="page-stack">
    <header class="page-heading">
      <div><p class="eyebrow">ORCHESTRATION</p><h1>工作流画布</h1><p>拖拽角色、连接条件分支，并把发布版本固定到任务运行。</p></div>
      <div class="heading-actions"><el-button @click="newWorkflow">新建草稿</el-button><el-button :disabled="!selected?.id" :loading="publishing" type="primary" @click="publish">发布当前版本</el-button></div>
    </header>

    <div class="studio-grid workflow-studio-grid">
      <el-card shadow="never" class="side-list">
        <template #header><div class="card-header"><span>版本历史</span><el-button text size="small" @click="load">刷新</el-button></div></template>
        <button v-for="item in workflows" :key="item.id" class="select-row" :class="{ active: selected?.id === item.id }" @click="select(item)">
          <span><strong>{{ item.name }}</strong><small>v{{ item.version }} · {{ item.definition.nodes.length }} 节点</small></span>
          <el-tag size="small" :type="item.status === 'published' || item.enabled ? 'success' : 'info'">{{ item.status === 'published' || item.enabled ? '已发布' : '草稿' }}</el-tag>
        </button>
        <el-empty v-if="!workflows.length" description="暂无工作流" />

        <div class="palette" aria-label="可拖拽角色节点">
          <strong>角色节点</strong><small>拖入右侧画布</small>
          <button v-for="role in roles" :key="role" draggable="true" @dragstart="dragRole($event, role)"><span>{{ role.slice(0, 1).toUpperCase() }}</span>{{ role }}</button>
        </div>
      </el-card>

      <div class="editor-stack">
        <el-card shadow="never" class="canvas-card">
          <template #header>
            <div class="canvas-toolbar">
              <el-input v-if="selected" v-model="selected.name" aria-label="工作流名称" class="workflow-name" />
              <div>
                <el-button size="small" @click="autoLayout">自动布局</el-button>
                <el-button size="small" :disabled="!selected" :loading="saving" type="primary" @click="saveVersion">保存新版本</el-button>
              </div>
            </div>
          </template>
          <div v-if="selected" class="flow-shell" @dragover.prevent @drop="dropRole">
            <VueFlow
              v-model:nodes="nodes"
              v-model:edges="edges"
              :min-zoom="0.35"
              :max-zoom="1.8"
              fit-view-on-init
              @connect="connect"
              @node-click="selectNode"
              @node-drag-stop="syncDsl"
              @edge-click="selectEdge"
              @pane-click="clearSelection"
            >
              <Background pattern-color="#b9c6bb" :gap="18" />
              <Controls position="bottom-right" />
              <template #node-default="{ data }">
                <Handle type="target" :position="Position.Left" />
                <article class="workflow-node" :class="[`status-${data.status || 'idle'}`]">
                  <span>{{ data.role }}</span><strong>{{ data.label }}</strong>
                  <small>{{ data.approval_required ? '需要审批' : `重试 ${data.retry_limit || 0} 次` }}</small>
                </article>
                <Handle type="source" :position="Position.Right" />
              </template>
            </VueFlow>
          </div>
          <el-empty v-else description="选择或新建工作流" />
        </el-card>

        <el-card v-if="selected" shadow="never">
          <el-tabs v-model="editorTab">
            <el-tab-pane label="属性" name="properties">
              <div v-if="activeNode" class="property-grid">
                <el-form label-position="top">
                  <el-form-item label="节点名称"><el-input :model-value="String(activeNode.data.label || '')" @update:model-value="updateNode('label', $event)" /></el-form-item>
                  <el-form-item label="角色"><el-select :model-value="String(activeNode.data.role || '')" @update:model-value="updateNode('role', $event)"><el-option v-for="role in roles" :key="role" :label="role" :value="role" /></el-select></el-form-item>
                  <el-form-item label="工具白名单（逗号分隔）"><el-input :model-value="toolsText" @update:model-value="updateTools" /></el-form-item>
                </el-form>
                <el-form label-position="top">
                  <el-form-item label="失败重试"><el-input-number :model-value="Number(activeNode.data.retry_limit || 0)" :min="0" :max="5" @update:model-value="updateNode('retry_limit', $event || 0)" /></el-form-item>
                  <el-form-item label="执行前审批"><el-switch :model-value="Boolean(activeNode.data.approval_required)" @update:model-value="updateNode('approval_required', $event)" /></el-form-item>
                  <el-button type="danger" plain @click="removeActiveNode">删除节点</el-button>
                </el-form>
              </div>
              <el-form v-else-if="activeEdge" label-position="top" class="edge-properties"><el-form-item label="路由条件"><el-select :model-value="String(activeEdge.label || 'success')" @update:model-value="updateEdgeCondition"><el-option label="成功" value="success"/><el-option label="失败" value="failure"/><el-option label="始终" value="always"/></el-select></el-form-item><el-button type="danger" plain @click="removeActiveEdge">删除连线</el-button></el-form>
              <el-empty v-else description="选择节点或连线编辑属性" :image-size="70" />
            </el-tab-pane>
            <el-tab-pane label="JSON DSL" name="dsl"><el-alert v-if="dslError" :title="dslError" type="error" :closable="false"/><el-input v-model="dsl" type="textarea" :rows="14" class="mono-input" aria-label="工作流 JSON DSL" @change="applyDsl" /></el-tab-pane>
            <el-tab-pane label="运行回放" name="replay">
              <div class="replay-toolbar"><el-input-number v-model="replayRunId" :min="1" controls-position="right" aria-label="任务运行编号"/><el-button :loading="replaying" @click="replay">加载运行</el-button><span v-if="replayVersion">运行使用 v{{ replayVersion }}</span></div>
              <el-timeline v-if="replaySteps.length"><el-timeline-item v-for="step in replaySteps" :key="step.id" :type="timelineType(step.status)" :timestamp="`#${step.sequence}`"><strong>{{ step.name || nodeLabel(step.role) }}</strong><p>{{ step.error_message || replaySummary(step.output) || step.status }}</p></el-timeline-item></el-timeline>
              <el-empty v-else description="输入任务运行编号回放节点状态" :image-size="70"/>
            </el-tab-pane>
          </el-tabs>
        </el-card>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, shallowRef, watch } from "vue";
import { ElMessage } from "element-plus";
import { Background } from "@vue-flow/background";
import { Controls } from "@vue-flow/controls";
import { Handle, Position, VueFlow, useVueFlow } from "@vue-flow/core";
import type { Connection, Edge, Node, NodeMouseEvent } from "@vue-flow/core";
import "@vue-flow/core/dist/style.css";
import "@vue-flow/core/dist/theme-default.css";
import "@vue-flow/controls/dist/style.css";

import { workflowApi } from "@/api/agent";
import type { WorkflowDefinition, WorkflowEdgeDefinition, WorkflowNodeDefinition, WorkflowReplay } from "@/types";

const roles = ["planner", "explorer", "implementer", "tester", "reviewer", "knowledge"];
const workflows = ref<WorkflowDefinition[]>([]);
const selected = ref<WorkflowDefinition | null>(null);
const nodes = shallowRef<Node[]>([]);
const edges = shallowRef<Edge[]>([]);
const activeNodeId = ref<string | null>(null);
const activeEdgeId = ref<string | null>(null);
const editorTab = ref("properties");
const dsl = ref("");
const dslError = ref("");
const saving = ref(false);
const publishing = ref(false);
const replaying = ref(false);
const replayRunId = ref<number>();
const replayVersion = ref<number | null>(null);
const replaySteps = ref<WorkflowReplay["steps"]>([]);
const syncing = ref(false);
const { addEdges, fitView, screenToFlowCoordinate } = useVueFlow();

const activeNode = computed<Node | null>(() => nodes.value.find((node) => node.id === activeNodeId.value) ?? null);
const activeEdge = computed<Edge | null>(() => edges.value.find((edge) => edge.id === activeEdgeId.value) ?? null);
const toolsText = computed(() => Array.isArray(activeNode.value?.data.tool_allowlist) ? activeNode.value?.data.tool_allowlist.join(", ") : "");

function toCanvas(definition: WorkflowDefinition["definition"]) {
  nodes.value = definition.nodes.map((node, index) => ({ id: node.id, position: node.position || { x: index * 210, y: index % 2 * 120 }, data: { ...node } }));
  edges.value = definition.edges.map((edge, index) => ({ id: edge.id || `e-${edge.source}-${edge.target}-${index}`, source: edge.source, target: edge.target, label: edge.condition || "success", animated: edge.condition !== "failure" }));
}
function fromCanvas(): WorkflowDefinition["definition"] {
  return {
    nodes: nodes.value.map((node) => ({ id: node.id, role: String(node.data.role), label: String(node.data.label), position: { ...node.position }, tool_allowlist: Array.isArray(node.data.tool_allowlist) ? node.data.tool_allowlist : [], retry_limit: Number(node.data.retry_limit || 0), approval_required: Boolean(node.data.approval_required) })),
    edges: edges.value.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target, condition: String(edge.label || "success") })),
  };
}
function syncDsl() { if (syncing.value || !selected.value) return; selected.value.definition = fromCanvas(); dsl.value = JSON.stringify(selected.value.definition, null, 2); }
function select(item: WorkflowDefinition) { selected.value = structuredClone(item); toCanvas(selected.value.definition); dsl.value = JSON.stringify(selected.value.definition, null, 2); clearSelection(); nextTick(() => fitView({ padding: .2 })); }
function newWorkflow() {
  const starter: WorkflowDefinition = { id: 0, space_id: 0, name: "工程 Agent 标准流", version: 1, enabled: false, status: "draft", definition: { nodes: ["planner", "explorer", "implementer", "tester", "reviewer", "knowledge"].map((role, index) => ({ id: role, role, label: role[0].toUpperCase() + role.slice(1), position: { x: index * 190, y: 80 }, retry_limit: role === "tester" ? 2 : 0, approval_required: role === "planner" })), edges: roles.slice(0, -1).map((role, index) => ({ source: role, target: roles[index + 1], condition: "success" })) }, created_at: "", updated_at: "" };
  select(starter);
}
function connect(params: Connection) { addEdges([{ ...params, id: `e-${params.source}-${params.target}-${Date.now()}`, label: "success", animated: true }]); nextTick(syncDsl); }
function selectNode(event: NodeMouseEvent) { activeNodeId.value = event.node.id; activeEdgeId.value = null; editorTab.value = "properties"; }
function selectEdge(event: { edge: Edge }) { activeEdgeId.value = event.edge.id; activeNodeId.value = null; editorTab.value = "properties"; }
function clearSelection() { activeNodeId.value = null; activeEdgeId.value = null; }
function updateNode(key: string, value: unknown) { if (activeNode.value) { activeNode.value.data[key] = value; syncDsl(); } }
function updateTools(value: string) { updateNode("tool_allowlist", value.split(",").map((item) => item.trim()).filter(Boolean)); }
function updateEdgeCondition(value: string) { if (activeEdge.value) { activeEdge.value.label = value; activeEdge.value.animated = value !== "failure"; syncDsl(); } }
function removeActiveNode() { if (!activeNodeId.value) return; nodes.value = nodes.value.filter((node) => node.id !== activeNodeId.value); edges.value = edges.value.filter((edge) => edge.source !== activeNodeId.value && edge.target !== activeNodeId.value); clearSelection(); }
function removeActiveEdge() { edges.value = edges.value.filter((edge) => edge.id !== activeEdgeId.value); clearSelection(); }
function dragRole(event: DragEvent, role: string) { event.dataTransfer?.setData("application/zhixiao-role", role); if (event.dataTransfer) event.dataTransfer.effectAllowed = "copy"; }
function dropRole(event: DragEvent) { const role = event.dataTransfer?.getData("application/zhixiao-role"); if (!role) return; const id = `${role}-${Date.now()}`; const point = screenToFlowCoordinate({ x: event.clientX, y: event.clientY }); nodes.value = [...nodes.value, { id, position: { x: point.x - 70, y: point.y - 30 }, data: { id, role, label: role[0].toUpperCase() + role.slice(1), retry_limit: 0, approval_required: false, tool_allowlist: [] } }]; }
function autoLayout() { nodes.value = nodes.value.map((node, index) => ({ ...node, position: { x: (index % 4) * 230, y: Math.floor(index / 4) * 150 } })); nextTick(() => fitView({ padding: .2 })); }
function applyDsl(value: string) {
  try {
    const parsed = JSON.parse(value) as { nodes?: WorkflowNodeDefinition[]; edges?: WorkflowEdgeDefinition[] };
    if (!Array.isArray(parsed.nodes) || !parsed.nodes.length || !Array.isArray(parsed.edges)) throw new Error("DSL 必须包含非空 nodes 与 edges 数组");
    const ids = parsed.nodes.map((node) => node.id); if (new Set(ids).size !== ids.length || ids.some((id) => !id)) throw new Error("节点 id 必须存在且唯一");
    syncing.value = true; if (selected.value) selected.value.definition = { nodes: parsed.nodes, edges: parsed.edges }; toCanvas({ nodes: parsed.nodes, edges: parsed.edges }); dslError.value = "";
  } catch (error) { dslError.value = error instanceof Error ? error.message : "JSON DSL 格式无效"; }
  finally { syncing.value = false; }
}
async function saveVersion() { if (!selected.value || !nodes.value.length) return; saving.value = true; try { const saved = await workflowApi.create({ ...selected.value, enabled: false, version: selected.value.id ? selected.value.version + 1 : selected.value.version, definition: fromCanvas() }); await load(); select(saved); ElMessage.success("新版本已保存为草稿"); } finally { saving.value = false; } }
async function publish() { if (!selected.value?.id) return; publishing.value = true; try { const published = await workflowApi.publish(selected.value.id); await load(); select(published); ElMessage.success(`v${published.version} 已发布`); } finally { publishing.value = false; } }
async function replay() { if (!replayRunId.value) { ElMessage.warning("请输入任务运行编号"); return; } replaying.value = true; try { const data = await workflowApi.replay(replayRunId.value); replaySteps.value = data.steps; replayVersion.value = data.workflow?.version ?? null; if (data.workflow) toCanvas(data.workflow.definition); const statuses = new Map(data.steps.map((step) => [step.role, step.status])); nodes.value.forEach((node) => { node.data.status = statuses.get(String(node.data.role)) || "idle"; }); } finally { replaying.value = false; } }
function timelineType(status: string) { return status === "succeeded" ? "success" : status === "failed" ? "danger" : status === "running" ? "primary" : "info"; }
function nodeLabel(id: string) { return nodes.value.find((node) => node.id === id)?.data.label || id; }
function replaySummary(output?: Record<string, unknown> | null) { if (!output) return ""; const value = output.summary; return typeof value === "string" ? value : ""; }
async function load() { workflows.value = await workflowApi.list(); if (selected.value?.id) { const current = workflows.value.find((item) => item.id === selected.value?.id); if (current) select(current); } else if (workflows.value[0]) select(workflows.value[0]); }

watch([nodes, edges], syncDsl, { deep: true });
onMounted(load);
</script>

<style scoped lang="scss">
.heading-actions, .canvas-toolbar, .replay-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.workflow-studio-grid { grid-template-columns: 250px minmax(0, 1fr); align-items: start; }
.side-list { min-height: 720px; }
.palette { margin: 18px -4px 0; padding: 16px 4px 0; border-top: 1px solid var(--border); }
.palette > strong, .palette > small { display: block; }
.palette > small { margin: 3px 0 10px; color: var(--text-muted); }
.palette button {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 5px 0;
  padding: 8px;
  color: var(--text);
  background: var(--surface-soft);
  border: 1px solid var(--border);
  cursor: grab;
  text-align: left;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.palette button:hover { border-color: #9cb7a1; background: var(--brand-soft); }
.palette button span { width: 24px; height: 24px; display: grid; place-items: center; color: var(--brand); background: var(--brand-soft); font: 700 11px var(--mono); }
.editor-stack { min-width: 0; display: flex; flex-direction: column; gap: 14px; }
.workflow-name { max-width: 360px; }
.flow-shell { height: 480px; border: 1px solid var(--border); background: var(--surface-soft); }
.workflow-node { width: 150px; min-height: 74px; padding: 11px 12px; color: var(--text); background: var(--surface); border: 1px solid #9aae9d; box-shadow: 3px 3px 0 rgba(77, 115, 84, .14); }
.workflow-node span, .workflow-node strong, .workflow-node small { display: block; }
.workflow-node span { color: var(--brand); font: 700 9px var(--mono); text-transform: uppercase; letter-spacing: 1px; }
.workflow-node strong { margin: 7px 0 4px; }
.workflow-node small { color: var(--text-muted); }
.workflow-node.status-running { border-color: #409eff; box-shadow: 3px 3px 0 rgba(64,158,255,.2); }
.workflow-node.status-succeeded { border-color: #3b9a57; }
.workflow-node.status-failed { border-color: #d9534f; }
.property-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; max-width: 900px; }
.property-grid .el-select, .edge-properties .el-select { width: 100%; }
.edge-properties { max-width: 420px; }
.replay-toolbar { justify-content: flex-start; margin-bottom: 18px; }
.replay-toolbar span { color: var(--text-muted); font: 12px var(--mono); }
.el-timeline-item p { margin: 5px 0; color: var(--text-muted); }
:deep(.vue-flow__node) { border: 0; background: transparent; padding: 0; box-shadow: none; }
:deep(.vue-flow__node.selected .workflow-node) { outline: 2px solid var(--brand); outline-offset: 2px; }
:deep(.vue-flow__edge.selected .vue-flow__edge-path) { stroke: var(--brand); stroke-width: 3; }
@media (max-width: 1050px) { .workflow-studio-grid { grid-template-columns: 1fr; } .side-list { min-height: auto; } .palette { display: grid; grid-template-columns: repeat(3, 1fr); gap: 5px; } .palette > strong, .palette > small { grid-column: 1 / -1; } }
@media (max-width: 640px) { .heading-actions, .canvas-toolbar { align-items: stretch; flex-direction: column; } .workflow-name { max-width: none; } .flow-shell { height: 420px; } .property-grid { grid-template-columns: 1fr; } .palette { grid-template-columns: repeat(2, 1fr); } }
</style>
