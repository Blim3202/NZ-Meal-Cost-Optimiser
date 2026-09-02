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
      <p class="subcard-hint">Tune name and brand keywords for this ingredient — brand filters take precedence over name filters.</p>

      <div class="ai-block">
        <div class="ai-block-head">
          <span class="rule-label">AI instruction</span>
          <span class="subcard-hint ai-block-hint">Universal sentence across all ingredients — e.g. "only red onions, no flavoured milk"</span>
        </div>
        <textarea
          v-model="aiText"
          class="ai-input ai-input-large"
          rows="3"
          maxlength="500"
          :disabled="!active || aiBusy"
          :placeholder="active ? 'e.g. only red onions, no flavoured milk, no cheese powder' : 'Run a comparison first, then describe the filter in plain English'"
        ></textarea>
        <div class="ai-actions">
          <button type="button" class="ghost-button ghost-small" :disabled="!canAiGenerate" @click="generateAi">
            <span v-if="aiBusy" class="spinner spinner-inline"></span>
            {{ aiBusy ? 'Asking AI…' : 'Generate filters' }}
          </button>
          <span class="subcard-hint ai-hint">{{ aiHint }}</span>
        </div>
        <p v-if="aiError" class="error-banner" role="alert">{{ aiError }}</p>
        <div v-if="aiSuggestion" class="ai-suggestion">
          <p class="subcard-hint">Review before applying — counts show net change per ingredient.</p>
          <ul class="ai-suggestion-list ai-suggestion-compact">
            <li v-for="row in aiCompactDiffs" :key="row.term" class="ai-suggestion-row ai-row-compact">
              <div class="ai-diff-main">
                <strong class="ai-diff-term">{{ row.term }}</strong>
                <span v-for="(w,i) in row.entry.includes" :key="`ai-inc-${row.term}-${i}`" class="kw-chip kw-include">{{ w }}</span>
                <span v-for="(w,i) in row.entry.excludes" :key="`ai-exc-${row.term}-${i}`" class="kw-chip kw-exclude">{{ w }}</span>
                <span v-for="(w,i) in row.entry.brand_includes" :key="`ai-binc-${row.term}-${i}`" class="kw-chip kw-brand-include">{{ w }}</span>
                <span v-for="(w,i) in row.entry.brand_excludes" :key="`ai-bexc-${row.term}-${i}`" class="kw-chip kw-brand-exclude">{{ w }}</span>
              </div>
              <span class="match-chip" :class="row.delta < 0 ? 'm-zero' : row.delta > 0 ? 'm-full' : 'm-part'" :title="`${row.kwCount} keyword(s) · ${row.cur.matched}/${row.cur.total} → ${row.ai.matched}/${row.ai.total}`">{{ row.deltaText }} · {{ row.ai.matched }}/{{ row.ai.total }}</span>
            </li>
          </ul>
          <div class="ai-suggestion-actions">
            <button type="button" class="primary-button" @click="applyAi">Apply these filters</button>
            <button type="button" class="ghost-button ghost-small" @click="dismissAi">Dismiss</button>
          </div>
        </div>
        <div v-if="aiSuggestion && !Object.keys(aiSuggestion.compiled_filters || {}).length" class="subcard-hint">No keyword changes suggested for this instruction.</div>
      </div>

      <div class="ai-block auto-refine-block">
        <div class="ai-actions">
          <button type="button" class="ghost-button ghost-small" :disabled="!canAutoCull" @click="autoCull">
            <span v-if="autoBusy" class="spinner spinner-inline"></span>
            {{ autoBusy ? 'Refining…' : 'Auto refine filters' }}
          </button>
          <span v-if="autoHint" class="subcard-hint ai-hint">{{ autoHint }}</span>
          <span v-else class="subcard-hint ai-block-hint">About 5–8 filters per ingredient — strongest irrelevant terms first</span>
        </div>
        <p v-if="autoError" class="error-banner" role="alert">{{ autoError }}</p>
        <div v-if="autoSuggestion" class="ai-suggestion">
          <p class="subcard-hint">Click on a chip to adjust suggested filters</p>
          <ul class="ai-suggestion-list ai-suggestion-compact">
            <li v-for="row in autoCompactDiffs" :key="`auto-${row.term}`" class="ai-suggestion-row ai-row-compact">
              <div class="ai-diff-main">
                <strong class="ai-diff-term">{{ row.term }}</strong>
                <button v-for="(w,i) in row.entry.excludes" :key="`auto-exc-${row.term}-${i}`" type="button" class="kw-chip kw-exclude is-toggle" :class="{ 'is-rejected': isAutoRejected(row.term,'excludes',w) }" :title="isAutoRejected(row.term,'excludes',w) ? 'Click to re-include' : 'Click to exclude'" :aria-pressed="!isAutoRejected(row.term,'excludes',w)" @click="toggleAutoChip(row.term,'excludes',w)">{{ w }}</button>
                <button v-for="(w,i) in row.entry.brand_excludes" :key="`auto-bexc-${row.term}-${i}`" type="button" class="kw-chip kw-brand-exclude is-toggle" :class="{ 'is-rejected': isAutoRejected(row.term,'brand_excludes',w) }" :title="isAutoRejected(row.term,'brand_excludes',w) ? 'Click to re-include' : 'Click to exclude'" :aria-pressed="!isAutoRejected(row.term,'brand_excludes',w)" @click="toggleAutoChip(row.term,'brand_excludes',w)">{{ w }}</button>
              </div>
              <span class="match-chip" :class="row.delta < 0 ? 'm-zero' : row.delta > 0 ? 'm-full' : 'm-part'" :title="`${row.effKwCount}/${row.kwCount} active · ${row.cur.matched}/${row.cur.total} → ${row.effMatched}/${row.effTotal}`">{{ row.deltaText }} · {{ row.effMatched }}/{{ row.effTotal }}</span>
            </li>
          </ul>
          <div class="ai-suggestion-actions">
            <button type="button" class="primary-button" @click="applyAuto">Apply these filters</button>
            <button type="button" class="ghost-button ghost-small" @click="dismissAuto">Dismiss</button>
          </div>
        </div>
        <div v-if="autoSuggestion && !Object.keys(autoSuggestion.compiled_filters || {}).length" class="subcard-hint">No irrelevant terms found for this dish.</div>
      </div>

      <div class="rule-line">
        <span class="rule-label must-include">Include Term</span>
        <div class="rule-chips">
          <span v-for="(word, i) in current.includes" :key="`inc-${i}`" class="kw-chip kw-include">{{ word }}<button type="button" class="kw-x" :title="`Remove '${word}'`" @click="drop('includes', i)">✕</button></span>
          <div class="kw-input-wrap" :class="{ 'is-filled': !!incDraft, 'is-duplicate': incDuplicate }">
            <span class="kw-input-icon" aria-hidden="true">+</span>
            <input v-model="incDraft" class="kw-add kw-add-line" placeholder="add term ↵" :aria-label="`Add include term for ${selectedTerm}`" @keydown.enter.prevent="push('includes')">
          </div>
        </div>
      </div>

      <div class="rule-line">
        <span class="rule-label must-exclude">Exclude Term</span>
        <div class="rule-chips">
          <span v-for="(word, i) in current.excludes" :key="`exc-${i}`" class="kw-chip kw-exclude">{{ word }}<button type="button" class="kw-x" :title="`Remove '${word}'`" @click="drop('excludes', i)">✕</button></span>
          <div class="kw-input-wrap" :class="{ 'is-filled': !!excDraft, 'is-duplicate': excDuplicate }">
            <span class="kw-input-icon" aria-hidden="true">+</span>
            <input v-model="excDraft" class="kw-add kw-add-line" placeholder="add term ↵" :aria-label="`Add exclude term for ${selectedTerm}`" @keydown.enter.prevent="push('excludes')">
          </div>
        </div>
      </div>

      <div class="rule-line">
        <span class="rule-label brand-include">Include Brand</span>
        <div class="rule-chips">
          <span v-for="(b, i) in current.brand_includes" :key="`binc-${i}`" class="kw-chip kw-brand-include">{{ b }}<button type="button" class="kw-x" :title="`Remove '${b}'`" @click="drop('brand_includes', i)">✕</button></span>
          <BrandAutocomplete
            v-model="brandIncDraft"
            :suggestions="availableBrands"
            :is-duplicate="brandIncDuplicate"
            placeholder="add brand ↵"
            :aria-label="`Add include brand for ${selectedTerm}`"
            @commit="commitBrand('brand_includes', $event)"
            @enter="commitBrand('brand_includes', $event)"
          />
        </div>
      </div>

      <div class="rule-line">
        <span class="rule-label brand-exclude">Exclude Brand</span>
        <div class="rule-chips">
          <span v-for="(b, i) in current.brand_excludes" :key="`bexc-${i}`" class="kw-chip kw-brand-exclude">{{ b }}<button type="button" class="kw-x" :title="`Remove '${b}'`" @click="drop('brand_excludes', i)">✕</button></span>
          <BrandAutocomplete
            v-model="brandExcDraft"
            :suggestions="availableBrands"
            :is-duplicate="brandExcDuplicate"
            placeholder="add brand ↵"
            :aria-label="`Add exclude brand for ${selectedTerm}`"
            @commit="commitBrand('brand_excludes', $event)"
            @enter="commitBrand('brand_excludes', $event)"
          />
        </div>
      </div>
      <div class="subcard-hint filter-legend">
        <ul style="margin:0; padding-left:1.25em; list-style:disc; display:grid; gap:2px;">
          <li><strong>Include Term</strong>: all must appear. <strong>Exclude Term</strong>: any match hides. Fuzzy (<em>carrot</em> = <em>carrots</em>).</li>
          <li><strong>Include Brand</strong> (OR) / <strong>Exclude Brand</strong> — any match decides; checks brand field only.</li>
          <li>Brand checked first — overrides name filter. Filtered = visible but not considered.</li>
        </ul>
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
import BrandAutocomplete from './BrandAutocomplete.vue';

