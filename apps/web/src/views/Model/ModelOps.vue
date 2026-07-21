<template>
  <section class="page-stack">
    <header class="page-heading"><div><p class="eyebrow">MODEL OPS</p><h1>模型与微调</h1><p>统一管理 OpenAI-compatible 模型路由、回退链和 LoRA 训练作业。</p></div><el-button type="primary" @click="modelDialog = true">添加模型</el-button></header>
    <el-tabs v-model="tab" class="surface-tabs">
      <el-tab-pane label="模型路由" name="models"><el-table :data="profiles"><el-table-column prop="name" label="名称"/><el-table-column prop="provider" label="Provider" width="130"/><el-table-column prop="model_name" label="模型"/><el-table-column prop="base_url" label="兼容端点"/><el-table-column prop="api_key_env" label="密钥环境变量"/><el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '启用' : '停用' }}</el-tag></template></el-table-column></el-table></el-tab-pane>
      <el-tab-pane label="LoRA 微调" name="finetune"><div class="tab-toolbar"><p>训练数据会先去敏并拆分训练/验证集，不上传模型权重到代码仓库。</p><el-button @click="fineTuneDialog = true">创建训练作业</el-button></div><el-table :data="jobs"><el-table-column label="作业"><template #default="{ row }">#{{ row.id }}</template></el-table-column><el-table-column prop="base_model" label="基础模型"/><el-table-column label="进度" width="260"><template #default="{ row }"><el-progress :percentage="Math.round(Number(row.metrics?.progress || 0) * 100)" :status="row.status === 'failed' ? 'exception' : row.status === 'succeeded' ? 'success' : undefined" /></template></el-table-column><el-table-column prop="status" label="状态" width="120"/></el-table></el-tab-pane>
    </el-tabs>
    <el-dialog v-model="modelDialog" title="添加模型配置" width="560px"><el-form label-position="top"><el-form-item label="名称"><el-input v-model="modelForm.name"/></el-form-item><el-form-item label="Provider"><el-select v-model="modelForm.provider" style="width:100%"><el-option v-for="item in providers" :key="item" :value="item" :label="item"/></el-select></el-form-item><el-form-item label="模型 ID"><el-input v-model="modelForm.model_name"/></el-form-item><el-form-item label="Base URL"><el-input v-model="modelForm.base_url"/></el-form-item><el-form-item label="密钥环境变量"><el-input v-model="modelForm.api_key_env" placeholder="例如 OPENAI_API_KEY"/></el-form-item></el-form><template #footer><el-button @click="modelDialog=false">取消</el-button><el-button type="primary" @click="saveModel">保存</el-button></template></el-dialog>
    <el-dialog v-model="fineTuneDialog" title="创建 LoRA 作业" width="520px"><el-form label-position="top"><el-form-item label="基础模型"><el-input v-model="fineTuneForm.base_model"/></el-form-item><el-form-item label="数据集制品 ID"><el-input-number v-model="fineTuneForm.dataset_artifact_id" :min="1"/></el-form-item></el-form><template #footer><el-button @click="fineTuneDialog=false">取消</el-button><el-button type="primary" @click="createFineTune">创建</el-button></template></el-dialog>
  </section>
</template>
<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { modelApi } from "@/api/agent";
import type { FineTuneJob, ModelProfile } from "@/types";
const tab = ref("models"); const profiles = ref<ModelProfile[]>([]); const jobs = ref<FineTuneJob[]>([]); const modelDialog = ref(false); const fineTuneDialog = ref(false); const providers: ModelProfile["provider"][] = ["openai", "xai", "deepseek", "qwen", "vllm"];
const modelForm = reactive<Partial<ModelProfile>>({ name: "", provider: "openai", model_name: "", base_url: "https://api.openai.com/v1", api_key_env: "", enabled: true }); const fineTuneForm = reactive<{ base_model: string; dataset_artifact_id?: number }>({ base_model: "", dataset_artifact_id: undefined });
async function load() { [profiles.value, jobs.value] = await Promise.all([modelApi.profiles(), modelApi.fineTunes()]); }
async function saveModel() { if (!modelForm.name || !modelForm.model_name || !modelForm.base_url) { ElMessage.warning("请填写名称、模型 ID 和 Base URL"); return; } await modelApi.create(modelForm); modelDialog.value=false; await load(); ElMessage.success("模型配置已保存"); }
async function createFineTune() { if (!fineTuneForm.base_model) { ElMessage.warning("请填写基础模型"); return; } await modelApi.createFineTune({ ...fineTuneForm, config: {} }); fineTuneDialog.value=false; await load(); ElMessage.success("训练作业已创建"); }
onMounted(load);
</script>
