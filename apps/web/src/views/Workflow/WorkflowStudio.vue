<template>
  <section class="page-stack">
    <header class="page-heading"><div><p class="eyebrow">ORCHESTRATION</p><h1>工作流</h1><p>版本化执行图定义任务如何规划、实现、验证和复核。</p></div><el-button type="primary" @click="newWorkflow">新建工作流</el-button></header>
    <div class="studio-grid">
      <el-card shadow="never" class="side-list"><template #header>工作流版本</template>
        <button v-for="item in workflows" :key="item.id" class="select-row" :class="{ active: selected?.id === item.id }" @click="select(item)"><span><strong>{{ item.name }}</strong><small>v{{ item.version }} · {{ item.definition.nodes.length }} 节点</small></span><el-switch v-model="item.enabled" @click.stop /></button>
        <el-empty v-if="!workflows.length" description="暂无工作流" />
      </el-card>
      <el-card shadow="never" class="canvas-card"><template #header><div class="card-header"><span>执行图预览</span><el-button :disabled="!selected" :loading="saving" type="primary" size="small" @click="save">保存新版本</el-button></div></template>
        <div v-if="selected" class="workflow-canvas"><template v-for="(node, index) in selected.definition.nodes" :key="node.id"><div class="flow-node"><span>{{ String(index + 1).padStart(2, '0') }}</span><strong>{{ node.label }}</strong><small>{{ node.role }}</small></div><div v-if="index < selected.definition.nodes.length - 1" class="flow-edge">→</div></template></div>
        <el-empty v-else description="选择一个工作流查看执行图" />
        <el-form v-if="selected" label-position="top" class="workflow-form"><el-form-item label="名称"><el-input v-model="selected.name" /></el-form-item><el-form-item label="JSON DSL"><el-input v-model="dsl" type="textarea" :rows="13" class="mono-input" @change="applyDsl" /></el-form-item></el-form>
      </el-card>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { workflowApi } from "@/api/agent";
import type { WorkflowDefinition } from "@/types";
const workflows = ref<WorkflowDefinition[]>([]); const selected = ref<WorkflowDefinition | null>(null); const saving = ref(false); const dsl = ref("");
function select(item: WorkflowDefinition) { selected.value = structuredClone(item); dsl.value = JSON.stringify(selected.value.definition, null, 2); }
function newWorkflow() { selected.value = { id: 0, space_id: 0, name: "工程 Agent 标准流", version: 1, enabled: true, definition: { nodes: ["planner", "explorer", "implementer", "tester", "reviewer", "knowledge"].map((role) => ({ id: role, role, label: role[0].toUpperCase() + role.slice(1) })), edges: [] }, created_at: "", updated_at: "" }; dsl.value = JSON.stringify(selected.value.definition, null, 2); }
function applyDsl(value: string) { try { if (selected.value) selected.value.definition = JSON.parse(value) as WorkflowDefinition["definition"]; } catch { ElMessage.error("JSON DSL 格式无效"); } }
async function save() { if (!selected.value) return; saving.value = true; try { const saved = await workflowApi.create({ ...selected.value, version: selected.value.id ? selected.value.version + 1 : selected.value.version }); await load(); select(saved); ElMessage.success("工作流版本已保存"); } finally { saving.value = false; } }
async function load() { workflows.value = await workflowApi.list(); if (!selected.value && workflows.value[0]) select(workflows.value[0]); }
onMounted(load);
</script>