const MAX_KW = 15;
const MAX_LEN = 40;

function normalize(list) {
  return list.map((w) => String(w).trim().toLowerCase());
}

// Filter tuner tab: three subcards (ingredient counters / rule editor /
// per-store product audit). Live counts come from POST /optimise/{id}/
// filter_preview — a debounced dry-run against the cached rows, so editing
// keywords gives instant feedback while "Apply filters" stays authoritative.
export default {
  name: 'FilterTunerPanel',
  components: { BrandAutocomplete },
  props: {
    jobId: { type: String, default: '' },
    active: { type: Boolean, default: false },
    ingredients: { type: Array, default: () => [] },
    filters: { type: Object, default: () => ({}) },
    stores: { type: Array, default: () => [] },
    companies: { type: Array, required: true },
    selectedTerm: { type: String, default: '' },
    dish: { type: String, default: '' },
  },
  emits: ['update-filters', 'select-term', 'pipeline-log'],
  setup(props, { emit }) {
    const incDraft = ref('');
    const excDraft = ref('');
    const brandIncDraft = ref('');
    const brandExcDraft = ref('');
    const previewBusy = ref(false);
    const preview = ref(null);
    const openStore = ref('');
    const aiText = ref('');
    const aiBusy = ref(false);
    const aiError = ref('');
    const aiSuggestion = ref(null);
    const autoBusy = ref(false);
    const autoError = ref('');
    const autoSuggestion = ref(null);

    // Normalise the entry shape so every field is always an array. Seeded
    // entries from data/dish_filters.json only carry includes/excludes —
    // without this, downstream code (e.g. `normalize(current.brand_includes)`)
    // throws on terms that have never had a brand filter added, and the
    // throw collapses the rule-editor render.
    const current = computed(() => {
      const entry = props.filters[props.selectedTerm];
      if (!entry) return { includes: [], excludes: [], brand_includes: [], brand_excludes: [] };
      return {
        includes: entry.includes || [],
        excludes: entry.excludes || [],
        brand_includes: entry.brand_includes || [],
        brand_excludes: entry.brand_excludes || [],
      };
    });
    watch(
      () => props.selectedTerm,
      () => { incDraft.value = ''; excDraft.value = ''; brandIncDraft.value = ''; brandExcDraft.value = ''; }
    );

    const incDuplicate = computed(() => {
      const w = incDraft.value.trim().toLowerCase();
      return !!w && (normalize(current.value.includes).includes(w) || normalize(current.value.excludes).includes(w));
    });
    const excDuplicate = computed(() => {
      const w = excDraft.value.trim().toLowerCase();
      return !!w && (normalize(current.value.excludes).includes(w) || normalize(current.value.includes).includes(w));
    });
    const brandIncDuplicate = computed(() => {
      const w = brandIncDraft.value.trim().toLowerCase();
      return !!w && (normalize(current.value.brand_includes).includes(w) || normalize(current.value.brand_excludes).includes(w));
    });
    const brandExcDuplicate = computed(() => {
      const w = brandExcDraft.value.trim().toLowerCase();
      return !!w && (normalize(current.value.brand_excludes).includes(w) || normalize(current.value.brand_includes).includes(w));
    });

    function push(kind) {
      const draft = kind === 'includes' ? incDraft
        : kind === 'excludes' ? excDraft
        : kind === 'brand_includes' ? brandIncDraft
        : brandExcDraft;
      const word = String(draft.value || '').trim().slice(0, MAX_LEN);
      if (!word) { draft.value = ''; return; }
      const lower = word.toLowerCase();
      const opposite = kind === 'includes' ? 'excludes' : kind === 'excludes' ? 'includes' : kind === 'brand_includes' ? 'brand_excludes' : 'brand_includes';
      if (normalize(current.value[kind] || []).includes(lower) || normalize(current.value[opposite] || []).includes(lower)) { draft.value = ''; return; }
      if ((current.value[kind] || []).length >= MAX_KW) { draft.value = ''; return; }
      const next = { ...current.value, [kind]: [...(current.value[kind] || []), word].slice(0, MAX_KW) };
      emit('update-filters', props.selectedTerm, next);
      draft.value = '';
    }
    function commitBrand(kind, value) {
      const draft = kind === 'brand_includes' ? brandIncDraft : brandExcDraft;
      draft.value = String(value || '').trim();
      push(kind);
    }
    function drop(kind, index) {
      const next = { ...current.value, [kind]: (current.value[kind] || []).filter((_, i) => i !== index) };
      emit('update-filters', props.selectedTerm, next);
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

    // Available brands for autocomplete — pulled from the preview's product
    // rows (already fetched and debounced) and filtered to the currently
    // selected ingredient so the user only sees brands that could plausibly
    // match. Empty until the first run, in which case the autocomplete
    // degrades to a plain text input (free entry).
    const availableBrands = computed(() => {
      const products = preview.value?.products || [];
      const term = props.selectedTerm;
      const set = new Set();
      for (const p of products) {
        if (term && p.search_ingredient !== term) continue;
        if (typeof p.brand === 'string' && p.brand.trim()) set.add(p.brand.trim());
      }
      return [...set].sort();
    });

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

    const canAiGenerate = computed(() => props.active && !!props.jobId && !aiBusy.value && !!aiText.value.trim() && aiText.value.trim().length <= 500);
    const aiHint = computed(() => {
      if (!props.active || !props.jobId) return 'Run a comparison to enable';
      if (!aiText.value.trim()) return 'Type a sentence like "only red onions, no flavoured milk"';
      if (aiText.value.trim().length > 500) return 'Max 500 characters';
      return 'Applies across all ingredients';
    });
    const canAutoCull = computed(() => props.active && !!props.jobId && !autoBusy.value && !aiBusy.value);
    const autoHint = computed(() => {
      if (!props.active || !props.jobId) return 'Run a comparison to enable';
      return '';
    });
    const aiPreviewCounts = computed(() => aiSuggestion.value?.preview?.terms || null);
    const aiCompactDiffs = computed(() => {
      const compiled = aiSuggestion.value?.compiled_filters || {};
      const aiTerms = aiSuggestion.value?.preview?.terms || {};
      const curTerms = preview.value?.terms || {};
      return Object.entries(compiled).map(([term, entry]) => {
        const kwCount = (entry.includes?.length || 0) + (entry.excludes?.length || 0) + (entry.brand_includes?.length || 0) + (entry.brand_excludes?.length || 0);
        const cur = curTerms[term] || { matched: 0, total: 0 };
        const ai = aiTerms[term] || { matched: cur.matched, total: cur.total };
        const delta = ai.matched - cur.matched;
        const deltaText = delta > 0 ? `+${delta}` : `${delta}`;
        return { term, entry, kwCount, cur, ai, delta, deltaText };
      });
    });
    const autoRejected = ref(new Set());
    function autoKey(term, kind, word) { return `${term}::${kind}::${String(word).toLowerCase()}`; }
    function isAutoRejected(term, kind, word) { return autoRejected.value.has(autoKey(term, kind, word)); }
    function toggleAutoChip(term, kind, word) {
      const k = autoKey(term, kind, word);
      const next = new Set(autoRejected.value);
      if (next.has(k)) next.delete(k); else next.add(k);
      autoRejected.value = next;
    }
    function isWordInText(word, text) {
      const lw = String(word).toLowerCase().trim();
      const lt = String(text || '').toLowerCase();
      if (!lw) return false;
      if (lt.includes(lw)) return true;
      if (lw.endsWith('s') && lt.includes(lw.slice(0, -1))) return true;
      if (!lw.endsWith('s') && lt.includes(`${lw}s`)) return true;
      return false;
    }
    function validForFilters(p, f) {
      const title = String(p.returned_ingredient || '');
      const brand = String(p.brand || '');
      if ((f.brand_includes || []).length && !(f.brand_includes || []).some((w) => isWordInText(w, brand))) return false;
      if ((f.brand_excludes || []).some((w) => isWordInText(w, brand))) return false;
      for (const w of f.includes || []) if (!isWordInText(w, title)) return false;
      for (const w of f.excludes || []) if (isWordInText(w, title)) return false;
      return true;
    }
    const autoEffectiveCounts = computed(() => {
      if (!autoSuggestion.value) return {};
      const products = autoSuggestion.value.preview?.products || preview.value?.products || [];
      const compiled = autoSuggestion.value.compiled_filters || {};
      const counts = {};
      const totals = {};
      for (const p of products) {
        const term = p.search_ingredient;
        totals[term] = (totals[term] || 0) + 1;
      }
      for (const [term, entry] of Object.entries(compiled)) {
        const cur = props.filters[term] || { includes: [], excludes: [], brand_includes: [], brand_excludes: [] };
        const effEx = (entry.excludes || []).filter((w) => !isAutoRejected(term, 'excludes', w));
        const effBe = (entry.brand_excludes || []).filter((w) => !isAutoRejected(term, 'brand_excludes', w));
        const eff = {
          includes: cur.includes || [],
          excludes: [...(cur.excludes || []), ...effEx],
          brand_includes: cur.brand_includes || [],
          brand_excludes: [...(cur.brand_excludes || []), ...effBe],
        };
        let matched = 0;
        for (const p of products) {
          if (p.search_ingredient !== term) continue;
          if (validForFilters(p, eff)) matched += 1;
        }
        counts[term] = { matched, total: totals[term] || 0 };
      }
      return counts;
    });
    const autoCompactDiffs = computed(() => {
      const compiled = autoSuggestion.value?.compiled_filters || {};
      const curTerms = preview.value?.terms || {};
      const effTerms = autoEffectiveCounts.value;
      return Object.entries(compiled).map(([term, entry]) => {
        const kwCount = (entry.excludes?.length || 0) + (entry.brand_excludes?.length || 0);
        const effEx = (entry.excludes || []).filter((w) => !isAutoRejected(term, 'excludes', w)).length;
        const effBe = (entry.brand_excludes || []).filter((w) => !isAutoRejected(term, 'brand_excludes', w)).length;
        const effKwCount = effEx + effBe;
        const cur = curTerms[term] || { matched: 0, total: 0 };
        const eff = effTerms[term] || cur;
        const delta = eff.matched - cur.matched;
        const deltaText = delta > 0 ? `+${delta}` : `${delta}`;
        return { term, entry, kwCount, effKwCount, cur, effMatched: eff.matched, effTotal: eff.total, ai: eff, delta, deltaText };
      });
    });

    async function parseJsonResponse(response) {
      const text = await response.text();
      let data = {};
      if (text) {
        try { data = JSON.parse(text); } catch { throw new Error(text.slice(0, 400) || 'Server error'); }
      }
      if (!response.ok) throw new Error(data.detail || text.slice(0, 400) || 'Request failed');
      return data;
    }
    async function generateAi() {
      if (!canAiGenerate.value) return;
      aiBusy.value = true;
      aiError.value = '';
      aiSuggestion.value = null;
      emit('pipeline-log', { kind: 'phase', co: 'FILTERS', text: `compiling instruction "${aiText.value.trim().slice(0, 80)}"…` });
      try {
        const response = await fetch(`/optimise/${props.jobId}/ai_filter_preview`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ instruction: aiText.value.trim() }),
        });
        aiSuggestion.value = await parseJsonResponse(response);
        if (aiSuggestion.value?.warnings?.length) {
          for (const w of aiSuggestion.value.warnings) emit('pipeline-log', { kind: 'warn', co: 'FILTERS', text: w });
        } else {
          const n = Object.keys(aiSuggestion.value?.compiled_filters || {}).length;
          emit('pipeline-log', { kind: 'ok', co: 'FILTERS', text: n ? `compiled ${n} term(s) — no warnings` : 'no filters suggested — no warnings' });
        }
      } catch (err) {
        aiError.value = err.message;
        emit('pipeline-log', { kind: 'err', co: 'FILTERS', text: err.message });
      } finally {
        aiBusy.value = false;
      }
    }
    function applyAi() {
      const filters = aiSuggestion.value?.compiled_filters || {};
      for (const [term, entry] of Object.entries(filters)) {
        const existing = props.filters[term] || { includes: [], excludes: [], brand_includes: [], brand_excludes: [] };
        const merged = {
          includes: [...new Set([...(existing.includes || []), ...(entry.includes || [])])],
          excludes: [...new Set([...(existing.excludes || []), ...(entry.excludes || [])])],
          brand_includes: [...new Set([...(existing.brand_includes || []), ...(entry.brand_includes || [])])],
          brand_excludes: [...new Set([...(existing.brand_excludes || []), ...(entry.brand_excludes || [])])],
        };
        const clean = {
          includes: merged.includes.filter(Boolean).slice(0, MAX_KW),
          excludes: merged.excludes.filter(Boolean).slice(0, MAX_KW),
          brand_includes: merged.brand_includes.filter(Boolean).slice(0, MAX_KW),
          brand_excludes: merged.brand_excludes.filter(Boolean).slice(0, MAX_KW),
        };
        emit('update-filters', term, clean);
      }
      aiSuggestion.value = null;
      aiText.value = '';
    }
    function dismissAi() {
      aiSuggestion.value = null;
      aiError.value = '';
    }
    async function autoCull() {
      if (!canAutoCull.value) return;
      autoBusy.value = true;
      autoError.value = '';
      autoSuggestion.value = null;
      autoRejected.value = new Set();
      const dishLabel = (props.dish || '').trim() || 'this dish';
      emit('pipeline-log', { kind: 'phase', co: 'AUTO', text: `auto-refining filters for "${dishLabel}"…` });
      try {
        const response = await fetch(`/optimise/${props.jobId}/auto_cull_preview`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ current_filters: props.filters }),
        });
        autoSuggestion.value = await parseJsonResponse(response);
        const cf = autoSuggestion.value?.compiled_filters || {};
        const total = Object.values(cf).reduce((n, e) => n + (e.excludes?.length || 0) + (e.brand_excludes?.length || 0), 0);
        const terms = Object.keys(cf).length;
        if (autoSuggestion.value?.warnings?.length) {
          for (const w of autoSuggestion.value.warnings) emit('pipeline-log', { kind: 'warn', co: 'AUTO', text: w });
          emit('pipeline-log', { kind: 'info', co: 'AUTO', text: `${total} filter(s) across ${terms} term(s) — ${autoSuggestion.value.warnings.length} warning(s)` });
        } else {
          emit('pipeline-log', { kind: 'ok', co: 'AUTO', text: total ? `refined — ${total} filter(s) across ${terms} term(s) — no warnings` : 'no irrelevant terms found — no warnings' });
        }
      } catch (err) {
        autoError.value = err.message;
        emit('pipeline-log', { kind: 'err', co: 'AUTO', text: err.message });
      } finally {
        autoBusy.value = false;
      }
    }
    function applyAuto() {
      const filters = autoSuggestion.value?.compiled_filters || {};
      for (const [term, entry] of Object.entries(filters)) {
        const effEx = (entry.excludes || []).filter((w) => !isAutoRejected(term, 'excludes', w));
        const effBe = (entry.brand_excludes || []).filter((w) => !isAutoRejected(term, 'brand_excludes', w));
        if (!effEx.length && !effBe.length) continue;
        const existing = props.filters[term] || { includes: [], excludes: [], brand_includes: [], brand_excludes: [] };
        const lowerEx = new Set((existing.excludes || []).map((w) => String(w).toLowerCase()));
        const lowerBe = new Set((existing.brand_excludes || []).map((w) => String(w).toLowerCase()));
        const newEx = [...(existing.excludes || [])];
        const newBe = [...(existing.brand_excludes || [])];
        for (const w of effEx) if (!lowerEx.has(String(w).toLowerCase()) && newEx.length < MAX_KW) { newEx.push(w); lowerEx.add(String(w).toLowerCase()); }
        for (const w of effBe) if (!lowerBe.has(String(w).toLowerCase()) && newBe.length < MAX_KW) { newBe.push(w); lowerBe.add(String(w).toLowerCase()); }
        const clean = {
          includes: existing.includes || [],
          excludes: newEx.slice(0, MAX_KW),
          brand_includes: existing.brand_includes || [],
          brand_excludes: newBe.slice(0, MAX_KW),
        };
        emit('update-filters', term, clean);
      }
      autoSuggestion.value = null;
      autoRejected.value = new Set();
    }
    function dismissAuto() {
      autoSuggestion.value = null;
      autoError.value = '';
      autoRejected.value = new Set();
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
      incDraft, excDraft, brandIncDraft, brandExcDraft,
      incDuplicate, excDuplicate, brandIncDuplicate, brandExcDuplicate,
      previewBusy, openStore, current, availableBrands,
      push, commitBrand, drop, countText, countClass, countTitle, storeCountClass,
      storeGroups, companyLabel, badgeClass, money,
      aiText, aiBusy, aiError, aiSuggestion, canAiGenerate, aiHint, aiPreviewCounts, aiCompactDiffs,
      generateAi, applyAi, dismissAi,
      autoBusy, autoError, autoSuggestion, canAutoCull, autoHint, autoCompactDiffs, autoRejected, autoEffectiveCounts,
      isAutoRejected, toggleAutoChip, autoCull, applyAuto, dismissAuto,
    };
  },
};
</script>
