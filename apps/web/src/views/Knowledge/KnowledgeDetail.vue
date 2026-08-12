<template>
  <section class="page-stack" v-loading="loading">
    <header class="page-heading">
      <div>
        <p class="eyebrow">KNOWLEDGE ARTICLE</p>
        <h1>{{ data?.title || "知识详情" }}</h1>
        <p v-if="data?.summary">{{ data.summary }}</p>
        <p v-else class="muted">查看完整内容、标签与来源任务。</p>
      </div>
      <el-button @click="$router.back()">返回</el-button>
    </header>

    <el-card v-if="data" shadow="never" class="article-card">
      <div class="meta">
        <el-tag size="small" effect="plain">{{ data.type }}</el-tag>
        <el-tag v-for="t in data.tags || []" :key="t" size="small" effect="plain">{{ t }}</el-tag>
        <span v-if="data.source_task_id" class="muted src">
          来源任务
          <el-link type="primary" @click="$router.push(`/task/${data.source_task_id}`)">
            #{{ data.source_task_id }}
          </el-link>
        </span>
        <span v-if="data.category_path" class="muted">{{ data.category_path }}</span>
      </div>
      <div class="article-body">
        <MarkdownView :content="data.content" />
      </div>
    </el-card>

    <el-card v-else-if="!loading" shadow="never" class="empty-card">
      <el-empty description="未找到该知识条目">
        <el-button type="primary" @click="$router.push('/knowledge')">返回知识库</el-button>
      </el-empty>
    </el-card>
  </section>
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
  try {
    data.value = await knowledgeApi.get(Number(route.params.id));
  } finally {
    loading.value = false;
  }
}

onMounted(load);
watch(() => route.params.id, load);
</script>

<style scoped lang="scss">
.article-card {
  padding-bottom: 8px;
}

.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  padding-bottom: 16px;
  margin-bottom: 8px;
  border-bottom: 1px solid var(--border);
}

.src {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.article-body {
  max-width: 860px;
  line-height: 1.7;
}

.empty-card {
  border: 1px dashed var(--border);
  background: var(--surface-soft);
}
</style>
