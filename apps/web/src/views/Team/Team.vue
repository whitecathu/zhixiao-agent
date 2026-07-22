<template>
  <section class="page-stack">
    <header class="page-heading">
      <div><p class="eyebrow">ORGANIZATION</p><h1>团队空间</h1><p>创建、切换与管理协作空间，所有工程任务都在当前空间内运行。</p></div>
      <el-button type="primary" @click="dialog = true">新建空间</el-button>
    </header>

    <el-card shadow="never">
      <el-table :data="userStore.spaces" class="clickable-table" stripe @row-click="onPick">
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="description" label="描述" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.id === userStore.currentSpaceId" type="success">当前使用</el-tag>
            <span v-else class="muted">可切换</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button v-if="row.id === userStore.currentSpaceId" disabled size="small" type="success">当前</el-button>
            <el-button v-else size="small" @click.stop="onPick(row)">切换</el-button>
            <el-button size="small" @click.stop="openManage(row)">管理</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!userStore.spaces.length" description="还没有工作空间，先创建一个吧" />
    </el-card>

    <el-dialog v-model="dialog" title="新建空间" width="480px" destroy-on-close>
      <el-form :model="form" label-position="top">
        <el-form-item label="名称"><el-input v-model="form.name" placeholder="例如：前端工程组" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="3" placeholder="可选，描述空间用途" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="loading" @click="submit">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="mgr" title="空间成员管理" width="640px">
      <el-form :inline="true" :model="member">
        <el-form-item label="用户ID"><el-input-number v-model="member.user_id" /></el-form-item>
        <el-form-item label="角色">
          <el-select v-model="member.role" style="width: 140px">
            <el-option label="空间管理员" value="space_admin" />
            <el-option label="成员" value="member" />
          </el-select>
        </el-form-item>
        <el-button type="primary" @click="addMember">邀请</el-button>
      </el-form>
      <el-table :data="members" style="margin-top: 12px">
        <el-table-column prop="user_id" label="用户 ID" />
        <el-table-column prop="role" label="角色" />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button link type="danger" @click="remove(row.user_id)">移除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";

import { useUserStore } from "@/stores/user";
import { spaceApi } from "@/api/space";

const userStore = useUserStore();
const dialog = ref(false);
const loading = ref(false);
const form = reactive({ name: "", description: "" });

const mgr = ref(false);
const managed = ref<number | null>(null);
const members = ref<any[]>([]);
const member = reactive({ user_id: 0, role: "member" });

onMounted(() => userStore.loadSpaces());

async function submit() {
  if (!form.name) {
    ElMessage.warning("请输入空间名称");
    return;
  }
  loading.value = true;
  try {
    await spaceApi.create({ ...form });
    ElMessage.success("创建成功");
    dialog.value = false;
    Object.assign(form, { name: "", description: "" });
    await userStore.loadSpaces();
  } finally {
    loading.value = false;
  }
}

function onPick(row: { id: number }) {
  userStore.switchSpace(row.id);
  ElMessage.success("已切换空间");
}

async function openManage(row: { id: number }) {
  managed.value = row.id;
  members.value = await spaceApi.listMembers(row.id);
  mgr.value = true;
}

async function addMember() {
  if (!managed.value || !member.user_id) return;
  await spaceApi.addMember(managed.value, { ...member });
  members.value = await spaceApi.listMembers(managed.value);
  ElMessage.success("已邀请");
}

async function remove(uid: number) {
  if (!managed.value) return;
  await spaceApi.removeMember(managed.value, uid);
  members.value = await spaceApi.listMembers(managed.value);
}
</script>
