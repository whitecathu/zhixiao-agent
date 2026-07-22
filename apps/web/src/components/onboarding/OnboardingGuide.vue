<template>
  <el-dialog
    v-model="open"
    class="onboarding-dialog"
    width="min(680px, calc(100vw - 28px))"
    :show-close="false"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    aria-label="首次上手引导"
  >
    <template #header>
      <div class="guide-header">
        <div><p class="eyebrow">GET STARTED</p><h2>完成第一次 Agent 交付</h2></div>
        <span v-if="state" class="progress-label">{{ state.completed_steps.length }} / {{ state.steps.length }}</span>
      </div>
    </template>
    <div v-loading="loading">
      <p class="intro">进度保存在当前工作空间，可随时跳过或从个人菜单重新播放。</p>
      <ol v-if="state" class="guide-steps">
        <li v-for="(step, index) in state.steps" :key="step.id" :class="{ done: step.completed, current: step.id === state.current_step }">
          <span class="step-index">{{ step.completed ? "✓" : index + 1 }}</span>
          <div><strong>{{ step.label }}</strong><small>{{ descriptions[step.id] }}</small></div>
          <el-button v-if="!step.completed && step.id === state.current_step" size="small" @click="go(step.id)">前往</el-button>
        </li>
      </ol>
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    </div>
    <template #footer>
      <div class="guide-footer">
        <el-button text @click="skip">稍后再说</el-button>
        <div>
          <el-button v-if="isAdmin" @click="settingsOpen = true">空间推荐配置</el-button>
          <el-button type="primary" :disabled="!state?.current_step" :loading="saving" @click="completeCurrent">标记当前步骤完成</el-button>
        </div>
      </div>
    </template>
  </el-dialog>

  <el-dialog v-model="settingsOpen" title="空间上手默认项" width="520px">
    <el-form label-position="top">
      <el-form-item label="推荐任务模板"><el-input v-model="config.recommended_template" maxlength="128" placeholder="例如：跨栈缺陷修复" /></el-form-item>
      <el-form-item label="默认工作流">
        <el-select v-model="config.default_workflow_id" clearable placeholder="由成员自行选择">
          <el-option v-for="workflow in workflows" :key="workflow.id" :label="`${workflow.name} · v${workflow.version}`" :value="workflow.id" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer><el-button @click="settingsOpen = false">取消</el-button><el-button type="primary" :loading="savingConfig" @click="saveConfig">保存</el-button></template>
  </el-dialog>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";

import { workflowApi } from "@/api/agent";
import { onboardingApi } from "@/api/product";
import { spaceApi } from "@/api/space";
import { useUserStore } from "@/stores/user";
import type { OnboardingState, WorkflowDefinition } from "@/types";

const props = defineProps<{ spaceId: number | null }>();
const router = useRouter();
const userStore = useUserStore();
const open = ref(false);
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const state = ref<OnboardingState | null>(null);
const isAdmin = ref(false);
const settingsOpen = ref(false);
const savingConfig = ref(false);
const workflows = ref<WorkflowDefinition[]>([]);
const config = reactive<{ recommended_template: string; default_workflow_id: number | null }>({ recommended_template: "", default_workflow_id: null });

const descriptions: Record<string, string> = {
  select_space: "确认任务、知识和权限归属的空间。",
  connect_repository: "接入本地路径或远程 Git 仓库。",
  create_task: "描述目标、验收标准与执行权限。",
  approve_plan: "检查计划和高风险操作后再放行。",
  inspect_delivery: "确认 Diff、测试报告和失败说明。",
};
const destinations: Record<string, string> = {
  select_space: "/team", connect_repository: "/repositories", create_task: "/tasks",
  approve_plan: "/tasks", inspect_delivery: "/tasks",
};

async function load() {
  if (!props.spaceId) return;
  loading.value = true;
  error.value = "";
  try {
    state.value = await onboardingApi.state();
    open.value = !state.value.finished;
    const [members, savedConfig, workflowItems] = await Promise.allSettled([
      spaceApi.listMembers(props.spaceId), onboardingApi.config(), workflowApi.list(),
    ]);
    if (members.status === "fulfilled") {
      const me = members.value.find((item) => item.user_id === userStore.user?.id);
      isAdmin.value = me?.role === "space_admin" || me?.role === "super_admin";
    }
    if (savedConfig.status === "fulfilled") {
      config.recommended_template = savedConfig.value.recommended_template || "";
      config.default_workflow_id = savedConfig.value.default_workflow_id;
    }
    if (workflowItems.status === "fulfilled") workflows.value = workflowItems.value;
  } catch { error.value = "上手进度暂时不可用，可刷新页面后重试。"; }
  finally { loading.value = false; }
}

async function completeCurrent() {
  if (!state.value?.current_step) return;
  saving.value = true;
  try {
    state.value = await onboardingApi.complete(state.value.current_step);
    if (state.value.finished) { open.value = false; ElMessage.success("首次 Agent 交付引导已完成"); }
  } finally { saving.value = false; }
}
async function skip() { state.value = await onboardingApi.skip(); open.value = false; }
async function replay() { if (!props.spaceId) return; state.value = await onboardingApi.replay(); open.value = true; }
function go(stepId: string) { open.value = false; router.push(destinations[stepId] || "/workspace"); }
async function saveConfig() {
  savingConfig.value = true;
  try {
    await onboardingApi.updateConfig({ recommended_template: config.recommended_template.trim() || null, default_workflow_id: config.default_workflow_id });
    settingsOpen.value = false; ElMessage.success("空间默认引导配置已保存");
  } finally { savingConfig.value = false; }
}

watch(() => props.spaceId, (value, previous) => { if (value && value !== previous) load(); });
onMounted(load);
defineExpose({ replay });
</script>

<style scoped lang="scss">
.guide-header, .guide-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.guide-header h2 { margin: 3px 0 0; font-size: 23px; }
.progress-label { padding: 6px 9px; color: var(--brand); background: var(--brand-soft); font: 700 12px var(--mono); }
.intro { margin: 0 0 16px; color: var(--text-muted); }
.guide-steps { display: flex; flex-direction: column; gap: 8px; margin: 0; padding: 0; list-style: none; }
.guide-steps li { display: grid; grid-template-columns: 34px 1fr auto; align-items: center; gap: 12px; min-height: 62px; padding: 10px 12px; border: 1px solid var(--border); background: var(--surface-soft); }
.guide-steps li.current { border-color: var(--brand); box-shadow: inset 3px 0 var(--brand); background: var(--brand-soft); }
.guide-steps li.done { opacity: .7; }
.step-index { width: 30px; height: 30px; display: grid; place-items: center; color: var(--text-muted); border: 1px solid var(--border); border-radius: 50%; font: 700 12px var(--mono); }
.done .step-index { color: #fff; border-color: var(--brand); background: var(--brand); }
.guide-steps strong, .guide-steps small { display: block; }
.guide-steps small { margin-top: 3px; color: var(--text-muted); }
.el-select { width: 100%; }
@media (max-width: 560px) { .guide-steps li { grid-template-columns: 34px 1fr; } .guide-steps li .el-button { grid-column: 2; justify-self: start; } .guide-footer { align-items: stretch; flex-direction: column-reverse; } .guide-footer > div { display: flex; flex-direction: column; gap: 6px; } }
</style>
