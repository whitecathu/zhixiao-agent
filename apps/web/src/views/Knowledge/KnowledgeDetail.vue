<template>
  <div v-loading="loading">
    <el-page-header @back="$router.back()" :content="data?.title" />
    <el-card v-if="data" class="box" shadow="never">
      <MarkdownView :content="data.content" />
      <div class="meta">
        <el-tag size="small">{{ data.type }}</el-tag>
        <el-tag v-for="t in data.tags || []" :key="t" size="small">{{ t }}</el-tag>
        <span class="src" v-if="data.source_task_id">来源任务
          <el-link @click="$router.push(`/task/${data.source_task_id}`)">#{{ data.source_task_id }}</el-link>
        </span>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import MarkdownView from "@/components/common/MarkdownView.vue";
import { knowledgeApi } from "@/api/knowledge";
import type { Knowledge } from "@/types";

const route = useRoute();
const data = ref<Knowledge | null>(null);
const loading = ref(false);

async function load() {
  loading.value = true;
  try { data.value = await knowledgeApi.get(Number(route.params.id)); }
  finally { loading.value = false; }
}

onMounted(load);
watch(() => route.params.id, load);
</script>

<style scoped lang="scss">
.box { margin-top: 12px; }
.meta { margin-top: 16px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; font-size: 13px; }
.src { color: #909399; }
</style>