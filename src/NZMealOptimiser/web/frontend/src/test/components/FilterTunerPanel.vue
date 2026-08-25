<template>
  <div class="filter-tuner">
    <!-- ── Card 1: ingredients + live match counters ─────────────────────── -->
    <section class="subcard">
      <h4>Ingredients</h4>
      <p class="subcard-hint">Recipe quantities with how many cached products survive the current keywords.</p>
      <ul class="tuning-list">
        <li v-for="ing in ingredients" :key="ing.term" :class="{ selected: ing.term === selectedTerm }">
          <button type="button" class="ing-line" @click="$emit('select-term', ing.term)">
            <span class="ing-name">{{ ing.term }}</span>
            <span class="ing-qty">{{ ing.qty }}</span>
            <span class="match-chip" :class="countClass(ing.term)" :title="countTitle(ing.term)">{{ countText(ing.term) }}</span>
          </button>
        </li>
      </ul>
    </section>

    <!-- ── Card 2: rule editor for the selected ingredient ───────────────── -->
    <section v-if="current" class="subcard">
      <h4>Edit rules <span class="chip-mini">{{ selectedTerm }}</span></h4>
      <p class="subcard-hint">Include: at least one keyword must appear in the product name (fuzzy singular/plural). Exclude: none may appear.</p>
      <div class="rule-line">
        <span class="rule-label must-include">Must include</span>
        <div class="rule-chips">
          <span v-for="(word, i) in current.includes" :key="`inc-${i}`" class="kw-chip kw-include">{{ word }}<button type="button" class="kw-x" :title="`Remove '${word}'`" @click="drop('includes', i)">✕</button></span>
          <input v-model="incDraft" class="kw-add kw-add-line" placeholder="add keyword ↵" @keydown.enter.prevent="push('includes')">
        </div>
      </div>
      <div class="rule-line">
        <span class="rule-label must-exclude">Must exclude</span>
        <div class="rule-chips">
          <span v-for="(word, i) in current.excludes" :key="`exc-${i}`" class="kw-chip kw-exclude">{{ word }}<button type="button" class="kw-x" :title="`Remove '${word}'`" @click="drop('excludes', i)">✕</button></span>
          <input v-model="excDraft" class="kw-add kw-add-line" placeholder="add keyword ↵" @keydown.enter.prevent="push('excludes')">
        </div>
      </div>
      <div class="rule-line ai-line">
        <span class="rule-label">AI instruction</span>
        <textarea class="ai-stub" disabled rows="2" placeholder="Custom AI instructions — planned, not functional yet"></textarea>
      </div>
    </section>

    <!-- ── Card 3: every store's products with matched/filtered pills ────── -->
    <section class="subcard subcard-wide">
      <h4>Products <span v-if="previewBusy" class="spinner spinner-inline"></span></h4>
      <p class="subcard-hint">Every cached product per supermarket, judged against the pending keywords. "Apply filters" bakes them into the store costs.</p>
      <div v-if="!storeGroups.length" class="empty-state">No cached products — run a comparison first.</div>
      <div v-else class="store-groups">
        <div v-for="group in storeGroups" :key="group.key" class="prod-store" :class="{ open: openStore === group.key }">
          <button type="button" class="prod-store-head" @click="openStore = openStore === group.key ? '' : group.key">
            <span class="badge" :class="badgeClass(group.company)">{{ companyLabel(group.company) }}</span>
            <strong>{{ group.store }}</strong>
            <span class="match-chip" :class="storeCountClass(group)" :title="`${group.filtered} of ${group.products.length} products excluded by pending filters`">{{ group.matched }}/{{ group.products.length }} matched</span>
            <span class="chevron">⌄</span>
          </button>
          <div v-if="openStore === group.key" class="prod-rows">
            <div class="prod-head" aria-hidden="true">
              <span>Ingredient</span>
              <span>Search result</span>
              <span>Brand</span>
              <span class="num">Quantity</span>
              <span class="num">Price</span>
              <span>Match status</span>
            </div>
            <div v-for="(p, i) in group.products" :key="`${p.sku}-${p.search_ingredient}-${i}`" class="prod-row" :class="{ 'row-invalid': !p.valid }">
              <span class="prod-term">{{ p.search_ingredient }}</span>
              <span class="prod-name" :title="p.returned_ingredient || 'No title'">{{ p.returned_ingredient || '—' }}</span>
              <span class="prod-brand" :title="p.brand">{{ p.brand || '—' }}</span>
              <span class="prod-size">{{ p.quantity }}{{ p.measurement_unit ? ` ${p.measurement_unit}` : '' }}</span>
              <span class="prod-price">{{ money(p.price) }}</span>
              <span class="pill" :class="p.valid ? 'pill-matched' : 'pill-filtered'" :title="p.valid ? 'Matched' : p.reason">{{ p.valid ? 'matched' : 'filtered' }}</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script>
