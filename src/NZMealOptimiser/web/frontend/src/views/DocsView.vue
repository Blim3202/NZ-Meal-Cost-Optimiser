<template>
  <main class="shell shell-wide">
    <header class="hero">
      <div><p class="eyebrow">Reference</p><h1>Documentation</h1><p class="lede">The project's technical manuals, rendered straight from docs/technical.</p></div>
    </header>

    <div class="docs-layout">
      <nav class="panel docs-list" aria-label="Document list">
        <button v-for="doc in docs" :key="doc.name" type="button" class="side-item" :class="{ active: selected === doc.name }" @click="select(doc.name)">
          <span class="side-label">{{ doc.title }}</span><small>{{ doc.name }}</small>
        </button>
      </nav>

      <section class="panel doc-reader">
        <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
        <p v-else-if="loading" class="empty-state">Loading document…</p>
        <!-- eslint-disable-next-line vue/no-v-html — trusted repo markdown -->
        <article v-else-if="html" class="doc-body" v-html="html"></article>
        <p v-else class="empty-state">Pick a manual from the list.</p>
      </section>
    </div>
  </main>
</template>

<script>
import { computed, onMounted, ref } from 'vue';
import { marked } from 'marked';
import hljs from 'highlight.js/lib/core';
import python from 'highlight.js/lib/languages/python';
import bash from 'highlight.js/lib/languages/bash';
import json from 'highlight.js/lib/languages/json';

// Python-focused syntax highlighter (keeps the bundle lean) — expands easily
// by registering more languages from highlight.js/lib/languages.
hljs.registerLanguage('python', python);
hljs.registerLanguage('bash', bash);
hljs.registerLanguage('json', json);

const ESCAPE = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ESCAPE[c]);

const renderer = new marked.Renderer();
// Dual-signature: marked v12 passes (code, infostring); v13+ passes ({ text, lang }).
renderer.code = (codeOrToken, infostring) => {
  try {
    const isToken = typeof codeOrToken === 'object' && codeOrToken !== null;
    const text = isToken ? codeOrToken.text : codeOrToken;
    const rawLang = isToken ? codeOrToken.lang : infostring;
    const first = String(rawLang || '').trim().split(/\s+/)[0] || '';
    const language = first && hljs.getLanguage(first) ? first : '';
    const value = language ? hljs.highlight(text, { language }).value : hljs.highlightAuto(text).value;
    return `<pre class="hljs"><code class="language-${language || ''}">${value}</code></pre>`;
  } catch {
    const fallbackText = typeof codeOrToken === 'string' ? codeOrToken : (codeOrToken && codeOrToken.text) || '';
    return `<pre><code>${escapeHtml(fallbackText)}</code></pre>`;
  }
};

marked.use({ gfm: true, breaks: false, renderer });

export default {
  name: 'DocsView',
  setup() {
    const docs = ref([]);
    const selected = ref('');
    const markdown = ref('');
    const loading = ref(false);
    const error = ref('');

    const html = computed(() => (markdown.value ? marked.parse(markdown.value) : ''));

    async function select(name) {
      selected.value = name;
      loading.value = true;
      error.value = '';
      try {
        const response = await fetch(`/tech-docs/${encodeURIComponent(name)}`);
        if (!response.ok) throw new Error(`Could not load "${name}"`);
        markdown.value = await response.text();
      } catch (err) {
        error.value = err.message;
        markdown.value = '';
      } finally {
        loading.value = false;
      }
    }

    onMounted(async () => {
      try {
        const response = await fetch('/tech-docs');
        if (!response.ok) throw new Error('Could not load the document list');
        docs.value = await response.json();
        if (docs.value.length) select(docs.value[0].name);
      } catch (err) {
        error.value = err.message;
      }
    });

    return { docs, selected, html, loading, error, select };
  },
};
</script>
