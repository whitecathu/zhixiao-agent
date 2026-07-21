<template>
  <div class="md" v-html="rendered"></div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { marked } from "marked";
import hljs from "highlight.js";
import DOMPurify from "dompurify";
import "highlight.js/styles/github.css";

const props = defineProps<{ content: string }>();

const renderer = new marked.Renderer();
renderer.code = (code: string, info?: string) => {
  const requestedLanguage = info?.split(/\s+/)[0];
  const language = requestedLanguage && hljs.getLanguage(requestedLanguage) ? requestedLanguage : "plaintext";
  const highlighted = hljs.highlight(code, { language }).value;
  return `<pre><code class="hljs language-${language}">${highlighted}</code></pre>`;
};

const rendered = computed(() => DOMPurify.sanitize(marked.parse(props.content || "", {
  async: false,
  breaks: true,
  gfm: true,
  renderer,
}) as string));
</script>

<style scoped lang="scss">
.md { line-height: 1.7; }
.md :deep(h1), .md :deep(h2), .md :deep(h3) { margin: 12px 0 8px; }
.md :deep(pre) { padding: 12px; background: #f5f5f7; border-radius: 6px; overflow: auto; }
.md :deep(code) { font-family: "JetBrains Mono", Consolas, monospace; }
</style>
