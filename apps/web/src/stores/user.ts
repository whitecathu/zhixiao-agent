import { defineStore } from "pinia";
import { ref, computed } from "vue";

import { authApi } from "@/api/auth";
import type { SpaceMember, User } from "@/types";
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
  const currentRole = ref<SpaceMember["role"] | null>(null);
  const isLogged = computed(() => !!getAuthToken());
  const isSpaceAdmin = computed(() => currentRole.value === "space_admin" || currentRole.value === "super_admin");

  async function login(username: string, password: string) {
    const data = await authApi.login({ username, password });
    setTokens(data.access_token, data.refresh_token);
    user.value = data.user;
    try {
      await loadSpaces();
    } catch {
      spaces.value = [];
    }
    if (spaces.value.length && !currentSpaceId.value) {
      switchSpace(spaces.value[0].id);
    }
  }

  async function register(payload: { username: string; email: string; password: string; nickname?: string }) {
    return authApi.register(payload);
  }

  async function loadSpaces() {
    spaces.value = await spaceApi.mine();
    if (currentSpaceId.value) await loadCurrentRole(currentSpaceId.value);
  }

  function switchSpace(id: number) {
    currentSpaceId.value = id;
    saveSpaceId(id);
    void loadCurrentRole(id);
  }

  async function loadCurrentRole(spaceId = currentSpaceId.value) {
    if (!spaceId || !user.value) { currentRole.value = null; return; }
    try {
      const members = await spaceApi.listMembers(spaceId);
      currentRole.value = members.find((member) => member.user_id === user.value?.id)?.role || null;
    } catch { currentRole.value = null; }
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
    currentRole.value = null;
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
    user, spaces, currentSpaceId, currentRole, isLogged, isSpaceAdmin,
    login, register, loadSpaces, loadCurrentRole, switchSpace, logout, refreshMe,
  };
});
