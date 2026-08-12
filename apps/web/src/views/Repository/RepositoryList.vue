<template>
  <section class="page-stack">
    <header class="page-heading">
      <div>
        <p class="eyebrow">WORKSPACES</p>
        <h1>代码仓库</h1>
        <p>注册本地仓库，Agent 将在隔离 worktree 中探测、编辑与验证。</p>
      </div>
      <el-button type="primary" :icon="Plus" @click="dialog = true">接入仓库</el-button>
    </header>

    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="仓库路径必须位于服务端允许的工作区边界内；提交、推送和 PR 始终需要审批。"
      class="boundary-alert"
    />

    <div v-loading="loading" class="repository-grid">
      <article v-for="repo in repositories" :key="repo.id" class="repo-card">
        <div class="repo-top">
          <span class="repo-icon">{{ repo.name.slice(0, 2).toUpperCase() }}</span>
          <el-tag :type="repo.status === 'ready' ? 'success' : repo.status === 'error' ? 'danger' : 'warning'">
            {{ statusText(repo.status) }}
          </el-tag>
        </div>
        <h3>{{ repo.name }}</h3>
        <code>{{ repo.root_path || repo.clone_url }}</code>
        <div class="repo-meta">
          <span>默认分支 {{ repo.default_branch }}</span>
          <span>{{ repo.root_path ? "本地仓库" : "远程仓库" }}</span>
        </div>
        <div class="repo-actions">
          <el-button text type="primary" @click="createTask(repo)">创建任务</el-button>
        </div>
      </article>
    </div>

    <el-card v-if="!loading && !repositories.length" shadow="never" class="empty-card">
      <el-empty description="还没有接入代码仓库">
        <el-button type="primary" :icon="Plus" @click="dialog = true">接入第一个仓库</el-button>
      </el-empty>
    </el-card>

    <el-dialog v-model="dialog" title="接入代码仓库" width="560px" destroy-on-close>
      <el-form label-position="top">
        <el-form-item label="显示名称">
          <el-input v-model="form.name" placeholder="zhixiao-agent" />
        </el-form-item>
        <el-form-item label="仓库来源">
          <el-radio-group v-model="form.source">
            <el-radio-button value="local">服务端路径</el-radio-button>
            <el-radio-button value="remote">Git Clone URL</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.source === 'local'" label="服务端绝对路径">
          <el-input v-model="form.root_path" placeholder="/workspace/zhixiao-agent" />
        </el-form-item>
        <el-form-item v-else label="Git Clone URL">
          <el-input v-model="form.clone_url" placeholder="git@github.com:owner/repository.git" />
        </el-form-item>
        <el-form-item label="默认分支">
          <el-input v-model="form.default_branch" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">校验并接入</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { Plus } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { repositoryApi } from "@/api/agent";
import type { Repository } from "@/types";

const router = useRouter();
const repositories = ref<Repository[]>([]);
const loading = ref(false);
const saving = ref(false);
const dialog = ref(false);
const form = reactive({
  name: "",
  source: "local" as "local" | "remote",
  root_path: "",
  clone_url: "",
  default_branch: "main",
});

function statusText(status: string) {
  return ({ ready: "可用", indexing: "索引中", error: "异常" } as Record<string, string>)[status] || status;
}

async function load() {
  loading.value = true;
  try {
    repositories.value = await repositoryApi.list();
  } finally {
    loading.value = false;
  }
}

async function save() {
  const source = form.source === "local" ? form.root_path.trim() : form.clone_url.trim();
  if (!form.name.trim() || !source) {
    ElMessage.warning("请填写名称和仓库来源");
    return;
  }
  saving.value = true;
  try {
    await repositoryApi.create({
      name: form.name.trim(),
      default_branch: form.default_branch.trim() || "main",
      ...(form.source === "local" ? { root_path: source } : { clone_url: source }),
    });
    dialog.value = false;
    Object.assign(form, { name: "", source: "local", root_path: "", clone_url: "", default_branch: "main" });
    await load();
    ElMessage.success("仓库已接入");
  } finally {
    saving.value = false;
  }
}

function createTask(repo: Repository) {
  router.push({ path: "/tasks", query: { repository: repo.id, create: "1" } });
}

onMounted(load);
</script>

<style scoped lang="scss">
.boundary-alert {
  border-color: var(--border);
  background: var(--brand-soft);
}

.empty-card {
  border: 1px dashed var(--border);
  background: var(--surface-soft);
}
</style>
