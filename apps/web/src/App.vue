<template>
  <router-view />
</template>

<script setup lang="ts">
import { onMounted } from "vue";
import { useUserStore } from "@/stores/user";

const userStore = useUserStore();

onMounted(async () => {
  if (userStore.isLogged) {
    try {
      await userStore.refreshMe();
      await userStore.loadSpaces();
    } catch {
      /* invalid token - request 拦截器会清理 */
    }
  }
});
</script>