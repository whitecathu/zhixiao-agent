<template>
  <div class="paged-table">
    <el-table v-loading="loading" :data="rows" stripe @row-click="onRowClick">
      <slot />
    </el-table>
    <el-pagination
      class="pager"
      layout="total, sizes, prev, pager, next, jumper"
      :total="total"
      :current-page="page"
      :page-size="pageSize"
      :page-sizes="[10, 20, 50, 100]"
      @update:current-page="$emit('update:page', $event)"
      @update:page-size="$emit('update:pageSize', $event)"
    />
  </div>
</template>

<script setup lang="ts">
defineProps<{
  rows: any[];
  total: number;
  page: number;
  pageSize: number;
  loading?: boolean;
}>();
const emit = defineEmits<{
  "update:page": [value: number];
  "update:pageSize": [value: number];
  "row-click": [row: any];
}>();

function onRowClick(row: unknown) {
  emit("row-click", row);
}
</script>

<style scoped lang="scss">
.pager { margin-top: 12px; text-align: right; }
</style>