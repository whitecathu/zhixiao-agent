<template>
  <section class="not-found page-stack">
    <div class="not-found-card">
      <p class="eyebrow">404</p>
      <h1>页面不存在</h1>
      <p class="muted">你访问的路径可能已变更，或链接已失效。</p>
      <div class="actions">
        <el-button type="primary" @click="$router.replace('/workspace')">返回工作台</el-button>
        <el-button @click="$router.back()">返回上一页</el-button>
      </div>
    </div>
  </section>
</template>

<style scoped lang="scss">
.not-found {
  min-height: calc(100dvh - 120px);
  display: grid;
  place-items: center;
}

.not-found-card {
  width: min(520px, 100%);
  padding: 36px;
  background: var(--surface);
  border: 1px solid var(--border);
  text-align: center;
}

.not-found-card h1 {
  margin: 8px 0 10px;
  font-size: 32px;
}

.actions {
  display: flex;
  justify-content: center;
  gap: 10px;
  margin-top: 24px;
}
</style>
