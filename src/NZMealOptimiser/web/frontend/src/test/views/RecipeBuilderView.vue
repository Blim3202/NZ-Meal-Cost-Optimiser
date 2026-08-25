<template>
  <main class="shell">
    <header class="hero">
      <div><p class="eyebrow">Under construction</p><h1>LLM Recipe Builder</h1><p class="lede">Paste a recipe link and let the LLM turn it into an optimisable dish breakdown.</p></div>
    </header>

    <section class="panel stub-panel">
      <span class="stub-icon" v-html="sparkIcon"></span>
      <h3>Coming soon</h3>
      <p class="lede">This page will accept a recipe URL (or pasted text), fetch it, and use Mistral to extract a structured ingredient list — search terms, quantities and units — ready to review in the dish builder.</p>

      <form class="stub-form" @submit.prevent>
        <label class="field"><span>Recipe URL</span><input type="url" placeholder="https://example.co.nz/recipe/butter-chicken" disabled></label>
        <button class="primary-button" type="submit" disabled><span class="spinner"></span>Build dish breakdown</button>
      </form>

      <ul class="roadmap">
        <li><strong>1 · Fetch &amp; clean</strong> — pull the page, strip boilerplate, isolate the ingredient section.</li>
        <li><strong>2 · LLM extraction</strong> — map free-text ingredients onto canonical units and store-search terms.</li>
        <li><strong>3 · Review</strong> — prefill the dashboard dish builder; you confirm rows before pricing.</li>
      </ul>
      <p class="hint">Plumbing already exists: <code>resolve_ingredients()</code> in <code>NZMealOptimiser/llm/llm_utils.py</code> handles curated → LLM → fallback resolution today.</p>
    </section>
  </main>
</template>

<script>
const sparkIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9z"/></svg>';

export default {
  name: 'RecipeBuilderView',
  setup() {
    return { sparkIcon };
  },
};
</script>
