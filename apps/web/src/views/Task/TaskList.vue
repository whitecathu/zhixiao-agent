<template>
  <section class="page-shell">
    <header class="page-heading">
      <div>
        <p class="eyebrow">ENGINEERING RUNS</p>
        <h1>工程任务</h1>
        <p>从目标到可应用 Diff 的完整 Agent 执行记录。</p>
      </div>
      <el-button type="primary" @click="dialogVisible = true">新建任务</el-button>
    </header>

    <el-card shadow="never" class="list-card table-chrome">
      <div class="ops">
        <el-input
          v-model="filter.keyword"
          placeholder="搜索任务标题或 ID"
          clearable
          :prefix-icon="Search"
          class="search-input"
        />
        <el-select v-model="filter.status" placeholder="状态筛选" clearable style="width: 140px">
          <el-option label="待审批" value="awaiting_approval" />
          <el-option label="排队中" value="queued" />
          <el-option label="执行中" value="running" />
          <el-option label="已完成" value="succeeded" />
          <el-option label="失败" value="failed" />
          <el-option label="已中断" value="interrupted" />
        </el-select>
      </div>

      <PagedTable
        class="clickable-table"
        :rows="rows"
        :total="total"
        :page="page"
        :page-size="pageSize"
        :loading="loading"
        @update:page="page = $event"
        @update:page-size="pageSize = $event"
        @row-click="onRowClick"
      >
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column label="任务">
          <template #default="{ row }">
            <strong>{{ row.title }}</strong>
            <div class="muted">{{ row.current_step || "等待执行步骤" }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="taskStatusTag(row.status)">{{ taskStatusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="permission_mode" label="权限" width="110" />
        <el-table-column prop="created_at" label="创建" width="190" />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button link @click.stop="$router.push(`/task/${row.id}`)">查看</el-button>
          </template>
        </el-table-column>
      </PagedTable>
    </el-card>

    <el-dialog v-model="dialogVisible" title="创建工程任务" width="720px" destroy-on-close>
      <el-form :model="form" label-position="top">
        <el-form-item label="代码仓库">
          <el-select v-model="form.repository_id" filterable placeholder="选择仓库" style="width: 100%">
            <el-option v-for="repo in repositories" :key="repo.id" :label="repo.name" :value="repo.id">
              <span>{{ repo.name }}</span>
              <small class="option-path">{{ repo.root_path || repo.clone_url }}</small>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="任务标题">
          <el-input v-model="form.title" placeholder="例如：为用户资料页增加头像上传" />
        </el-form-item>
        <el-form-item label="目标与验收标准">
          <el-input
            v-model="form.prompt"
            type="textarea"
            :rows="7"
            placeholder="描述期望行为、约束和必须通过的验证。Agent 会先生成计划。"
          />
        </el-form-item>
        <el-form-item label="权限模式">
          <el-select v-model="form.permission_mode" style="width: 100%">
            <el-option label="只读分析" value="read_only" />
            <el-option label="允许编辑" value="edit" />
            <el-option label="允许执行命令" value="execute" />
            <el-option label="完整权限（危险操作仍审批）" value="full" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">提交并跳转</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Search } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";

import PagedTable from "@/components/common/PagedTable.vue";
import { taskApi } from "@/api/task";
import { repositoryApi } from "@/api/agent";
import { taskStatusTag, taskStatusText } from "@/utils/status";
import type { PermissionMode, Repository, TaskItem } from "@/types";

const router = useRouter();
const route = useRoute();
const rows = ref<TaskItem[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const loading = ref(false);
const filter = reactive({ status: "", keyword: "" });
const dialogVisible = ref(false);
const submitting = ref(false);
const repositories = ref<Repository[]>([]);
const form = reactive<{ title: string; prompt: string; repository_id?: number; permission_mode: PermissionMode }>({
  title: "",
  prompt: "",
  repository_id: undefined,
  permission_mode: "edit",
});
if (typeof route.query.title === "string") form.title = route.query.title;
if (typeof route.query.goal === "string") form.prompt = route.query.goal;

repositoryApi.list().then((data) => {
  repositories.value = data;
  const requested = Number(route.query.repository);
  if (requested) form.repository_id = requested;
}).catch(() => undefined);
if (route.query.create === "1") dialogVisible.value = true;

async function load() {
  loading.value = true;
  try {
    const data = await taskApi.list();
    const keyword = filter.keyword.trim().toLowerCase();
    const filtered = data.filter((item) => {
      const statusOk = !filter.status || item.status === filter.status;
      const keywordOk =
        !keyword ||
        item.title.toLowerCase().includes(keyword) ||
        String(item.id).includes(keyword);
      return statusOk && keywordOk;
    });
    total.value = filtered.length;
    const start = (page.value - 1) * pageSize.value;
    rows.value = filtered.slice(start, start + pageSize.value);
  } finally {
    loading.value = false;
  }
}

watch([page, pageSize, filter], load, { immediate: true, deep: true });

function onRowClick(row: TaskItem) {
  router.push(`/task/${row.id}`);
}

async function submit() {
  if (!form.repository_id || form.title.trim().length < 2 || form.prompt.trim().length < 10) {
    ElMessage.warning("请选择仓库并填写标题与目标");
    return;
  }
  submitting.value = true;
  try {
    const t = await taskApi.create({
      repository_id: form.repository_id,
      title: form.title.trim(),
      prompt: form.prompt.trim(),
      permission_mode: form.permission_mode,
    });
    dialogVisible.value = false;
    router.push(`/task/${t.id}`);
  } finally {
    submitting.value = false;
  }
}
</script>

<style scoped lang="scss">
.list-card {
  padding-bottom: var(--space-2);
}

.ops {
  display: flex;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
  flex-wrap: wrap;
  align-items: center;
}

.search-input {
  flex: 1;
  min-width: 220px;
  max-width: 420px;
}

.option-path {
  float: right;
  color: var(--text-muted);
  margin-left: var(--space-6);
  font-size: var(--text-xs);
}
</style>
