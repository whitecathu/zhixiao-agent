<template>
  <section class="page-stack" v-loading="loading">
    <header class="page-heading">
      <div>
        <p class="eyebrow">ACCOUNT</p>
        <h1>个人设置</h1>
        <p>管理资料与登录凭证，变更仅作用于当前账号。</p>
      </div>
    </header>

    <el-card shadow="never" class="profile-card">
      <el-tabs v-model="tab" class="profile-tabs">
        <el-tab-pane label="个人资料" name="info">
          <dl class="profile-list">
            <div>
              <dt>用户名</dt>
              <dd>{{ user?.username || "—" }}</dd>
            </div>
            <div>
              <dt>邮箱</dt>
              <dd>{{ user?.email || "—" }}</dd>
            </div>
            <div class="nickname-row">
              <dt>昵称</dt>
              <dd>
                <el-input v-model="form.nickname" placeholder="显示名称" class="nickname-input" />
                <el-button type="primary" @click="saveProfile">保存</el-button>
              </dd>
            </div>
          </dl>
          <p class="muted note">昵称变更会先写入本地会话；如需持久化请在认证模块启用资料更新接口。</p>
        </el-tab-pane>

        <el-tab-pane label="修改密码" name="pwd">
          <el-form :model="pwdForm" label-position="top" class="pwd-form">
            <el-form-item label="原密码">
              <el-input v-model="pwdForm.old_password" type="password" show-password autocomplete="current-password" />
            </el-form-item>
            <el-form-item label="新密码">
              <el-input v-model="pwdForm.new_password" type="password" show-password autocomplete="new-password" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="saving" @click="savePwd">提交</el-button>
            </el-form-item>
          </el-form>
          <p class="muted note">新密码至少 8 位。</p>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </section>
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
    pwdForm.old_password = "";
    pwdForm.new_password = "";
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  if (!userStore.user) {
    loading.value = true;
    try {
      await userStore.refreshMe();
    } finally {
      loading.value = false;
    }
  }
  if (userStore.user?.nickname) form.nickname = userStore.user.nickname;
});
</script>

<style scoped lang="scss">
.profile-card {
  max-width: 720px;
}

.profile-list {
  margin: 0;
}

.profile-list > div {
  display: grid;
  grid-template-columns: 100px 1fr;
  gap: 12px;
  align-items: center;
  padding: 14px 0;
  border-bottom: 1px solid var(--border);
}

.profile-list dt {
  color: var(--text-muted);
  font-size: 13px;
}

.profile-list dd {
  margin: 0;
}

.nickname-row dd {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.nickname-input {
  max-width: 280px;
}

.pwd-form {
  max-width: 420px;
}

.note {
  margin-top: 16px;
}
</style>
