<template>
  <div class="search-box">
    <el-input
      :model-value="modelValue"
      placeholder="语义检索企业知识（自然语言提问）"
      clearable
      :prefix-icon="Search"
      @update:model-value="onInput"
      @keyup.enter="$emit('search')"
    />
    <el-button type="primary" :loading="loading" @click="$emit('search')">检索</el-button>
    <el-tag v-if="hint" type="info" class="hint">{{ hint }}</el-tag>
  </div>
</template>

<script setup lang="ts">
import { ElInput, ElButton, ElTag } from "element-plus";
import { Search } from "@element-plus/icons-vue";

const props = defineProps<{
  modelValue: string;
  loading?: boolean;
  hint?: string;
  debounce?: number;
}>();
const emit = defineEmits<{
  "update:modelValue": [value: string];
  search: [];
}>();

let timer: number | undefined;
function onInput(v: string) {
  emit("update:modelValue", v);
  if (timer) clearTimeout(timer);
  timer = window.setTimeout(() => emit("search"), props.debounce ?? 400);
}
</script>

<style scoped lang="scss">
.search-box { display: flex; gap: 8px; align-items: center; }
.hint { margin-left: 12px; }
</style>