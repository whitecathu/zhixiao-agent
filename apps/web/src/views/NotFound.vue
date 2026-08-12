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
  padding: 40px 36px;
  background: var(--surface);
  border: 1px solid var(--border);
  text-align: center;
  box-shadow: var(--shadow-sm);
  animation: rise 0.22s ease;
}

.not-found-card h1 {
  margin: 8px 0 10px;
  font-size: 32px;
  letter-spacing: -0.8px;
}

.actions {
  display: flex;
  justify-content: center;
  gap: 10px;
  margin-top: 24px;
  flex-wrap: wrap;
}

@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .not-found-card {
    animation: none;
  }
}
</style>
