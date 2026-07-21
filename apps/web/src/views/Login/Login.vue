<template>
  <div class="login-wrap">
    <div class="intro"><span class="intro-mark">Z</span><p class="eyebrow">FULL-STACK ENGINEERING AGENT</p><h1>从工程目标<br/>到可信交付</h1><p>仓库探测、计划审批、隔离实现、测试复核与知识沉淀，在一个可回放的执行闭环中完成。</p><div class="intro-loop"><span>PLAN</span><i>→</i><span>BUILD</span><i>→</i><span>VERIFY</span><i>→</i><span>SHIP</span></div></div>
    <el-card class="card">
      <template #header>
        <div class="title"><strong>智效工坊</strong><small>登录工程 Agent 控制台</small></div>
      </template>
      <el-tabs v-model="mode">
        <el-tab-pane label="登录" name="login">
          <el-form ref="loginFormRef" :model="loginForm" :rules="loginRules" label-width="0" @submit.prevent="submitLogin">
            <el-form-item prop="username">
              <el-input v-model="loginForm.username" placeholder="用户名或邮箱" :prefix-icon="User" />
            </el-form-item>
            <el-form-item prop="password">
              <el-input v-model="loginForm.password" type="password" show-password placeholder="密码" :prefix-icon="Lock" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="loading" style="width:100%" native-type="submit">登录</el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="注册" name="register">
          <el-form ref="regFormRef" :model="regForm" :rules="regRules" label-width="0" @submit.prevent="submitRegister">
            <el-form-item prop="username"><el-input v-model="regForm.username" placeholder="用户名" :prefix-icon="User" /></el-form-item>
            <el-form-item prop="email"><el-input v-model="regForm.email" placeholder="邮箱" :prefix-icon="Message" /></el-form-item>
            <el-form-item prop="password"><el-input v-model="regForm.password" type="password" show-password placeholder="密码" :prefix-icon="Lock" /></el-form-item>
            <el-form-item><el-button type="primary" :loading="loading" style="width:100%" native-type="submit">注册并登录</el-button></el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, FormInstance, FormRules } from "element-plus";
import { User, Lock, Message } from "@element-plus/icons-vue";

import { useUserStore } from "@/stores/user";

const userStore = useUserStore();
const router = useRouter();
const route = useRoute();

const mode = ref<"login" | "register">("login");
const loading = ref(false);

const loginFormRef = ref<FormInstance>();
const regFormRef = ref<FormInstance>();

const loginForm = reactive({ username: "", password: "" });
const regForm = reactive({ username: "", email: "", password: "" });

const loginRules: FormRules = {
  username: [{ required: true, message: "请输入用户名或邮箱", trigger: "blur" }],
  password: [{ required: true, min: 8, message: "密码至少 8 位", trigger: "blur" }],
};
const regRules: FormRules = {
  username: [{ required: true, min: 3, max: 64, message: "用户名 3-64 位", trigger: "blur" }],
  email: [{ required: true, type: "email", message: "邮箱格式错误", trigger: "blur" }],
  password: [
    { required: true, min: 8, message: "密码至少 8 位", trigger: "blur" },
    { validator: (_r, v: string, cb) => {
      if (!/[a-zA-Z]/.test(v) || !/\d/.test(v)) cb(new Error("密码必须包含字母与数字"));
      else cb();
    }, trigger: "blur" },
  ],
};

async function submitLogin() {
  if (!loginFormRef.value || !(await loginFormRef.value.validate())) return;
  loading.value = true;
  try {
    await userStore.login(loginForm.username, loginForm.password);
    ElMessage.success("登录成功");
    router.replace((route.query.redirect as string) || "/workspace");
  } catch (e) {
    /* 拦截器报错 */
  } finally {
    loading.value = false;
  }
}

async function submitRegister() {
  if (!regFormRef.value || !(await regFormRef.value.validate())) return;
  loading.value = true;
  try {
    await userStore.register({ ...regForm });
    await userStore.login(regForm.username, regForm.password);
    ElMessage.success("注册成功，已自动登录");
    router.replace("/workspace");
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped lang="scss">
.login-wrap { display:grid; grid-template-columns:minmax(420px,1fr) 480px; align-items:center; gap:70px; min-height:100vh; padding:8vw; color:#edf7ee; background-color:#101a13; background-image:radial-gradient(#35473a 1px,transparent 1px); background-size:22px 22px; }
.intro { max-width:680px; }.intro-mark { display:grid; place-items:center; width:48px;height:48px;margin-bottom:40px;color:#122016;background:#9eef6b;font:800 25px var(--mono);transform:rotate(-3deg);}.intro h1 { margin:8px 0 20px; font-size:58px; line-height:1.03; letter-spacing:-2px; }.intro>p:not(.eyebrow) { max-width:580px; color:#9cac9f; font-size:16px; line-height:1.8; }.intro-loop { display:flex; gap:13px; align-items:center; margin-top:38px; color:#a9ff83; font:700 11px var(--mono); letter-spacing:1px; }.intro-loop i { color:#53675a; font-style:normal; }.card { width:100%; padding:14px; color:var(--text); background:var(--surface); border:1px solid #53675a; box-shadow:18px 18px 0 rgba(66,88,72,.24); }.title strong,.title small { display:block; }.title strong { font-size:21px; }.title small { margin-top:4px; color:var(--text-muted); font-weight:400; }
@media(max-width:900px){.login-wrap{grid-template-columns:1fr;padding:28px}.intro{display:none}.card{max-width:480px;margin:auto}}
</style>
