<template>
  <section class="workspace page-stack">
    <div class="workspace-hero">
      <div><p class="eyebrow">AGENT COMMAND CENTER</p><h1>把工程目标交给可验证的执行闭环</h1><p>Agent 会先理解仓库和项目指令，再计划、隔离编辑、运行测试与交付可审查的 Diff。</p><div class="hero-actions"><el-button type="primary" size="large" @click="$router.push('/tasks?create=1')">创建工程任务</el-button><el-button size="large" @click="$router.push('/repositories')">管理代码仓库</el-button></div></div>
      <div class="loop-visual"><span v-for="(step, index) in loop" :key="step" :class="{ hot: index < 3 }"><b>{{ String(index + 1).padStart(2, '0') }}</b>{{ step }}</span></div>
    </div>
    <div class="cards"><article v-for="card in cards" :key="card.key" class="metric-card"><span>{{ card.title }}</span><strong>{{ card.display }}</strong><small>{{ card.note }}</small></article></div>
    <div class="dashboard-grid">
      <el-card class="recent" shadow="never"><template #header><div class="card-header"><span>最近任务</span><el-button text @click="$router.push('/tasks')">查看全部 →</el-button></div></template><el-table :data="recent" @row-click="onTaskClick"><el-table-column label="任务"><template #default="{ row }"><strong>{{ row.title }}</strong><div class="muted">#{{ row.id }}</div></template></el-table-column><el-table-column prop="status" label="状态" width="110"><template #default="{ row }"><el-tag :type="statusTag(row.status)">{{ statusText(row.status) }}</el-tag></template></el-table-column><el-table-column prop="created_at" label="创建时间" width="190"/></el-table><el-empty v-if="!recent.length" description="还没有工程任务" /></el-card>
      <el-card shadow="never" class="quick"><template #header>常用场景</template><button v-for="template in templates" :key="template.title" class="quick-row" @click="startTemplate(template)"><span>{{ template.icon }}</span><div><strong>{{ template.title }}</strong><small>{{ template.description }}</small></div><b>→</b></button></el-card>
    </div>
  </section>
</template>
<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { statsApi } from "@/api/stats";
import type { SpaceOverview, TaskItem } from "@/types";
const router = useRouter(); const overview = ref<SpaceOverview>({ total_tasks:0, succeeded:0, tasks_last_30d:0, knowledge_total:0, reuse_rate:0 }); const recent = ref<Array<Pick<TaskItem,"id"|"title"|"status"|"created_at">>>([]);
const loop = ["探测", "计划", "实现", "验证", "复核", "交付"];
const templates = [{ icon:"BUG", title:"修复缺陷", description:"定位根因、补回归测试并生成最小 Diff" },{ icon:"API", title:"实现跨栈功能", description:"同步修改接口、类型、前端与集成验证" },{ icon:"REV", title:"代码审查", description:"按风险分级输出可定位的审查结论" }];
const cards = computed(() => [{ key:"total",title:"累计任务",display:overview.value.total_tasks,note:"全部工程运行" },{ key:"success",title:"成功交付",display:overview.value.succeeded,note:"通过质量门禁" },{ key:"month",title:"30 天活跃",display:overview.value.tasks_last_30d,note:"新建任务" },{ key:"knowledge",title:"知识资产",display:overview.value.knowledge_total,note:`复用率 ${(overview.value.reuse_rate*100).toFixed(1)}%` }]);
function onTaskClick(row: Pick<TaskItem,"id">){ router.push(`/task/${row.id}`); }
function startTemplate(template: {title:string;description:string}){ router.push({ path:"/tasks",query:{ create:"1", title:template.title, goal:template.description } }); }
function statusTag(status: TaskItem["status"]){ return status==="succeeded"?"success":status==="failed"?"danger":status==="awaiting_approval"?"warning":"primary"; }
function statusText(status: TaskItem["status"]){ return ({awaiting_approval:"待审批",queued:"排队中",running:"执行中",succeeded:"已完成",failed:"失败",interrupted:"已中断",cancelled:"已取消"} as const)[status]; }
onMounted(async()=>{ const [stats,tasks]=await Promise.allSettled([statsApi.overview(),statsApi.recentTasks()]); if(stats.status==="fulfilled") overview.value=stats.value; if(tasks.status==="fulfilled") recent.value=tasks.value as typeof recent.value; });
</script>
<style scoped lang="scss">
.workspace-hero { display:grid; grid-template-columns:1.25fr .75fr; gap:42px; padding:36px; color:#edf7ee; background:#13251a; border:1px solid #27452f; overflow:hidden; }.workspace-hero h1 { max-width:710px; margin:6px 0 12px; font-size:36px; line-height:1.15; letter-spacing:-1.2px; }.workspace-hero p:not(.eyebrow) { max-width:680px; color:#9fb2a3; line-height:1.7; }.hero-actions { display:flex; gap:10px; margin-top:24px; }.loop-visual { display:grid; align-content:center; }.loop-visual span { display:flex; gap:18px; padding:9px 14px; color:#6e8073; border-left:1px solid #39513f; font-size:13px; }.loop-visual span.hot { color:#c9f7c8; border-left-color:#91e377; background:linear-gradient(90deg,rgba(145,227,119,.1),transparent); }.loop-visual b { font:11px var(--mono); }.cards { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; }.metric-card { padding:17px 19px; background:var(--surface); border:1px solid var(--border); }.metric-card span,.metric-card small,.metric-card strong { display:block; }.metric-card span,.metric-card small { color:var(--text-muted); font-size:11px; }.metric-card strong { margin:8px 0 5px; font:700 28px var(--mono); }.dashboard-grid { display:grid; grid-template-columns:minmax(0,1.6fr) minmax(320px,.7fr); gap:14px; }.quick-row { width:100%; display:grid; grid-template-columns:42px 1fr 20px; gap:11px; align-items:center; padding:13px 0; text-align:left; color:inherit; background:none; border:0; border-bottom:1px solid var(--border); cursor:pointer; }.quick-row>span { color:var(--brand); font:700 11px var(--mono); }.quick-row strong,.quick-row small { display:block; }.quick-row small { color:var(--text-muted); margin-top:4px; }.quick-row>b { color:var(--brand); } @media(max-width:1000px){.workspace-hero,.dashboard-grid{grid-template-columns:1fr}.cards{grid-template-columns:repeat(2,1fr)}}
</style>
