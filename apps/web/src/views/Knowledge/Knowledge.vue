<template>
  <div class="layout">
    <el-card class="left" shadow="never">
      <template #header>分类</template>
      <el-input v-model="filterText" placeholder="过滤分类" size="small" />
      <el-tree
        :data="categoryTree"
        :props="{ label: 'name', children: 'children' }"
        :filter-node-method="filterNode"
        ref="treeRef"
        @node-click="onCategory"
        node-key="id"
      />
      <div class="tag-wrap">
        <div class="title">标签</div>
        <el-tag v-for="t in tags" :key="t.id" class="tag"
                :effect="activeTags.includes(t.name) ? 'dark' : 'plain'"
                @click="toggleTag(t.name)">{{ t.name }}</el-tag>
      </div>
    </el-card>

    <div class="right">
      <SearchBox v-model="query" :loading="loading" @search="onSearch" hint="支持语义+关键词混合检索" />

      <PagedTable :rows="hits" :total="total" :page="page" :page-size="pageSize" :loading="loading"
                  @update:page="page = $event" @update:page-size="pageSize = $event">
        <el-table-column label="标题">
          <template #default="{ row }">
            <el-link @click="$router.push(`/knowledge/${row.knowledge_id}`)">{{ row.title }}</el-link>
          </template>
        </el-table-column>
        <el-table-column label="摘要" width="360">
          <template #default="{ row }">
            <span v-html="highlight(row.snippet)"></span>
          </template>
        </el-table-column>
        <el-table-column label="分类" prop="category_path" width="160" />
        <el-table-column label="质量分" width="100">
          <template #default="{ row }">{{ (row.quality_score * 100).toFixed(0) }}%</template>
        </el-table-column>
        <el-table-column label="综合分" width="100">
          <template #default="{ row }">{{ row.score.toFixed(3) }}</template>
        </el-table-column>
      </PagedTable>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from "vue";

import SearchBox from "@/components/common/SearchBox.vue";
import PagedTable from "@/components/common/PagedTable.vue";
import { knowledgeApi } from "@/api/knowledge";
import type { SearchHit } from "@/types";

const query = ref("");
const filterText = ref("");
const tags = ref<{ id: number; name: string }[]>([]);
const categoryTree = ref<any[]>([]);
const treeRef = ref();
const activeTags = ref<string[]>([]);
const page = ref(1);
const pageSize = ref(20);
const hits = ref<SearchHit[]>([]);
const total = ref(0);
const loading = ref(false);
const categoryFilter = ref<string | undefined>();

watch(filterText, (v) => treeRef.value?.filter(v));

function filterNode(value: string, data: { name: string }) {
  if (!value) return true;
  return data.name.includes(value);
}

function onCategory(node: { path?: string }) {
  categoryFilter.value = node?.path;
  onSearch();
}

function toggleTag(name: string) {
  if (activeTags.value.includes(name)) activeTags.value = activeTags.value.filter((t) => t !== name);
  else activeTags.value.push(name);
  onSearch();
}

async function loadFilters() {
  try { tags.value = await knowledgeApi.tags(); } catch { /* */ }
  const cats = await knowledgeApi.categories();
  // 构建树
  const map = new Map<number, any>();
  cats.forEach((c) => map.set(c.id, { ...c, children: [] }));
  const tree: any[] = [];
  cats.forEach((c) => {
    if (c.parent_id && map.has(c.parent_id)) map.get(c.parent_id).children.push(map.get(c.id));
    else tree.push(map.get(c.id));
  });
  categoryTree.value = tree;
}

async function onSearch() {
  loading.value = true;
  try {
    if (!query.value && !activeTags.value.length && !categoryFilter.value) {
      // 没条件则按分类列
      const data = await knowledgeApi.list({ page: page.value, page_size: pageSize.value,
                                              category_path: categoryFilter.value });
      hits.value = data.items.map((k) => ({
        knowledge_id: k.id, score: 0, title: k.title,
        summary: k.summary, snippet: (k.content || "").slice(0, 200),
        tags: k.tags || [], category_path: k.category_path || "",
        quality_score: Number(k.quality_score), source_task_id: k.source_task_id,
      })) as SearchHit[];
      total.value = data.total;
      return;
    }
    const payload: any = {
      query: query.value || activeTags.value.join(" ") || categoryFilter.value || "",
      page: page.value, page_size: pageSize.value,
    };
    if (activeTags.value.length) payload.tags = activeTags.value;
    if (categoryFilter.value) payload.category_path = categoryFilter.value;
    const res = await knowledgeApi.search(payload);
    hits.value = res.items; total.value = res.total;
  } finally { loading.value = false; }
}

watch([page, pageSize], onSearch);

function highlight(text: string) {
  if (!query.value) return text;
  return text.replace(new RegExp(query.value, "ig"), (m) => `<mark>${m}</mark>`);
}

loadFilters();
</script>

<style scoped lang="scss">
.layout { display: flex; gap: 12px; }
.left { width: 240px; flex: 0 0 240px; }
.right { flex: 1; }
.tag-wrap { margin-top: 16px; border-top: 1px solid var(--el-border-color); padding-top: 8px; }
.tag { cursor: pointer; margin: 4px 4px 0 0; }
.title { font-size: 13px; color: #909399; margin-bottom: 6px; }
mark { background: #ffd75e; }
</style>
