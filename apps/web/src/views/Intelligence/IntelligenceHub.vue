<template>
  <section class="page-stack">
    <header class="page-heading"><div><p class="eyebrow">KNOWLEDGE QUALITY</p><h1>图谱与评测</h1><p>查看可追溯的知识关系，用固定场景集衡量 Agent 的真实工程能力。</p></div><el-button v-if="tab === 'evaluation'" type="primary" @click="evaluationDialog = true">运行评测</el-button></header>
    <el-tabs v-model="tab" class="surface-tabs">
      <el-tab-pane label="知识图谱" name="graph"><div class="graph-toolbar"><el-input v-model="query" clearable placeholder="搜索实体"/><span>{{ filteredEntities.length }} 实体 · {{ graph.relations.length }} 关系</span></div><div class="graph-layout"><div class="entity-cloud"><button v-for="entity in filteredEntities" :key="entity.id" class="entity-node" :class="{ active: selectedEntity === entity.id }" @click="selectedEntity = entity.id"><strong>{{ entity.name }}</strong><small>{{ entity.entity_type }} · {{ entity.source_refs.length }} 个来源</small></button><el-empty v-if="!filteredEntities.length" description="暂无图谱实体" /></div><el-card shadow="never" class="evidence-panel"><template #header>关系与证据</template><article v-for="rel in visibleRelations" :key="rel.id" class="relation"><strong>{{ entityName(rel.source_entity_id) }} → {{ rel.relation_type }} → {{ entityName(rel.target_entity_id) }}</strong><p>{{ formatEvidence(rel.evidence) }}</p></article><el-empty v-if="!visibleRelations.length" description="选择实体查看证据链" /></el-card></div></el-tab-pane>
      <el-tab-pane label="Agent 评测" name="evaluation"><el-table :data="evaluations"><el-table-column prop="dataset_name" label="评测集"/><el-table-column prop="status" label="状态" width="120"/><el-table-column label="任务成功率" width="140"><template #default="{ row }">{{ percent(row.metrics?.task_success_rate) }}</template></el-table-column><el-table-column label="首次通过率" width="140"><template #default="{ row }">{{ percent(row.metrics?.first_pass_rate) }}</template></el-table-column><el-table-column label="平均延迟" width="140"><template #default="{ row }">{{ row.metrics?.avg_latency_ms ? `${Math.round(row.metrics.avg_latency_ms)} ms` : '—' }}</template></el-table-column><el-table-column label="平均成本" width="120"><template #default="{ row }">{{ row.metrics?.avg_cost == null ? '—' : `$${row.metrics.avg_cost.toFixed(3)}` }}</template></el-table-column></el-table></el-tab-pane>
    </el-tabs>
    <el-dialog v-model="evaluationDialog" title="运行固定评测集" width="480px"><el-form label-position="top"><el-form-item label="运行名称"><el-input v-model="evaluationName" placeholder="release-candidate-01"/></el-form-item></el-form><template #footer><el-button @click="evaluationDialog=false">取消</el-button><el-button type="primary" @click="createEvaluation">开始评测</el-button></template></el-dialog>
  </section>
</template>
<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { intelligenceApi } from "@/api/agent";
import type { EvaluationRun, KnowledgeEntity, KnowledgeRelation } from "@/types";
const tab = ref("graph"); const query = ref(""); const selectedEntity = ref<number | null>(null); const graph = reactive<{ entities: KnowledgeEntity[]; relations: KnowledgeRelation[] }>({ entities: [], relations: [] }); const evaluations = ref<EvaluationRun[]>([]); const evaluationDialog = ref(false); const evaluationName = ref("");
const filteredEntities = computed(() => { const needle = query.value.trim().toLowerCase(); return needle ? graph.entities.filter((item) => item.name.toLowerCase().includes(needle) || item.entity_type.toLowerCase().includes(needle)) : graph.entities; });
const visibleRelations = computed(() => selectedEntity.value ? graph.relations.filter((r) => r.source_entity_id === selectedEntity.value || r.target_entity_id === selectedEntity.value) : graph.relations.slice(0, 12));
function entityName(id: number) { return graph.entities.find((entity) => entity.id === id)?.name || String(id); }
function formatEvidence(value: Array<Record<string, unknown>>) { return value.length ? value.map((item) => JSON.stringify(item)).join("；") : "暂无证据摘要"; }
function percent(value?: number) { return value == null ? "—" : `${(value * 100).toFixed(1)}%`; }
async function loadGraph() { const data = await intelligenceApi.graph(); graph.entities = data.entities; graph.relations = data.relations; }
async function loadEvaluations() { evaluations.value = await intelligenceApi.evaluations(); }
async function createEvaluation() { if (!evaluationName.value.trim()) { ElMessage.warning("请填写评测集名称"); return; } await intelligenceApi.createEvaluation({ dataset_name: evaluationName.value.trim() }); evaluationDialog.value=false; await loadEvaluations(); ElMessage.success("评测已进入队列"); }
onMounted(() => Promise.allSettled([loadGraph(), loadEvaluations()]));
</script>
