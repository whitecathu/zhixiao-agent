<template>
  <section class="page-stack">
    <header class="page-heading">
      <div>
        <p class="eyebrow">CAPABILITIES</p>
        <h1>Agent 与工具</h1>
        <p>为角色分配指令和最小工具权限，所有越权操作进入审批队列。</p>
      </div>
      <el-button type="primary" @click="createAgent">新建 Agent</el-button>
    </header>

    <el-tabs v-model="tab" class="surface-tabs">
      <el-tab-pane label="Agent 定义" name="agents">
        <div v-if="agents.length" class="agent-grid">
          <article v-for="agent in agents" :key="agent.id" class="agent-card">
            <div class="agent-role">{{ agent.role }}</div>
            <div class="card-header">
              <h3>{{ agent.name }}</h3>
              <el-switch v-model="agent.enabled" disabled />
            </div>
            <p>{{ agent.system_prompt }}</p>
            <div class="chip-row">
              <el-tag v-for="tool in agent.tool_allowlist" :key="tool" effect="plain">{{ tool }}</el-tag>
            </div>
            <el-button text type="primary" @click="edit(agent)">复制为新定义</el-button>
          </article>
        </div>
        <el-empty v-else description="还没有 Agent 定义">
          <el-button type="primary" @click="createAgent">新建第一个 Agent</el-button>
        </el-empty>
      </el-tab-pane>

      <el-tab-pane label="工具注册表" name="tools">
        <el-table :data="tools" empty-text="暂无已注册工具">
          <el-table-column prop="name" label="工具" width="200" />
          <el-table-column prop="description" label="用途" />
          <el-table-column label="权限" width="130">
            <template #default="{ row }">
              <el-tag :type="permissionTag(row.permission)">{{ row.permission }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-drawer v-model="drawer" title="Agent 配置" size="520px">
      <el-form label-position="top">
        <el-form-item label="名称"><el-input v-model="draft.name" /></el-form-item>
        <el-form-item label="角色标识"><el-input v-model="draft.role" /></el-form-item>
        <el-form-item label="系统指令">
          <el-input v-model="draft.system_prompt" type="textarea" :rows="12" class="mono-input" />
        </el-form-item>
        <el-form-item label="工具白名单">
          <el-select v-model="draft.tool_allowlist" multiple filterable style="width: 100%">
            <el-option v-for="tool in tools" :key="tool.name" :label="tool.name" :value="tool.name" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="drawer = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-drawer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { definitionApi } from "@/api/agent";
import type { AgentDefinition, PermissionMode, ToolDefinition } from "@/types";

const tab = ref("agents");
const agents = ref<AgentDefinition[]>([]);
const tools = ref<ToolDefinition[]>([]);
const drawer = ref(false);
const saving = ref(false);
const draft = reactive<Partial<AgentDefinition>>({
  name: "",
  role: "",
  system_prompt: "",
  tool_allowlist: [],
  enabled: true,
});

function edit(agent: AgentDefinition) {
  Object.assign(draft, structuredClone(agent));
  drawer.value = true;
}

function createAgent() {
  Object.assign(draft, {
    id: undefined,
    name: "",
    role: "custom",
    system_prompt: "",
    tool_allowlist: [],
    enabled: true,
  });
  drawer.value = true;
}

async function save() {
  if (!draft.name?.trim() || !draft.system_prompt?.trim()) {
    ElMessage.warning("请填写名称和系统指令");
    return;
  }
  saving.value = true;
  try {
    await definitionApi.createAgent({ ...draft, id: undefined });
    drawer.value = false;
    await load();
    ElMessage.success("Agent 定义已创建");
  } finally {
    saving.value = false;
  }
}

function permissionTag(mode: PermissionMode) {
  return ({ read_only: "info", edit: "primary", execute: "warning", full: "danger" } as const)[mode];
}

async function load() {
  const [agentData, toolData] = await Promise.all([definitionApi.agents(), definitionApi.tools()]);
  agents.value = agentData;
  tools.value = toolData;
}

onMounted(load);
</script>
