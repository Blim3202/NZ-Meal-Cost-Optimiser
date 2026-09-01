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
          <p v-if="aiSuggestion.warnings?.length" class="subcard-hint">Warnings: {{ aiSuggestion.warnings.join('; ') }}</p>
          <div class="ai-suggestion-actions">
            <button type="button" class="primary-button" @click="applyAi">Apply these filters</button>
            <button type="button" class="ghost-button ghost-small" @click="dismissAi">Dismiss</button>
          </div>
        </div>
        <div v-if="aiSuggestion && !Object.keys(aiSuggestion.compiled_filters || {}).length" class="subcard-hint">No keyword changes suggested for this instruction.</div>
      </div>

      <div class="ai-block auto-refine-block">
        <div class="ai-block-head">
          <span class="rule-label">Auto refine</span>
          <span class="subcard-hint ai-block-hint">Dish-wide — cull up to 15 most irrelevant terms per ingredient for this dish</span>
        </div>
        <div class="ai-actions">
          <button type="button" class="ghost-button ghost-small" :disabled="!canAutoCull" @click="autoCull">
            <span v-if="autoBusy" class="spinner spinner-inline"></span>
            {{ autoBusy ? 'Refining…' : 'Auto refine filters' }}
          </button>
          <span class="subcard-hint ai-hint">{{ autoHint }}</span>
        </div>
        <p v-if="autoError" class="error-banner" role="alert">{{ autoError }}</p>
        <div v-if="autoSuggestion" class="ai-suggestion">
          <p class="subcard-hint">Review auto-cull suggestions — additive, capped at 15 per keyword list.</p>
          <ul class="ai-suggestion-list ai-suggestion-compact">
            <li v-for="row in autoCompactDiffs" :key="`auto-${row.term}`" class="ai-suggestion-row ai-row-compact">
              <div class="ai-diff-main">
                <strong class="ai-diff-term">{{ row.term }}</strong>
                <span v-for="(w,i) in row.entry.excludes" :key="`auto-exc-${row.term}-${i}`" class="kw-chip kw-exclude">{{ w }}</span>
                <span v-for="(w,i) in row.entry.brand_excludes" :key="`auto-bexc-${row.term}-${i}`" class="kw-chip kw-brand-exclude">{{ w }}</span>
              </div>
              <span class="match-chip" :class="row.delta < 0 ? 'm-zero' : row.delta > 0 ? 'm-full' : 'm-part'" :title="`${row.kwCount} keyword(s) · ${row.cur.matched}/${row.cur.total} → ${row.ai.matched}/${row.ai.total}`">{{ row.deltaText }} · {{ row.ai.matched }}/{{ row.ai.total }}</span>
            </li>
          </ul>
          <p v-if="autoSuggestion.warnings?.length" class="subcard-hint">Warnings: {{ autoSuggestion.warnings.join('; ') }}</p>
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
      <p class="subcard-hint filter-legend">Every Include Term must appear in the product name and no Exclude Term may appear (fuzzy singular/plural, e.g. carrot matches carrots). Brand filters are user-set only and match the product brand (Pams, Watties, Pak'nSave, etc.) — Include Brand passes when any brand matches, Exclude Brand hides on any match. Brand filters are checked first and override name filters, so a brand decision wins even when the name would also pass or fail. Filtered products stay visible as ‘filtered’ but are excluded from store costs.</p>
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
  },
  emits: ['update-filters', 'select-term'],
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
      return 'Auto-generates up to 15 excludes per ingredient for this dish';
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
    const autoCompactDiffs = computed(() => {
      const compiled = autoSuggestion.value?.compiled_filters || {};
      const aiTerms = autoSuggestion.value?.preview?.terms || {};
      const curTerms = preview.value?.terms || {};
      return Object.entries(compiled).map(([term, entry]) => {
        const kwCount = (entry.excludes?.length || 0) + (entry.brand_excludes?.length || 0);
        const cur = curTerms[term] || { matched: 0, total: 0 };
        const ai = aiTerms[term] || { matched: cur.matched, total: cur.total };
        const delta = ai.matched - cur.matched;
        const deltaText = delta > 0 ? `+${delta}` : `${delta}`;
        return { term, entry, kwCount, cur, ai, delta, deltaText };
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
      try {
        const response = await fetch(`/optimise/${props.jobId}/ai_filter_preview`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ instruction: aiText.value.trim() }),
        });
        aiSuggestion.value = await parseJsonResponse(response);
      } catch (err) {
        aiError.value = err.message;
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
      try {
        const response = await fetch(`/optimise/${props.jobId}/auto_cull_preview`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ current_filters: props.filters }),
        });
        autoSuggestion.value = await parseJsonResponse(response);
      } catch (err) {
        autoError.value = err.message;
      } finally {
        autoBusy.value = false;
      }
    }
    function applyAuto() {
      const filters = autoSuggestion.value?.compiled_filters || {};
      for (const [term, entry] of Object.entries(filters)) {
        const existing = props.filters[term] || { includes: [], excludes: [], brand_includes: [], brand_excludes: [] };
        const lowerEx = new Set((existing.excludes || []).map((w) => String(w).toLowerCase()));
        const lowerBe = new Set((existing.brand_excludes || []).map((w) => String(w).toLowerCase()));
        const newEx = [...(existing.excludes || [])];
        const newBe = [...(existing.brand_excludes || [])];
        for (const w of entry.excludes || []) if (!lowerEx.has(String(w).toLowerCase()) && newEx.length < MAX_KW) { newEx.push(w); lowerEx.add(String(w).toLowerCase()); }
        for (const w of entry.brand_excludes || []) if (!lowerBe.has(String(w).toLowerCase()) && newBe.length < MAX_KW) { newBe.push(w); lowerBe.add(String(w).toLowerCase()); }
        const clean = {
          includes: existing.includes || [],
          excludes: newEx.slice(0, MAX_KW),
          brand_includes: existing.brand_includes || [],
          brand_excludes: newBe.slice(0, MAX_KW),
        };
        emit('update-filters', term, clean);
      }
      autoSuggestion.value = null;
    }
    function dismissAuto() {
      autoSuggestion.value = null;
      autoError.value = '';
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
      autoBusy, autoError, autoSuggestion, canAutoCull, autoHint, autoCompactDiffs,
      autoCull, applyAuto, dismissAuto,
    };
  },
};
</script>
