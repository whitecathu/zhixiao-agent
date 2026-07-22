<template>
  <section class="page-stack">
    <header class="page-heading"><div><p class="eyebrow">KNOWLEDGE QUALITY</p><h1>图谱与评测</h1><p>通过实体关系和原始证据追溯 Agent 的知识结论。</p></div><el-button v-if="tab === 'evaluation'" type="primary" @click="evaluationDialog = true">运行评测</el-button></header>
    <el-tabs v-model="tab" class="surface-tabs">
      <el-tab-pane label="知识图谱" name="graph">
        <div class="graph-toolbar">
          <div class="graph-search"><el-input v-model="query" clearable placeholder="搜索实体名称、类型或关键词" @keyup.enter="explore"/><el-select v-model="entityType" clearable placeholder="全部类型"><el-option v-for="type in entityTypes" :key="type" :label="type" :value="type"/></el-select><el-button :loading="graphLoading" type="primary" @click="explore">检索</el-button></div>
          <span>{{ graph.entities.length }} 实体 · {{ graph.relations.length }} 关系</span>
        </div>
        <el-alert v-if="graph.truncated" title="结果已达到安全上限，可增加筛选条件缩小图谱。" type="warning" :closable="false" show-icon />
        <el-alert v-if="graph.retrieval_mode === 'fallback'" title="图服务暂不可用，当前展示向量/关键词降级结果。" type="info" :closable="false" show-icon />
        <el-alert v-else-if="graph.evidence_sufficient === false && graph.entities.length" title="当前关系缺少来源证据，不会作为知识问答依据。" type="warning" :closable="false" show-icon />
        <div class="knowledge-graph-layout">
          <div class="knowledge-flow" v-loading="graphLoading">
            <VueFlow v-model:nodes="flowNodes" v-model:edges="flowEdges" :nodes-draggable="true" :nodes-connectable="false" fit-view-on-init @node-click="onNodeClick" @edge-click="onEdgeClick">
              <Background pattern-color="#bec9c0" :gap="20" />
              <Controls position="bottom-right" />
              <template #node-entity="{ data }"><article class="entity-card" :class="{ active: selectedEntity?.id === data.entity.id }"><span>{{ data.entity.entity_type }}</span><strong>{{ data.entity.name }}</strong><small>{{ data.entity.source_refs.length }} 个来源</small></article></template>
            </VueFlow>
            <el-empty v-if="!flowNodes.length && !graphLoading" description="没有匹配的知识实体" />
          </div>
          <el-card shadow="never" class="evidence-panel">
            <template #header><div class="card-header"><span>关系与证据</span><el-button v-if="selectedEntity" size="small" :loading="expanding" @click="expandSelected">展开邻居</el-button></div></template>
            <div v-if="selectedEntity" class="entity-summary"><p class="eyebrow">{{ selectedEntity.entity_type }}</p><h3>{{ selectedEntity.name }}</h3><div class="property-list"><span v-for="(value, key) in selectedEntity.properties" :key="key"><small>{{ key }}</small>{{ display(value) }}</span></div></div>
            <article v-for="rel in visibleRelations" :key="rel.id" class="relation" :class="{ active: selectedRelation?.id === rel.id }" @click="selectedRelation = rel">
              <strong>{{ entityName(rel.source_entity_id) }} → {{ rel.relation_type }} → {{ entityName(rel.target_entity_id) }}</strong>
              <p v-if="!rel.evidence.length" class="no-evidence">无来源证据，不参与回答</p>
              <ul v-else class="evidence-list"><li v-for="(evidence, index) in rel.evidence" :key="index"><span>{{ evidenceTitle(evidence) }}</span><small>{{ evidenceExcerpt(evidence) }}</small><a v-if="evidenceUrl(evidence)" :href="evidenceUrl(evidence)" target="_blank" rel="noreferrer">打开来源</a></li></ul>
            </article>
            <el-empty v-if="!selectedEntity && !selectedRelation" description="选择实体或关系查看证据链" :image-size="70" />
          </el-card>
        </div>
      </el-tab-pane>
      <el-tab-pane label="Agent 评测" name="evaluation"><el-table :data="evaluations"><el-table-column prop="dataset_name" label="评测集"/><el-table-column prop="status" label="状态" width="120"/><el-table-column label="任务成功率" width="140"><template #default="{ row }">{{ percent(row.metrics?.task_success_rate) }}</template></el-table-column><el-table-column label="首次通过率" width="140"><template #default="{ row }">{{ percent(row.metrics?.first_pass_rate) }}</template></el-table-column><el-table-column label="平均延迟" width="140"><template #default="{ row }">{{ row.metrics?.avg_latency_ms ? `${Math.round(row.metrics.avg_latency_ms)} ms` : '—' }}</template></el-table-column><el-table-column label="平均成本" width="120"><template #default="{ row }">{{ row.metrics?.avg_cost == null ? '—' : `$${row.metrics.avg_cost.toFixed(3)}` }}</template></el-table-column></el-table></el-tab-pane>
    </el-tabs>
    <el-dialog v-model="evaluationDialog" title="运行固定评测集" width="480px"><el-form label-position="top"><el-form-item label="运行名称"><el-input v-model="evaluationName" placeholder="release-candidate-01"/></el-form-item></el-form><template #footer><el-button @click="evaluationDialog=false">取消</el-button><el-button type="primary" @click="createEvaluation">开始评测</el-button></template></el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, shallowRef } from "vue";
