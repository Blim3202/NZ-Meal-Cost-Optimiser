<template>
  <main class="shell">
    <header class="hero">
      <div><p class="eyebrow">Recipe library</p><h1>LLM Recipe Builder</h1><p class="lede">Paste a recipe's ingredient list and let Mistral turn it into an optimisable dish breakdown.</p></div>
    </header>

    <section class="panel builder-panel">
      <p class="notice-banner import-disclaimer" role="note">
        <span class="disclaimer-icon" aria-hidden="true">♡</span>
        <span>Please support recipe authors by visiting their sites — following the original instructions there guarantees accurate cooking steps, while LLM extraction can occasionally misread quantities. Only paste recipes you have legitimate access to.</span>
      </p>

      <form @submit.prevent="buildBreakdown">
        <div class="form-grid">
          <label class="field field-wide"><span>Paste your ingredient list</span>
            <textarea v-model="form.text" rows="7" maxlength="1000" placeholder="e.g.&#10;500g beef mince&#10;400g spaghetti pasta&#10;1 can chopped tomatoes (400g)&#10;1 brown onion, finely diced&#10;2 cloves garlic" :disabled="importing"></textarea>
          </label>
          <p class="hint paste-instructions field-wide">Add the ingredient list for your recipe above, then fill in the recipe name, portion size and optional notes below — skip any ads, stories or cooking steps.</p>
          <label class="field field-name"><span>Recipe name</span><input v-model.trim.lazy="form.name" maxlength="80" placeholder="e.g. spaghetti bolognese" required></label>
          <label class="field field-base"><span>Base portions</span><input v-model.number="form.basePortions" type="number" min="1" max="24" required></label>
          <label class="field field-wide"><span>Notes (optional)</span><input v-model.trim="form.notes" maxlength="100" placeholder="Chocolate chip cookies — bbcgoodfood.com"></label>
        </div>
        <div class="char-row"><span class="char-counter" :class="{ 'counter-limit': form.text.length >= TEXT_LIMIT }">{{ form.text.length }}/{{ TEXT_LIMIT }}</span></div>
        <div class="form-actions builder-actions">
          <button class="primary-button" type="submit" :disabled="importing || !canBuild"><span v-if="importing" class="spinner"></span>{{ importing ? 'Building…' : 'Build dish breakdown' }}</button>
          <span v-if="importing" class="hint">Mistral extracts the ingredients, then Gemini seeds product-filter rules — this can take 10–20 s.</span>
          <button type="button" class="ghost-button ghost-small builder-clear" title="Wipe the pasted text, recipe details and the extracted breakdown" :disabled="importing || !hasContent" @click="clearAll">Clear all</button>
        </div>
      </form>

      <transition name="toast-slide">
        <aside v-if="rejected" class="notice-banner rejection-banner" role="status">
          <span>Couldn't build this recipe — {{ rejected }}. Paste an ingredient list from the recipe's own site and try again.</span>
          <button type="button" class="chip-x rejection-x" title="Dismiss" @click="rejected = ''">✕</button>
        </aside>
      </transition>

      <p v-if="error" class="error-banner" role="alert">{{ error }}</p>

      <section v-if="result" class="result-block">
        <div class="section-heading">
          <div><p class="eyebrow">Extracted breakdown</p><h3>{{ form.name }}</h3><small class="muted-meta">{{ result.ingredients.length }} ingredient searches · {{ rulesCount }} filter rule{{ rulesCount === 1 ? '' : 's' }} seeded · base {{ Number(form.basePortions) || 4 }} portions</small></div>
          <button type="button" class="primary-button is-ready" @click="openInBuilder">Open in dish builder →</button>
        </div>
        <ul class="ingredient-list">
          <li v-for="(ing, index) in result.ingredients" :key="index"><span class="ing-name">{{ ing.search_term }}</span><span class="ing-qty">{{ displayQty(ing) }}</span></li>
        </ul>
        <ul v-if="result.warnings && result.warnings.length" class="warning-list">
          <li v-for="(warning, index) in result.warnings" :key="index">⚠ {{ warning }}</li>
        </ul>
        <p class="hint">Review every row in the dish builder before pricing — extraction can misread quantities.</p>
      </section>
    </section>
  </main>
</template>

<script>
import { computed, reactive, ref } from 'vue';

const TEXT_LIMIT = 1000;
const NOTES_LIMIT = 100;

export default {
  name: 'RecipeBuilderView',
  emits: ['open-draft'],
  setup(_props, { emit }) {
    const form = reactive({ text: '', name: '', basePortions: 4, notes: '' });
    const importing = ref(false);
    const error = ref('');
    const rejected = ref('');
    const result = ref(null);

    const canBuild = computed(() => !!form.text.trim() && !!String(form.name || '').trim());
    const rulesCount = computed(() => Object.keys(result.value?.filters || {}).length);
    const hasContent = computed(() => !!(String(form.text || '').trim()
      || String(form.name || '').trim() || String(form.notes || '').trim()
      || Number(form.basePortions) !== 4 || result.value));

    function displayQty(ing) {
      const qty = ing.quantity ?? '';
      const approx = ing.approx_quantity ? ` · ~${ing.approx_quantity} ${ing.approx_unit}` : '';
      return `${qty} ${ing.unit}${approx}`;
    }

    async function buildBreakdown() {
      if (importing.value || !canBuild.value) return;
      importing.value = true;
      error.value = '';
      rejected.value = '';
      result.value = null;
      try {
        const response = await fetch('/dishes/import_text', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            recipe_text: form.text.trim().slice(0, TEXT_LIMIT),
            dish_name: String(form.name || '').trim(),
            base_portions: Number(form.basePortions) || 4,
            notes: form.notes.trim().slice(0, NOTES_LIMIT),
          }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Could not build the dish breakdown');
        if (data.status === 'rejected') {
          // Gentle refusal (non-recipe text / injection attempt) — no red error.
          rejected.value = data.reason || 'the pasted text is not a recipe';
          return;
        }
        result.value = data;
      } catch (err) {
        error.value = err.message;
      } finally {
        importing.value = false;
      }
    }

    function openInBuilder() {
      emit('open-draft', {
        name: String(form.name || '').trim(),
        basePortions: Number(form.basePortions) || 4,
        ingredients: result.value?.ingredients || [],
        filters: result.value?.filters || {},
        notes: form.notes.trim().slice(0, NOTES_LIMIT),
      });
    }

    function clearAll() {
      if (!hasContent.value) return;
      if (!window.confirm('Clear the recipe builder?\nThe pasted ingredients, recipe details and the extracted breakdown will be removed.')) return;
      form.text = '';
      form.name = '';
      form.basePortions = 4;
      form.notes = '';
      result.value = null;
      rejected.value = '';
      error.value = '';
    }

    return {
      TEXT_LIMIT, form, importing, error, rejected, result,
      canBuild, rulesCount, hasContent, displayQty, buildBreakdown, openInBuilder, clearAll,
    };
  },
};
</script>
