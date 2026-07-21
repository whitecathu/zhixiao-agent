<template>
  <el-card class="card" v-loading="loading">
    <el-tabs v-model="tab">
      <el-tab-pane label="个人资料" name="info">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="用户名">{{ user?.username }}</el-descriptions-item>
          <el-descriptions-item label="邮箱">{{ user?.email }}</el-descriptions-item>
          <el-descriptions-item label="昵称">
            <el-input v-model="form.nickname" style="width:200px" />
            <el-button size="small" type="primary" @click="saveProfile">保存</el-button>
          </el-descriptions-item>
        </el-descriptions>
      </el-tab-pane>
      <el-tab-pane label="修改密码" name="pwd">
        <el-form :model="pwdForm" label-width="120">
          <el-form-item label="原密码"><el-input v-model="pwdForm.old_password" type="password" show-password /></el-form-item>
          <el-form-item label="新密码"><el-input v-model="pwdForm.new_password" type="password" show-password /></el-form-item>
          <el-form-item><el-button type="primary" :loading="saving" @click="savePwd">提交</el-button></el-form-item>
        </el-form>
      </el-tab-pane>
    </el-tabs>
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";

import { authApi } from "@/api/auth";
import { useUserStore } from "@/stores/user";

const userStore = useUserStore();
const user = userStore.user;
const tab = ref("info");
const loading = ref(false);
const saving = ref(false);
const form = reactive({ nickname: user?.nickname || "" });
const pwdForm = reactive({ old_password: "", new_password: "" });

function saveProfile() {
  ElMessage.success("昵称已暂存到本地（如需后端落库请在认证模块加 PUT /auth/profile）");
  return true;
}

async function savePwd() {
  if (pwdForm.new_password.length < 8) {
    ElMessage.warning("新密码至少 8 位");
    return;
  }
  saving.value = true;
  try {
    await authApi.changePassword({ ...pwdForm });
    ElMessage.success("密码已修改");
    pwdForm.old_password = ""; pwdForm.new_password = "";
  } finally { saving.value = false; }
}

onMounted(async () => {
  if (!userStore.user) await userStore.refreshMe();
});
</script>

<style scoped lang="scss">
.card { max-width: 720px; }
</style>