import { ElMessage } from "element-plus";
import { Background } from "@vue-flow/background";
import { Controls } from "@vue-flow/controls";
import { VueFlow, useVueFlow } from "@vue-flow/core";
import type { Edge, Node, NodeMouseEvent } from "@vue-flow/core";
import "@vue-flow/core/dist/style.css";
import "@vue-flow/core/dist/theme-default.css";
import "@vue-flow/controls/dist/style.css";

import { intelligenceApi } from "@/api/agent";
import type { EvaluationRun, KnowledgeEntity, KnowledgeGraphExploreResult, KnowledgeRelation } from "@/types";

const tab = ref("graph");
const query = ref("");
const entityType = ref("");
const graphLoading = ref(false);
const expanding = ref(false);
const graph = reactive<KnowledgeGraphExploreResult>({ entities: [], relations: [] });
const selectedEntity = ref<KnowledgeEntity | null>(null);
const selectedRelation = ref<KnowledgeRelation | null>(null);
const flowNodes = shallowRef<Node[]>([]);
const flowEdges = shallowRef<Edge[]>([]);
const evaluations = ref<EvaluationRun[]>([]);
const evaluationDialog = ref(false);
const evaluationName = ref("");
const { fitView } = useVueFlow();

const entityTypes = computed(() => [...new Set(graph.entities.map((item) => item.entity_type))].sort());
const visibleRelations = computed(() => {
  if (selectedRelation.value) return [selectedRelation.value];
  if (selectedEntity.value) return graph.relations.filter((rel) => rel.source_entity_id === selectedEntity.value?.id || rel.target_entity_id === selectedEntity.value?.id);
  return [];
});

