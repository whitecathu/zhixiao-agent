import { defineStore } from "pinia";
import { ref, computed } from "vue";

import { authApi } from "@/api/auth";
import type { User } from "@/types";
import {
  clearTokens, getAuthToken, getRefreshToken, getSpaceId,
  setSpaceId as saveSpaceId, setTokens, clearSpaceId,
} from "@/utils/auth";
import { spaceApi } from "@/api/space";
import type { Space } from "@/types";

export const useUserStore = defineStore("user", () => {
  const user = ref<User | null>(null);
  const spaces = ref<Space[]>([]);
  const currentSpaceId = ref<number | null>(getSpaceId());
  const isLogged = computed(() => !!getAuthToken());

  async function login(username: string, password: string) {
    const data = await authApi.login({ username, password });
    setTokens(data.access_token, data.refresh_token);
    user.value = data.user;
    await loadSpaces();
    if (spaces.value.length && !currentSpaceId.value) {
      switchSpace(spaces.value[0].id);
    }
  }

  async function register(payload: { username: string; email: string; password: string; nickname?: string }) {
    return authApi.register(payload);
  }

  async function loadSpaces() {
    spaces.value = await spaceApi.mine();
  }

  function switchSpace(id: number) {
    currentSpaceId.value = id;
    saveSpaceId(id);
  }

  async function logout() {
    const rt = getRefreshToken();
    if (rt) {
      try { await authApi.logout(rt); } catch { /* ignore */ }
    }
    clearTokens();
    clearSpaceId();
    user.value = null;
    spaces.value = [];
    currentSpaceId.value = null;
  }

  async function refreshMe() {
    if (!getAuthToken()) return;
    try {
      user.value = await authApi.me();
    } catch {
      clearTokens();
    }
  }

  return {
    user, spaces, currentSpaceId, isLogged,
    login, register, loadSpaces, switchSpace, logout, refreshMe,
  };
});