import { computed, onUnmounted, ref, watch } from 'vue';

// Filter tuner tab: three subcards (ingredient counters / rule editor /
// per-store product audit). Live counts come from POST /optimise/{id}/
// filter_preview — a debounced dry-run against the cached rows, so editing
// keywords gives instant feedback while "Apply filters" stays authoritative.
export default {
  name: 'FilterTunerPanel',
  props: {
    jobId: { type: String, default: '' },
    active: { type: Boolean, default: false }, // a completed result exists
    ingredients: { type: Array, default: () => [] }, // [{term, qty}] requested order
    filters: { type: Object, default: () => ({}) }, // term -> {includes, excludes}
    stores: { type: Array, default: () => [] }, // [{company, store}] display order
    companies: { type: Array, required: true },
    selectedTerm: { type: String, default: '' },
  },
  emits: ['update-filters', 'select-term'],
  setup(props, { emit }) {
    const incDraft = ref('');
    const excDraft = ref('');
    const previewBusy = ref(false);
    const preview = ref(null); // {terms, products, unmatched_terms}
    const openStore = ref('');

    const current = computed(() => props.filters[props.selectedTerm] || { includes: [], excludes: [] });
    watch(() => props.selectedTerm, () => { incDraft.value = ''; excDraft.value = ''; });

    function push(kind) {
      const draft = kind === 'includes' ? incDraft : excDraft;
      const word = String(draft.value || '').trim().slice(0, 40);
      if (!word || current.value[kind].some((w) => w.toLowerCase() === word.toLowerCase())) { draft.value = ''; return; }
      emitUpdate(kind, [...current.value[kind], word]);
      draft.value = '';
    }
    function drop(kind, index) { emitUpdate(kind, current.value[kind].filter((_, i) => i !== index)); }
    function emitUpdate(kind, list) {
      emit('update-filters', props.selectedTerm, { includes: [...current.value.includes], excludes: [...current.value.excludes], [kind]: list });
    }

    // ── Debounced preview against the cached run ──────────────────────────
    let debounceTimer = null;
    const signature = computed(() => JSON.stringify(props.filters));
    watch([signature, () => props.active], () => schedulePreview(), { immediate: true });
    onUnmounted(() => { if (debounceTimer) clearTimeout(debounceTimer); });

    function schedulePreview() {
      if (!props.active || !props.jobId) return;
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(fetchPreview, 300);
    }
    async function fetchPreview() {
      if (!props.active || !props.jobId) return;
      previewBusy.value = true;
      try {
        const response = await fetch(`/optimise/${props.jobId}/filter_preview`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ingredient_filters: props.filters }),
        });
        preview.value = response.ok ? await response.json() : null;
      } catch { preview.value = null; } finally { previewBusy.value = false; }
    }

    function countsFor(term) {
      const c = preview.value?.terms?.[term];
      return c || null;
    }
    function countText(term) {
      const c = countsFor(term);
      return c ? `${c.matched}/${c.total} matched` : 'no data';
    }
    function countClass(term) {
      const c = countsFor(term);
      if (!c || !c.total) return 'm-none';
      if (!c.matched) return 'm-zero';
      return c.matched === c.total ? 'm-full' : 'm-part';
    }
    function countTitle(term) {
      const c = countsFor(term);
      if (!c) return 'No cached products for this search term';
      return `${c.matched} of ${c.total} cached products pass the pending filters`;
    }

    function storeCountClass(group) {
      if (!group.filtered) return 'm-full';
      if (!group.matched) return 'm-zero';
      return 'm-part';
    }

    const storeGroups = computed(() => {
      const products = preview.value?.products || [];
      const order = new Map(props.stores.map((s, i) => [`${s.company}|${s.store}`, i]));
      const map = new Map();
      for (const p of products) {
        const key = `${p.company}|${p.store}`;
        let g = map.get(key);
        if (!g) { g = { key, company: p.company, store: p.store, products: [], matched: 0, filtered: 0 }; map.set(key, g); }
        g.products.push(p);
        if (p.valid) g.matched += 1; else g.filtered += 1;
      }
      return [...map.values()].sort((a, b) => (order.get(a.key) ?? 999) - (order.get(b.key) ?? 999));
    });

    function companyLabel(company) { return props.companies.find((item) => item.id === company)?.label || company; }
    function badgeClass(company) { return `badge-${String(company).toLowerCase()}`; }
    function money(value) { return value === '' || value === null || value === undefined || Number.isNaN(Number(value)) ? '-' : `$${Number(value).toFixed(2)}`; }

    return {
      incDraft, excDraft, previewBusy, openStore, current,
      push, drop, countText, countClass, countTitle, storeCountClass,
      storeGroups, companyLabel, badgeClass, money,
    };
  },
};
</script>