function rebuildFlow() {
  const count = Math.max(graph.entities.length, 1);
  flowNodes.value = graph.entities.map((entity, index) => { const angle = (index / count) * Math.PI * 2; const ring = 150 + Math.floor(index / 12) * 110; return { id: String(entity.id), type: "entity", position: { x: 340 + Math.cos(angle) * ring, y: 220 + Math.sin(angle) * ring }, data: { entity } }; });
  flowEdges.value = graph.relations.map((rel) => ({ id: String(rel.id), source: String(rel.source_entity_id), target: String(rel.target_entity_id), label: rel.relation_type, animated: rel.evidence.length > 0, style: { stroke: rel.evidence.length ? "#628b69" : "#a9b0aa", strokeDasharray: rel.evidence.length ? undefined : "5 5" } }));
  nextTick(() => fitView({ padding: .18 }));
}
function mergeGraph(data: KnowledgeGraphExploreResult, replace = true) {
  if (replace) { graph.entities = data.entities; graph.relations = data.relations; }
  else {
    const entityMap = new Map(graph.entities.map((entity) => [entity.id, entity])); data.entities.forEach((entity) => entityMap.set(entity.id, entity)); graph.entities = [...entityMap.values()];
    const relationMap = new Map(graph.relations.map((relation) => [relation.id, relation])); data.relations.forEach((relation) => relationMap.set(relation.id, relation)); graph.relations = [...relationMap.values()];
  }
  graph.truncated = data.truncated; graph.retrieval_mode = data.retrieval_mode; graph.evidence_chain = data.evidence_chain; graph.evidence_sufficient = data.evidence_sufficient; graph.evidence_status = data.evidence_status; rebuildFlow();
}
async function explore() {
  graphLoading.value = true;
  try { const data = await intelligenceApi.exploreGraph({ query: query.value.trim() || undefined, entity_types: entityType.value ? [entityType.value] : undefined, depth: 1, limit: 100 }); mergeGraph(data); selectedEntity.value = null; selectedRelation.value = null; }
  catch {
    try { const fallback = await intelligenceApi.graph(); mergeGraph({ ...fallback, retrieval_mode: "fallback" }); }
    catch { graph.entities = []; graph.relations = []; rebuildFlow(); }
  } finally { graphLoading.value = false; }
}
async function expandSelected() { if (!selectedEntity.value) return; expanding.value = true; try { const data = await intelligenceApi.exploreGraph({ entity_id: selectedEntity.value.id, depth: 1, limit: 100 }); mergeGraph(data, false); } finally { expanding.value = false; } }
function onNodeClick(event: NodeMouseEvent) { selectedEntity.value = event.node.data.entity as KnowledgeEntity; selectedRelation.value = null; }
function onEdgeClick(event: { edge: Edge }) { selectedRelation.value = graph.relations.find((relation) => String(relation.id) === event.edge.id) || null; selectedEntity.value = null; }
function entityName(id: number) { return graph.entities.find((entity) => entity.id === id)?.name || String(id); }
function display(value: unknown) { return typeof value === "string" ? value : JSON.stringify(value); }
function evidenceTitle(value: Record<string, unknown>) { return String(value.title || value.source || value.path || "来源证据"); }
function evidenceExcerpt(value: Record<string, unknown>) { return String(value.excerpt || value.quote || value.content || "已记录来源，但未提供摘要"); }
function evidenceUrl(value: Record<string, unknown>) { const url = value.url; return typeof url === "string" && /^https?:\/\//.test(url) ? url : ""; }
function percent(value?: number) { return value == null ? "—" : `${(value * 100).toFixed(1)}%`; }
async function loadEvaluations() { evaluations.value = await intelligenceApi.evaluations(); }
async function createEvaluation() { if (!evaluationName.value.trim()) { ElMessage.warning("请填写评测集名称"); return; } await intelligenceApi.createEvaluation({ dataset_name: evaluationName.value.trim() }); evaluationDialog.value=false; await loadEvaluations(); ElMessage.success("评测已进入队列"); }
onMounted(() => Promise.allSettled([explore(), loadEvaluations()]));
</script>

<style scoped lang="scss">
.graph-search { display: flex; align-items: center; gap: 8px; flex: 1; }
.graph-search .el-input { max-width: 500px; }
.graph-search .el-select { width: 170px; }
.knowledge-graph-layout { display: grid; grid-template-columns: minmax(0, 1fr) 390px; gap: 14px; min-height: 600px; margin-top: 12px; }
.knowledge-flow { position: relative; min-height: 600px; overflow: hidden; border: 1px solid var(--border); background: var(--surface-soft); }
.knowledge-flow > .el-empty { position: absolute; inset: 0; }
.entity-card { min-width: 130px; max-width: 190px; padding: 10px 12px; color: var(--text); background: var(--surface); border: 1px solid #a2afa4; box-shadow: 3px 3px 0 rgba(61, 99, 68, .14); }
.entity-card span, .entity-card strong, .entity-card small { display: block; }
.entity-card span { color: var(--brand); font: 700 9px var(--mono); letter-spacing: 1px; text-transform: uppercase; }
.entity-card strong { overflow: hidden; margin: 6px 0 4px; text-overflow: ellipsis; white-space: nowrap; }
.entity-card small { color: var(--text-muted); }
.entity-card.active { outline: 2px solid var(--brand); outline-offset: 2px; }
.evidence-panel { min-width: 0; max-height: 600px; overflow: auto; }
.entity-summary { padding-bottom: 14px; border-bottom: 1px solid var(--border); }
.entity-summary h3 { margin: 4px 0 12px; font-size: 20px; }
.property-list { display: flex; flex-wrap: wrap; gap: 6px; }
.property-list span { max-width: 100%; padding: 5px 7px; background: var(--surface-soft); overflow-wrap: anywhere; font-size: 12px; }
.property-list small { margin-right: 5px; color: var(--text-muted); }
.relation { cursor: pointer; }
.relation.active { box-shadow: inset 3px 0 var(--brand); padding-left: 10px; }
.no-evidence { color: #b44d49 !important; }
.evidence-list { margin: 9px 0 0; padding: 0; list-style: none; }
.evidence-list li { padding: 8px; background: var(--surface-soft); border-left: 2px solid var(--brand); }
.evidence-list li + li { margin-top: 6px; }
.evidence-list span, .evidence-list small { display: block; }
.evidence-list small { margin-top: 4px; color: var(--text-muted); line-height: 1.5; }
.evidence-list a { display: inline-block; margin-top: 5px; color: var(--brand); font-size: 12px; }
:deep(.vue-flow__node) { border: 0; background: transparent; padding: 0; box-shadow: none; }
:deep(.vue-flow__edge-text) { font-size: 10px; fill: var(--text-muted); }
@media (max-width: 1050px) { .knowledge-graph-layout { grid-template-columns: 1fr; } .evidence-panel { max-height: none; } }
@media (max-width: 680px) { .graph-toolbar, .graph-search { align-items: stretch; flex-direction: column; } .graph-search .el-input, .graph-search .el-select { width: 100%; max-width: none; } .knowledge-flow { min-height: 450px; } }
</style>
