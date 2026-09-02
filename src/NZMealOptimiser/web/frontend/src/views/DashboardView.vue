<template>
  <main class="shell">
    <header class="hero">
      <div><p class="eyebrow">LOCAL GROCERY INTELLIGENCE</p><h1>NZ Meal Cost Optimiser</h1>      <p class="lede">Compare any dish. Preset or built by you, across nearby supermarkets.</p></div>
    </header>

    <div class="home-grid">
      <section class="panel search-panel area-form">
        <div class="section-heading">
          <div><p class="eyebrow">Compare supermarkets</p><h3>Pick a dish or build your own</h3></div>
        </div>
        <p class="hint">Set your address and compare prices across Pak'nSave, New World and Woolworths.</p>
        <form @submit.prevent="primaryAction">
          <div class="form-grid">
            <div class="field field-wide">
              <span>Recipe source</span>
              <div class="seg-toggle" role="group" aria-label="Recipe source">
                <button type="button" class="seg-btn" :class="{ active: recipeMode === 'preset' }" @click="setMode('preset')">Preset dish</button>
                <button type="button" class="seg-btn" :class="{ active: recipeMode === 'custom' }" @click="setMode('custom')">Custom dish</button>
                <button type="button" class="seg-btn" :class="{ active: recipeMode === 'shopping' }" @click="setMode('shopping')">Shopping list</button>
              </div>
            </div>
            <label v-if="recipeMode === 'preset'" class="field field-wide"><span>Dish</span><select v-model="form.dish" required><option disabled value="">Choose a dish</option><option v-for="dish in dishes" :key="dish.key" :value="dish.key">{{ dish.label }}</option></select></label>
            <template v-else-if="recipeMode === 'custom'">
              <label class="field field-name"><span>Dish name</span><input v-model.trim.lazy="draft.name" placeholder="e.g. kumara &amp; chorizo hash" maxlength="80"></label>
              <label class="field field-base"><span>Base portions</span><input v-model.number="draft.basePortions" type="number" min="1" max="24" required></label>
              <label class="field field-wide"><span>Notes (optional)</span><input v-model.trim="draft.notes" maxlength="100" placeholder="Chocolate chip cookies — bbcgoodfood.com"></label>
              <div class="field field-wide generate-row">
                <button type="button" class="ghost-button" :disabled="generating || !canGenerate" title="Ask Mistral to draft ingredients and Gemini to seed product-filter rules from the dish name (10-20 s)" @click="generateIngredients"><span v-if="generating" class="spinner"></span>{{ generating ? 'Generating…' : 'Generate custom ingredients' }}</button>
                <span v-if="generating" class="hint">Building your ingredient list and filters. This usually takes a few seconds.</span>
              </div>
            </template>
            <label class="field field-wide"><span>NZ address</span><AddressAutocomplete v-model="form.address" placeholder="Auckland CBD" :disabled="gpsActive || originSource === 'picked'" @select="onAddressSelect" /></label>
            <label class="field field-sm"><span>Distance</span><NumberPopover v-model="form.distance_km" :options="distanceOptions" :placeholder="form.distance_km" suffix="km" aria-label="Distance in kilometres" @update:modelValue="clampOverrides" /></label>
            <label v-if="recipeMode !== 'shopping'" class="field field-sm"><span>Portions</span><input v-model.number="form.portions" type="number" min="2" max="12" required></label>
            <label class="field field-sm"><span>Max stores per company</span><NumberPopover v-model="form.max_stores_per_company" :options="storeOptions" :placeholder="form.max_stores_per_company" aria-label="Max stores per company" @update:modelValue="clampOverrides" /></label>
          </div>
          <p v-if="recipeMode === 'custom'" class="mode-note">Quantities above are scaled ×{{ scaleDisplay }} onto the {{ Number(draft.basePortions) || 1 }}-portion base recipe.</p>
          <p v-else-if="recipeMode === 'shopping'" class="mode-note">Each ingredient is one store search. Quantities are exactly what you need to buy, priced at a single portion with no scaling.</p>
          <div class="gps-row">
            <button type="button" class="ghost-button" :disabled="gpsBusy || gpsActive" @click="useGps"><span v-if="gpsBusy" class="spinner"></span>{{ gpsBusy ? 'Locating…' : 'Use my location' }}</button>
            <span v-if="gpsActive" class="chip chip-gps">📍 GPS · {{ gpsDisplay }}<button type="button" class="chip-x" title="Clear GPS location" @click="clearGps">✕</button></span>
            <span v-if="originSource === 'picked' && !gpsActive" class="chip chip-picked" :title="form.address || 'Pick a point on the map'">📍 Pinned · {{ form.address || pickedCoordsLabel }}<button type="button" class="chip-x" title="Clear pinned location" @click="clearPicked">✕</button></span>
            <span v-if="settings.overridesArmed" class="chip chip-danger" title="Settings → Danger zone overrides are enabled">⚠ Overrides active · caps {{ hardLimits.max_distance_km }} km / {{ hardLimits.max_stores_per_company }} stores</span>
          </div>
          <fieldset class="company-picker"><legend>Compare supermarkets</legend><label v-for="company in companies" :key="company.id" class="company-option" :class="`company-${company.id.toLowerCase()}`"><input v-model="form.companies" type="checkbox" :value="company.id"><span class="checkmark"></span><span>{{ company.label }}</span></label></fieldset>
          <div class="form-actions">
            <button class="primary-button" :class="{ 'is-ready': readyToCompare && !loading }" type="submit" :disabled="loading || resolving || !form.companies.length || !canResolve"><span v-if="loading || resolving" class="spinner"></span>{{ actionLabel }}</button>
            <span class="hint">{{ actionHint }}</span>
          </div>
        </form>
        <p v-if="staleNotice && !loading" class="notice-banner">⚙ Parameters changed. Check to resolve settings.</p>
        <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
      </section>

      <section class="panel ingredients-panel area-recipe">
        <div class="section-heading">
          <div><p class="eyebrow">Recipe breakdown</p><h3>{{ recipeMode === 'custom' ? 'Dish builder' : recipeMode === 'shopping' ? 'Shopping list' : 'Ingredient preview' }}</h3></div>
          <div class="heading-actions">
            <span v-if="builderIngredients.length" class="chip">{{ builderIngredients.length }} items</span>
            <button v-if="canResetFilters" type="button" class="ghost-button ghost-small" title="Restore the curated include/exclude keywords for this dish" @click="resetFiltersToPreset">Reset filters</button>
            <button v-if="recipeMode === 'preset'" type="button" class="ghost-button ghost-small" :disabled="!form.dish" title="Copy this preset into the builder and edit it" @click="customiseFromPreset">Customise ✎</button>
            <template v-else>
              <button v-if="showUpdateButton" type="button" class="ghost-button ghost-small" :disabled="!canUpdatePrices" :title="canUpdatePrices ? 'Re-query only the changed ingredients across the same stores. Quantity-only edits recalculate without new searches.' : 'Resolve blank or duplicate search terms first'" @click="updateIngredientPrices"><span v-if="updatingPrices" class="spinner"></span>{{ updatingPrices ? 'Updating…' : `Update ingredient prices (${priceDiff.count})` }}</button>
              <button type="button" class="ghost-button ghost-small" :disabled="!draft.ingredients.length" :title="recipeMode === 'shopping' ? 'Remove every item from the shopping list' : 'Remove every ingredient row (dish name and base portions reset too)'" @click="clearBuilder">Clear all</button>
              <button v-if="recipeMode === 'custom'" type="button" class="ghost-button ghost-small" :disabled="savingPreset || !canSavePreset" :title="canSavePreset ? 'Store this recipe in data/dishes.json' : 'Complete the dish name and at least one ingredient row first'" @click="savePreset">{{ savingPreset ? 'Saving…' : 'Save as preset' }}</button>
            </template>
          </div>
        </div>
        <DishBuilder :mode="recipeMode === 'preset' ? 'locked' : 'edit'" :ingredients="builderIngredients" :duplicate-terms="duplicateTerms" :base-portions="builderBasePortions" :requested-portions="builderRequestedPortions" :filter-counts="filterCounts" @add="addIngredient" @remove="removeIngredient" @patch="patchIngredient" @open-filters="openInTuner" />
        <p class="hint">{{ recipeHint }}</p>
      </section>

      <PipelineConsole class="area-terminal" :title="terminalTitle" :lines="consoleLines" :running="jobRunning" />

      <section class="panel map-panel area-map">
        <div class="section-heading"><div><p class="eyebrow">Map</p><h3>Stores near you</h3></div><span v-if="originLabel" class="chip">{{ originLabel }}</span></div>
        <MapPanel :origin="mapOrigin" :stores="mapStores" :radius-km="form.distance_km" :winner-key="winnerKey" @select-store="focusStore" @pick-origin="onPickOrigin" />
        <p v-if="!origin && !gpsActive" class="map-hint-inline">Click anywhere on the map (or drag the pin) to pick a location</p>
      </section>
    </div>

    <ProgressStrip :job="job" :running="jobRunning" :pct="overallPct" :elapsed="elapsedDisplay" />

    <ResultsTabs ref="resultsSection" :result="result" :companies="companies" :terms="runTerms" :tuner-ingredients="tunerIngredients" :filters="scopeFilters" :job-id="job.id || ''" :preview-active="previewActive" :can-reapply="canReapply" :applying="reaplying" @apply="reapplyFilters" @update-filters="onUpdateFilters" @pipeline-log="onPipelineLog" />

    <transition name="toast-slide">
      <aside v-if="applyToast" class="apply-toast" role="status">
        <p><strong>{{ applyToast.count }} filter change{{ applyToast.count === 1 ? '' : 's' }}</strong> applied. Check <em>Summary</em> for updated comparisons.</p>
        <div class="toast-actions">
          <button type="button" class="ghost-button ghost-small" @click="openToastSummary">Open summary →</button>
          <button type="button" class="kw-x toast-x" title="Dismiss" @click="dismissApplyToast">✕</button>
        </div>
      </aside>
    </transition>
  </main>
</template>

<script>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import MapPanel from '../components/MapPanel.vue';
import PipelineConsole from '../components/PipelineConsole.vue';
import ProgressStrip from '../components/ProgressStrip.vue';
import ResultsTabs from '../components/ResultsTabs.vue';
import DishBuilder from '../components/DishBuilder.vue';
import NumberPopover from '../components/NumberPopover.vue';
import AddressAutocomplete from '../components/AddressAutocomplete.vue';
import { useJobRunner } from '../composables/useJobRunner.js';
import { normaliseUnit } from '../unitOptions.js';
import { storesOf, winnerKeyOf } from '../resultUtils.js';
import { filterStore, seedPresetRules } from '../filterStore.js';
import { settings } from '../settings.js';

const companyData = [{ id: 'PaknSave', label: "Pak'nSave" }, { id: 'NewWorld', label: 'New World' }, { id: 'Woolworths', label: 'Woolworths' }];
const NZ_BOUNDS = { latMin: -47.6, latMax: -34.2, lonMin: 166.2, lonMax: 178.9 };
const NORMAL_CAPS = { distance: 8, stores: 5 };
const OVERRIDE_CAPS = { distance: 50, stores: 20 };

export default {
  name: 'DashboardView',
  components: { MapPanel, PipelineConsole, ProgressStrip, ResultsTabs, DishBuilder, NumberPopover, AddressAutocomplete },
  setup(_props, { expose }) {
    const {
      job, result, loading, error, logLine, start,
      jobRunning, overallPct, elapsedDisplay, terminalTitle, consoleLines,
    } = useJobRunner();

    const dishes = ref([]);
    const form = reactive({ dish: '', address: '', distance_km: 5, portions: 4, max_stores_per_company: 3, companies: companyData.map((company) => company.id) });
    const addressHistory = ref(JSON.parse(localStorage.getItem('meal-addresses') || '[]'));
    const companies = companyData;
    const gps = ref(null);
    const gpsBusy = ref(false);
    const origin = ref(null);
    const resolving = ref(false);
    const previewStores = ref([]);
    const staleNotice = ref(false);
    const resultsSection = ref(null);
    const hardLimits = OVERRIDE_CAPS;

    // ── Recipe source: preset dropdown vs hand-built dish ──────────────────
    const recipeMode = ref('preset');
    const savingPreset = ref(false);
    const generating = ref(false);
    let rowSeq = 0;
    const emptyRow = () => ({ id: `row-${++rowSeq}`, search_term: '', quantity: '', unit: 'g', approx_quantity: '', approx_unit: '' });
    const draft = reactive({ name: '', basePortions: 4, notes: '', ingredients: [] });

    const scaleFactor = computed(() => (Number(draft.basePortions) > 0 ? Math.round((form.portions / Number(draft.basePortions)) * 1000) / 1000 : 1));
    const scaleDisplay = computed(() => (Number.isInteger(scaleFactor.value) ? String(scaleFactor.value) : scaleFactor.value.toFixed(2).replace(/0$/, '')));

    const selectedPreset = computed(() => dishes.value.find((d) => d.key === form.dish));
    const builderIngredients = computed(() => (recipeMode.value === 'preset' ? selectedPreset.value?.ingredients || [] : draft.ingredients));
    const builderBasePortions = computed(() => (recipeMode.value === 'shopping' ? 1 : Number(draft.basePortions) || 1));
    const builderRequestedPortions = computed(() => (recipeMode.value === 'shopping' ? 1 : form.portions));

    const validRows = computed(() => draft.ingredients
      .map((row) => ({
        search_term: String(row.search_term || '').trim(),
        quantity: Number(row.quantity),
        unit: normaliseUnit(row.unit),
        approx_quantity: Number(row.approx_quantity) > 0 ? Number(row.approx_quantity) : null,
        approx_unit: Number(row.approx_quantity) > 0 ? normaliseUnit(row.approx_unit || '') : null,
      }))
      .filter((row) => row.search_term && row.quantity > 0));
    const duplicateTerms = computed(() => {
      const counts = new Map();
      for (const row of draft.ingredients) {
        const term = String(row.search_term || '').trim().toLowerCase();
        if (term) counts.set(term, (counts.get(term) || 0) + 1);
      }
      return new Set([...counts.entries()].filter(([, n]) => n > 1).map(([term]) => term));
    });

    const canResolveBase = computed(() => {
      if (recipeMode.value === 'preset') return !!form.dish;
      if (!validRows.value.length || duplicateTerms.value.size) return false;
      return recipeMode.value === 'shopping' ? true : !!String(draft.name || '').trim();
    });
    const canResolve = computed(() => canResolveBase.value && (gpsActive.value || !!form.address || originSource.value === 'picked'));
    const canSavePreset = computed(() => !!String(draft.name || '').trim() && validRows.value.length > 0 && duplicateTerms.value.size === 0);
    const canGenerate = computed(() => !!String(draft.name || '').trim());

    function addIngredient() { draft.ingredients.push(emptyRow()); }
    function removeIngredient(index) { draft.ingredients.splice(index, 1); }
    function patchIngredient(index, changes) { Object.assign(draft.ingredients[index], changes); }

    function clearBuilder() {
      const count = draft.ingredients.length;
      if (!count && !String(draft.name || '').trim() && Number(draft.basePortions) === 4 && !String(draft.notes || '').trim()) return;
      const message = recipeMode.value === 'shopping'
        ? `Clear all ${count} item${count === 1 ? '' : 's'} from the shopping list?`
        : 'Clear all ingredients?\nThe dish name, notes and base portions will be reset too.';
      if (!window.confirm(message)) return;
      draft.ingredients = [];
      draft.name = '';
      draft.basePortions = 4;
      draft.notes = '';
      logLine('warn', 'DISH', `Builder cleared. ${count} row${count === 1 ? '' : 's'} removed.`);
    }

    function loadIntoDraft(key) {
      const dish = dishes.value.find((d) => d.key === key);
      if (!dish) return false;
      draft.name = dish.label;
      draft.basePortions = Number(dish.portion) || 4;
      draft.notes = String(dish.notes || '').slice(0, 100);
      draft.ingredients = dish.ingredients.map((ing) => ({
        id: `row-${++rowSeq}`,
        search_term: ing.search_term || '',
        quantity: ing.quantity ?? '',
        unit: normaliseUnit(ing.unit) || 'g',
        approx_quantity: ing.approx_quantity ?? '',
        approx_unit: normaliseUnit(ing.approx_unit || ''),
      }));
      return true;
    }

    function customiseFromPreset() {
      if (!loadIntoDraft(form.dish)) return;
      recipeMode.value = 'custom';
      logLine('ok', 'DISH', `Customising "${draft.name}". ${draft.ingredients.length} rows copied to builder.`);
    }

    function setMode(mode) {
      if (mode === recipeMode.value) return;
      recipeMode.value = mode;
      // Entering custom mode is always a blank slate: any previous builder
      // content AND the shared 'custom' filter scope (one scope across all
      // custom dishes) are wiped so stale rules can't leak into a new dish.
      // "Customise ✎" bypasses setMode, so preset copying still works.
      if (mode === 'custom') {
        const hadContent = draft.ingredients.length > 0 || String(draft.name || '').trim() || Number(draft.basePortions) !== 4 || String(draft.notes || '').trim();
        draft.name = '';
        draft.basePortions = 4;
        draft.notes = '';
        draft.ingredients = [];
        filterStore.value = { ...filterStore.value, custom: {} };
        logLine('phase', 'DISH', hadContent
          ? 'Custom dish. Builder reset for a new recipe.'
          : 'Builder open. Name a dish, then generate or add ingredients.');
      } else if (mode === 'shopping') {
        logLine('phase', 'DISH', 'Shopping list. Add items with the exact quantity you need.');
      }
    }

    // ── LLM custom-dish generation (POST /dishes/generate) ──────────────────
    // Mistral drafts the ingredient rows; Gemini seeds include/exclude filter
    // rules for each search term. Generated rules replace the whole 'custom'
    // scope (it is shared across all custom dishes, so leftovers from a
    // previous dish must never leak in). Rules stay fully editable afterwards.
    function applyGeneratedFilters(filters) {
      const clean = Object.fromEntries(Object.entries(filters || {})
        .map(([term, f]) => [term, { includes: [...(f.includes || [])], excludes: [...(f.excludes || [])] }])
        .filter(([, f]) => f.includes.length || f.excludes.length));
      filterStore.value = { ...filterStore.value, custom: clean };
      return Object.keys(clean).length;
    }

    async function generateIngredients() {
      if (generating.value || !canGenerate.value) return;
      const name = String(draft.name).trim();
      const existing = draft.ingredients.filter((row) => String(row.search_term || '').trim()).length;
      if (existing && !window.confirm(`Replace the current ${existing} ingredient row${existing === 1 ? '' : 's'} with AI-generated ones?`)) return;
      generating.value = true;
      error.value = '';
      logLine('phase', 'DISH', `generating ingredients for "${name}" via Mistral…`);
      try {
        const response = await fetch('/dishes/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ dish_name: name, base_portions: Number(draft.basePortions) || 4 }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Could not generate ingredients');
        draft.ingredients = data.ingredients.map((ing) => ({
          id: `row-${++rowSeq}`,
          search_term: ing.search_term || '',
          quantity: ing.quantity ?? '',
          unit: normaliseUnit(ing.unit) || 'g',
          approx_quantity: ing.approx_quantity ?? '',
          approx_unit: normaliseUnit(ing.approx_unit || ''),
        }));
        const rulesCount = applyGeneratedFilters(data.filters);
        for (const warning of data.warnings || []) logLine('warn', 'LLM', warning);
        logLine('ok', 'LLM', `Generated ${draft.ingredients.length} ingredients · ${rulesCount} filter rule${rulesCount === 1 ? '' : 's'} seeded. Review them in the filter editor.`);
        if (origin.value) staleNotice.value = true; // recipe changed vs resolved setup
      } catch (err) {
        error.value = err.message;
        logLine('err', 'LLM', `Generation failed: ${err.message}`);
      } finally {
        generating.value = false;
      }
    }

    // ── Product filters: dish_filters.json presets + per-user keyword edits ─
    // One scope per mode: "preset:<key>" for curated dishes, "custom" and
    // "shopping" for the builder modes. The store lives in ../filterStore.js —
    // a single shared ref persisted to localStorage, also imported by the My
    // Dishes inline editor so rule edits from either page stay in sync.
    const presetFilters = ref({}); // dish key -> { search_term: {includes, excludes} }
    const reaplying = ref(false);
    let appliedFilterSig = ''; // filter payload baked into the latest run/reapply
    let appliedFiltersSnapshot = {}; // keyword copy of the payload baked into the latest run/reapply

    // ── Apply-filters toast ─────────────────────────────────────────────────
    const applyToast = ref(null); // { count } while visible
    let toastTimer = null;
    function countFilterChanges(before, after) {
      let changes = 0;
      const fields = ['includes', 'excludes', 'brand_includes', 'brand_excludes'];
      for (const term of new Set([...Object.keys(before), ...Object.keys(after)])) {
        const a = before[term] || {};
        const b = after[term] || {};
        for (const kind of fields) {
          const prev = new Set((a[kind] || []).map((w) => w.toLowerCase()));
          const next = new Set((b[kind] || []).map((w) => w.toLowerCase()));
          for (const w of next) if (!prev.has(w)) changes += 1;
          for (const w of prev) if (!next.has(w)) changes += 1;
        }
      }
      return changes;
    }
    function showApplyToast(count) {
      applyToast.value = { count };
      if (toastTimer) clearTimeout(toastTimer);
      toastTimer = setTimeout(() => { applyToast.value = null; }, 6000);
    }
    function dismissApplyToast() {
      if (toastTimer) clearTimeout(toastTimer);
      applyToast.value = null;
    }
    function openToastSummary() {
      dismissApplyToast();
      resultsSection.value?.openSummary();
    }

    const activeScopeKey = computed(() => (recipeMode.value === 'preset' ? `preset:${form.dish}` : recipeMode.value));
    const seenScopes = computed(() => new Set(filterStore.value._seen || []));
    const scopeFilters = computed(() => filterStore.value[activeScopeKey.value] || {});

    function markSeen(key) {
      if (seenScopes.value.has(key)) return;
      filterStore.value = { ...filterStore.value, _seen: [...(filterStore.value._seen || []), key] };
    }

    async function fetchPresetFilters() {
      try {
        const response = await fetch('/dish_filters');
        if (response.ok) presetFilters.value = await response.json();
      } catch { /* presets are optional sugar — builder filters still work */ }
    }

    // Seed an unseen preset scope from dish_filters.json exactly once, so
    // deleting keywords never resurrects them on revisit (per-user store wins).
    // Brand filters are NEVER seeded — they are user-set only.
    function seedIfUnseen() {
      const key = activeScopeKey.value;
      if (!key.startsWith('preset:') || seenScopes.value.has(key)) return;
      markSeen(key);
      const rules = presetFilters.value[key.slice('preset:'.length)];
      if (!rules) return;
      const clean = Object.fromEntries(Object.entries(rules)
        .map(([term, f]) => [term, {
          includes: [...(f.includes || [])],
          excludes: [...(f.excludes || [])],
          brand_includes: [],
          brand_excludes: [],
        }])
        .filter(([, f]) => f.includes.length || f.excludes.length));
      filterStore.value = { ...filterStore.value, [key]: clean };
      const n = Object.keys(clean).length;
      logLine('ok', 'DISH', `loaded ${n} product-filter rule${n === 1 ? '' : 's'} for "${selectedPreset.value?.label || form.dish}"`);
    }
    watch(activeScopeKey, seedIfUnseen);

    function onPipelineLog({ kind, co, text }) {
      logLine(kind || 'warn', co || 'AUTO', text);
    }

    function onUpdateFilters(term, next) {
      const scope = { ...(filterStore.value[activeScopeKey.value] || {}) };
      const clean = {
        includes: (next.includes || []).filter(Boolean),
        excludes: (next.excludes || []).filter(Boolean),
        brand_includes: (next.brand_includes || []).filter(Boolean),
        brand_excludes: (next.brand_excludes || []).filter(Boolean),
      };
      const empty = !clean.includes.length && !clean.excludes.length
        && !clean.brand_includes.length && !clean.brand_excludes.length;
      if (empty) delete scope[term];
      else scope[term] = clean;
      filterStore.value = { ...filterStore.value, [activeScopeKey.value]: scope };
    }

    const normalisedRulesSig = (rules) => JSON.stringify(Object.entries(rules || {})
      .map(([term, f]) => ({
        t: term.toLowerCase(),
        i: f.includes || [],
        e: f.excludes || [],
        bi: f.brand_includes || [],
        be: f.brand_excludes || [],
      }))
      .sort((a, b) => a.t.localeCompare(b.t)));
    const canResetFilters = computed(() => recipeMode.value === 'preset' && !!form.dish
      && !!presetFilters.value[form.dish]
      && normalisedRulesSig(scopeFilters.value) !== normalisedRulesSig(presetFilters.value[form.dish]));
    function resetFiltersToPreset() {
      const rules = presetFilters.value[form.dish] || {};
      filterStore.value = { ...filterStore.value, [activeScopeKey.value]: JSON.parse(JSON.stringify(rules)) };
      markSeen(activeScopeKey.value);
      logLine('ok', 'DISH', `filters reset to curated presets (${Object.keys(rules).length} terms)`);
    }

    function currentIngredientFilters() {
      const scope = scopeFilters.value;
      const out = {};
      for (const row of builderIngredients.value) {
        const term = String(row.search_term || '').trim();
        if (!term) continue;
        const entry = scope[term];
        if (!entry) continue;
        const includes = (entry.includes || []).filter((w) => String(w).trim());
        const excludes = (entry.excludes || []).filter((w) => String(w).trim());
        const brand_includes = (entry.brand_includes || []).filter((w) => String(w).trim());
        const brand_excludes = (entry.brand_excludes || []).filter((w) => String(w).trim());
        if (includes.length || excludes.length || brand_includes.length || brand_excludes.length) {
          out[term] = { includes, excludes, brand_includes, brand_excludes };
        }
      }
      return out;
    }
    const filterSignature = computed(() => JSON.stringify(currentIngredientFilters()));
    const canReapply = computed(() => !!result.value && !!job.id && !jobRunning.value
      && !reaplying.value && filterSignature.value !== appliedFilterSig);

    // ── Results card handoff (tabs / tuner) ────────────────────────────────
    // Requested ingredient order for Summary rankings + tuner card 1.
    const runTerms = computed(() => builderIngredients.value
      .map((row) => String(row.search_term || '').trim())
      .filter(Boolean));
    function displayQty(ing) {
      const qty = ing.quantity === null || ing.quantity === undefined ? '' : `${ing.quantity} `;
      const approx = ing.approx_quantity ? ` · ~${ing.approx_quantity} ${ing.approx_unit}` : '';
      return `${qty}${ing.unit}${approx}`;
    }
    const tunerIngredients = computed(() => builderIngredients.value
      .map((row) => ({ term: String(row.search_term || '').trim(), row }))
      .filter((entry) => entry.term)
      .map((entry) => ({ term: entry.term, qty: displayQty(entry.row) })));
    const filterCounts = computed(() => {
      const counts = {};
      for (const [term, entry] of Object.entries(scopeFilters.value || {})) {
        const n = (entry.includes?.length || 0) + (entry.excludes?.length || 0);
        if (n) counts[term] = n;
      }
      return counts;
    });
    const previewActive = computed(() => !!result.value && !jobRunning.value);
    function openInTuner(term) { resultsSection.value?.openTuner(term); }

    async function reapplyFilters() {
      if (!canReapply.value) return;
      reaplying.value = true;
      error.value = '';
      try {
        const response = await fetch(`/optimise/${job.id}/reapply`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ingredient_filters: currentIngredientFilters() }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Could not reapply the filters');
        const changes = countFilterChanges(appliedFiltersSnapshot, currentIngredientFilters());
        resultsSection.value?.suppressJumpOnce();
        result.value = data;
        appliedFilterSig = filterSignature.value;
        appliedFiltersSnapshot = JSON.parse(JSON.stringify(currentIngredientFilters()));
        showApplyToast(changes);
        const winner = data.store_costs?.[0];
        logLine('ok', 'SYS', `filters reapplied · ${data.rows.length} products recalculated · winner ${winner ? `${winner.store} $${winner.total_used_cost.toFixed(2)}` : '—'}`);
      } catch (err) {
        error.value = err.message;
      } finally {
        reaplying.value = false;
      }
    }

    // ── Partial ingredient updates ("Update ingredient prices") ────────────
    // After a completed run, builder edits diff against a snapshot taken at
    // submit time (stable per-row ids). Renames are detected so their filter
    // rules carry over; the server decides per term whether to re-query
    // (added/renamed terms) or purely rescale (quantity/unit edits).
    const updatingPrices = ref(false);
    let runBaseline = null; // [{id, key, term}] baked into the last run/update
    const rowKeyOf = (row) => JSON.stringify([
      String(row.search_term || '').trim(),
      Number(row.quantity),
      normaliseUnit(row.unit),
      Number(row.approx_quantity) > 0 ? Number(row.approx_quantity) : null,
      Number(row.approx_quantity) > 0 ? normaliseUnit(row.approx_unit || '') : null,
    ]);
    function snapshotBuilderRows() {
      return draft.ingredients.map((row) => ({ id: row.id, key: rowKeyOf(row), term: String(row.search_term || '').trim() }));
    }
    const priceDiff = computed(() => {
      const out = { terms: [], renames: [], removedCount: 0, count: 0 };
      if (!runBaseline || !result.value || jobRunning.value) return out;
      const baseById = new Map(runBaseline.map((row) => [row.id, row]));
      const seenIds = new Set();
      for (const row of draft.ingredients) {
        seenIds.add(row.id);
        const term = String(row.search_term || '').trim();
        const base = baseById.get(row.id);
        if (!base) {
          if (term) out.terms.push(term); // brand-new row
          continue;
        }
        if (base.key !== rowKeyOf(row)) {
          if (base.term && term && base.term !== term) out.renames.push([base.term, term]);
          if (term) out.terms.push(term); // renamed or quantity/unit edit
        }
      }
      for (const base of runBaseline) if (!seenIds.has(base.id)) out.removedCount += 1;
      out.count = out.terms.length + out.removedCount;
      return out;
    });
    const showUpdateButton = computed(() => !!result.value && !jobRunning.value && !staleNotice.value && priceDiff.value.count > 0);
    const canUpdatePrices = computed(() => showUpdateButton.value && !updatingPrices.value
      && duplicateTerms.value.size === 0
      && draft.ingredients.every((row) => String(row.search_term || '').trim())
      && (recipeMode.value !== 'custom' || !!String(draft.name || '').trim()));

    // Renamed ingredient → move its generated/edited filter rules onto the
    // new term so tuning survives a rename (rules are never regenerated).
    function applyRuleRenames() {
      const pairs = priceDiff.value.renames;
      if (!pairs.length) return;
      const scope = { ...(filterStore.value[activeScopeKey.value] || {}) };
      let moved = 0;
      for (const [from, to] of pairs) {
        const fromKey = Object.keys(scope).find((key) => key.toLowerCase() === from.toLowerCase());
        if (fromKey && !Object.keys(scope).some((key) => key.toLowerCase() === to.toLowerCase())) {
          scope[to] = scope[fromKey];
          moved += 1;
        }
        if (fromKey) delete scope[fromKey];
      }
      filterStore.value = { ...filterStore.value, [activeScopeKey.value]: scope };
      if (moved) logLine('ok', 'DISH', `carried ${moved} filter rule${moved === 1 ? '' : 's'} over to the renamed search term${pairs.length === 1 ? '' : 's'}`);
    }

    async function updateIngredientPrices() {
      if (!canUpdatePrices.value) return;
      updatingPrices.value = true;
      error.value = '';
      const diff = priceDiff.value;
      logLine('phase', 'SYS', `updating ${diff.count} changed ingredient${diff.count === 1 ? '' : 's'}`
        + `${diff.renames.length ? ` · rename${diff.renames.length === 1 ? '' : 's'} detected` : ''}`);
      try {
        const response = await fetch(`/optimise/${job.id}/update_ingredients`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            custom_dish: {
              dish_name: recipeMode.value === 'shopping' ? 'Shopping list' : String(draft.name).trim(),
              base_portions: recipeMode.value === 'shopping' ? 1 : (Number(draft.basePortions) || 4),
              ingredients: builderPayloadRows(),
              source_label: recipeMode.value === 'shopping' ? 'shopping_list' : 'custom',
            },
            ingredient_filters: currentIngredientFilters(),
          }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Could not update the ingredient prices');
        applyRuleRenames();
        resultsSection.value?.suppressJumpOnce();
        result.value = data;
        runBaseline = snapshotBuilderRows();
        appliedFilterSig = filterSignature.value;
        appliedFiltersSnapshot = JSON.parse(JSON.stringify(currentIngredientFilters()));
        const winner = data.store_costs?.[0];
        logLine('ok', 'SYS', `ingredient prices updated · ${data.rows.length} products recalculated · winner ${winner ? `${winner.store} $${winner.total_used_cost.toFixed(2)}` : '—'}`);
      } catch (err) {
        error.value = err.message;
        logLine('err', 'SYS', `Ingredient update failed: ${err.message}`);
      } finally {
        updatingPrices.value = false;
      }
    }

    // ── Cross-view entry points ─────────────────────────────────────────────
    function loadPreset(key, edit = false) {
      if (!dishes.value.some((d) => d.key === key)) return;
      form.dish = key;
      if (edit) customiseFromPreset();
    }

    // LLM Recipe Builder → dashboard: fill the custom-mode draft from a fresh
    // /dishes/import_text payload. Bypasses setMode's blank-slate wipe the
    // same way customiseFromPreset does; applyGeneratedFilters replaces the
    // shared 'custom' filter scope wholesale, so no stale rules can leak.
    function loadDraft(payload = {}) {
      const rows = Array.isArray(payload.ingredients) ? payload.ingredients : [];
      if (!rows.length) return;
      recipeMode.value = 'custom';
      draft.name = String(payload.name || '').trim();
      draft.basePortions = Number(payload.basePortions) > 0 ? Math.min(Number(payload.basePortions), 24) : 4;
      draft.notes = String(payload.notes || '').trim().slice(0, 100);
      draft.ingredients = rows.map((ing) => ({
        id: `row-${++rowSeq}`,
        search_term: ing.search_term || '',
        quantity: ing.quantity ?? '',
        unit: normaliseUnit(ing.unit) || 'g',
        approx_quantity: ing.approx_quantity ?? '',
        approx_unit: normaliseUnit(ing.approx_unit || ''),
      }));
      const rulesCount = applyGeneratedFilters(payload.filters);
      logLine('ok', 'LLM', `Imported "${draft.name}". ${draft.ingredients.length} ingredient${draft.ingredients.length === 1 ? '' : 's'} · ${rulesCount} filter rule${rulesCount === 1 ? '' : 's'} seeded. Review before pricing.`);
      if (origin.value) staleNotice.value = true;
    }
    expose({ loadPreset, loadDraft });

    const builderPayloadRows = () => validRows.value.map((row) => (row.approx_quantity === null
      ? { search_term: row.search_term, quantity: row.quantity, unit: row.unit }
      : { ...row }));

    async function savePreset() {
      if (!canSavePreset.value || savingPreset.value) return;
      const name = String(draft.name).trim();
      const key = name.toLowerCase();
      if (dishes.value.some((d) => d.key === key) && !window.confirm(`"${name}" already exists as a preset.\nOverwrite it?`)) return;
      const wasCustom = recipeMode.value === 'custom'; // captured pre-switch
      savingPreset.value = true;
      error.value = '';
      try {
        const response = await fetch('/dishes/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            dish_name: name,
            base_portions: Number(draft.basePortions) || 4,
            ingredients: builderPayloadRows(),
            notes: String(draft.notes || '').trim().slice(0, 100),
          }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Could not save the preset');
        // Carry the builder's keyword rules onto the named preset — otherwise
        // Gemini-seeded / hand-tuned rules die with the scratch 'custom'
        // scope on the next setMode('custom').
        let rulesSeeded = 0;
        if (wasCustom) rulesSeeded = seedPresetRules(data.key, filterStore.custom);
        await fetchDishes();
        form.dish = data.key;
        recipeMode.value = 'preset';
        if (origin.value) staleNotice.value = true; // recipe changed vs resolved setup
        logLine('ok', 'DISH', `preset ${data.updated ? 'updated' : 'created'}: "${data.key}" · ${validRows.value.length} ingredients @ ${Number(draft.basePortions)} portions${wasCustom ? ` · ${rulesSeeded} filter rule set(s) carried over` : ''}`);
      } catch (err) {
        error.value = err.message;
      } finally {
        savingPreset.value = false;
      }
    }

    const recipeHint = computed(() => {
      if (recipeMode.value === 'custom') return 'Each ingredient is one search per store. The ≈ fields give non-standard units a gram or ml equivalent so used-costs can be scaled.';
      if (recipeMode.value === 'shopping') return 'List the items you need with the quantity you want. Each ingredient is one search per store, without scaling.';
      return 'These are the searches the price comparison will run. Use "Customise" to tweak them.';
    });

    // ── Location / map plumbing (shared behaviour with the standard page) ──
    const gpsActive = computed(() => !!gps.value);
    const gpsDisplay = computed(() => (gps.value ? `${gps.value.lat.toFixed(3)}, ${gps.value.lon.toFixed(3)}` : ''));
    const mapOrigin = computed(() => origin.value || result.value?.origin || null);
    const originSource = computed(() => origin.value?.source || (result.value?.origin?.source || ''));
    const pickedCoordsLabel = computed(() => (origin.value ? `${origin.value.lat.toFixed(4)}, ${origin.value.lon.toFixed(4)}` : ''));
    const originLabel = computed(() => { const o = mapOrigin.value; if (!o) return ''; if (o.source === 'gps') return 'Using device GPS'; if (o.source === 'picked') return 'Pinned on map'; return 'Geocoded origin'; });
    const mapStores = computed(() => storesOf(result.value, previewStores.value));
    const winnerKey = computed(() => winnerKeyOf(result.value));
    const resolved = computed(() => !!origin.value);
    const readyToCompare = computed(() => resolved.value && !staleNotice.value && previewStores.value.length > 0);
    const actionLabel = computed(() => (loading.value ? 'Comparing prices...' : resolving.value ? 'Resolving…' : readyToCompare.value ? 'Compare prices' : 'Resolve setup'));
    const actionHint = computed(() => {
      if (!form.companies.length) return 'Select at least one supermarket.';
      if (loading.value) return 'Results stream into the console below.';
      if (resolving.value) return 'Checking dish and location…';
      if (recipeMode.value === 'custom') {
        if (!String(draft.name || '').trim()) return 'Name your dish first.';
        if (!validRows.value.length) return 'Add ingredients manually or click "Generate custom ingredients".';
        if (duplicateTerms.value.size) return 'Merge the highlighted duplicate search terms.';
      } else if (recipeMode.value === 'shopping') {
        if (!validRows.value.length) return 'Add at least one item with a term and quantity.';
        if (duplicateTerms.value.size) return 'Merge the highlighted duplicate search terms.';
      } else if (!form.dish) return 'Choose a dish first.';
      if (!resolved.value) return 'Please verify the dish and location first.';
      if (staleNotice.value) return 'Parameters changed. Resolve again to continue.';
      if (!previewStores.value.length) return 'No stores in range. Increase the distance or select more supermarkets.';
      return 'Dish and location verified. Ready to compare.';
    });

    function useGps() {
      if (!navigator.geolocation) { error.value = 'Geolocation is not supported by this browser.'; return; }
      gpsBusy.value = true;
      navigator.geolocation.getCurrentPosition((pos) => {
        const { latitude, longitude } = pos.coords;
        if (latitude < NZ_BOUNDS.latMin || latitude > NZ_BOUNDS.latMax || longitude < NZ_BOUNDS.lonMin || longitude > NZ_BOUNDS.lonMax) {
          gpsBusy.value = false;
          error.value = 'Your device appears to be outside New Zealand. Enter an NZ address instead.';
          return;
        }
        gps.value = { lat: latitude, lon: longitude };
        gpsBusy.value = false;
        error.value = '';
      }, (err) => {
        gpsBusy.value = false;
        error.value = err.code === err.PERMISSION_DENIED ? 'Location permission denied. Enter an address instead.' : 'Could not get your location. Enter an address instead.';
      }, { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
    }
    function clearGps() { gps.value = null; }
    function focusStore(pin) { resultsSection.value?.focusStore(pin); }

    // ── Map pick / drag → new origin {source: 'picked'} ─────────────────────
    // Pure manual GPS picking, no Nominatim involved. We set the origin
    // immediately, snap the map preview, then debounce-reverse the coords
    // via /geocode/reverse (Photon) so the address field gets a real label
    // without the user re-typing. The 'picked' source makes the form-input
    // wipe guard at the bottom of the file skip the picked branch, and
    // originLabel above surfaces it in the coverage chip.
    let reverseAbort = null;
    async function reverseLookup(lat, lon) {
      if (reverseAbort) reverseAbort.abort();
      reverseAbort = new AbortController();
      const signal = reverseAbort.signal;
      try {
        const response = await fetch(`/geocode/reverse?lat=${lat}&lon=${lon}`, { signal });
        if (!response.ok) return null;
        return await response.json();
      } catch (err) {
        if (err.name === 'AbortError') return null;
        return null;
      }
    }

    async function onPickOrigin({ lat, lon }) {
      if (lat < NZ_BOUNDS.latMin || lat > NZ_BOUNDS.latMax || lon < NZ_BOUNDS.lonMin || lon > NZ_BOUNDS.lonMax) {
        error.value = 'That point is outside New Zealand. Drop the pin within NZ.';
        return;
      }
      origin.value = { lat, lon, source: 'picked' };
      _suppressAddressReset += 1;
      form.address = '';
      error.value = '';
      logLine('phase', 'LOC', `Pin dropped · ${lat.toFixed(4)}, ${lon.toFixed(4)}. Looking up address…`);
      await fetchPreview();
      const data = await reverseLookup(lat, lon);
      if (data && data.label) {
        _suppressAddressReset += 1;
        form.address = data.label;
        logLine('ok', 'LOC', `pinned · ${data.label}`);
      } else if (data === null) {
        logLine('warn', 'LOC', `No address label found for ${lat.toFixed(4)}, ${lon.toFixed(4)}. Drop the pin closer to a road.`);
      }
    }

    function onAddressSelect(suggestion) {
      if (gpsActive.value) return;
      resolving.value = true;
      error.value = '';
      logLine('phase', 'LOC', `resolving "${suggestion.display}"…`);
      // The Photon result already includes coords — use them directly so
      // we avoid a second Nominatim round-trip through /geocode.
      _suppressAddressReset += 1;
      origin.value = { lat: suggestion.lat, lon: suggestion.lon, source: 'geocoded' };
      form.address = suggestion.display;
      logLine('ok', 'LOC', `geocoded "${suggestion.display}" → ${suggestion.lat.toFixed(4)}, ${suggestion.lon.toFixed(4)}`);
      resolving.value = false;
      fetchPreview();
    }

    function clearPicked() {
      if (origin.value?.source === 'picked') {
        origin.value = null;
        form.address = '';
        logLine('warn', 'LOC', 'pinned location cleared');
      }
    }

    // ── Danger-zone overrides: clamp helper + arming transitions ───────────
    const distanceOptions = computed(() => Array.from({ length: settings.overridesArmed ? 50 : 8 }, (_, i) => i + 1));
    const storeOptions = computed(() => Array.from({ length: settings.overridesArmed ? 20 : 5 }, (_, i) => i + 1));
    function clampOverrides() {
      const caps = settings.overridesArmed ? OVERRIDE_CAPS : NORMAL_CAPS;
      form.distance_km = Math.min(caps.distance, Math.max(1, Math.round(Number(form.distance_km) || 5)));
      form.max_stores_per_company = Math.min(caps.stores, Math.max(1, Math.round(Number(form.max_stores_per_company) || 3)));
    }
    watch(() => settings.overridesArmed, (armed) => {
      clampOverrides();
      logLine('warn', 'SYS', armed
        ? `Overrides armed. Distance up to ${OVERRIDE_CAPS.distance} km, up to ${OVERRIDE_CAPS.stores} stores/company (hard server caps).`
        : 'Overrides disarmed. Inputs returned to standard ranges.');
    });

    // Address-input guard: when the user types, wipe the geocoded origin
    // so the resolve step runs again. The picked origin's label is set
    // programmatically via onPickOrigin — we suppress the wipe in that
    // window so the resolved label doesn't immediately kill the pin.
    let _suppressAddressReset = 0;
    watch(() => form.address, () => {
      if (_suppressAddressReset > 0) { _suppressAddressReset -= 1; return; }
      if (origin.value?.source === 'geocoded') { origin.value = null; logLine('warn', 'LOC', 'Address changed. Re-resolve location.'); }
    });
    watch(gps, (lock) => {
      if (lock) { origin.value = { lat: lock.lat, lon: lock.lon, source: 'gps' }; logLine('ok', 'LOC', `device gps locked · ${lock.lat.toFixed(4)}, ${lock.lon.toFixed(4)}`); }
      else if (origin.value?.source === 'gps') { origin.value = null; logLine('warn', 'LOC', 'gps cleared'); }
    });
    watch(() => form.dish, (key) => {
      if (recipeMode.value !== 'preset') return;
      const dish = dishes.value.find((d) => d.key === key);
      if (!key) logLine('warn', 'DISH', 'Recipe cleared. Choose a dish.');
      else if (dish) logLine('ok', 'DISH', `recipe refreshed · ${dish.label} · ${dish.ingredients.length} ingredient searches`);
      else logLine('warn', 'DISH', `recipe unavailable (${key})`);
    });

    // Stale-state trigger: ONLY location/store parameters force a re-resolve.
    // Ingredient edits stay live — with a completed result they arm the
    // partial "Update ingredient prices" flow instead of invalidating setup,
    // and a full "Compare prices" rerun is always one click away anyway.
    const locationSettingsSignature = computed(() => [
      recipeMode.value === 'preset' ? `preset:${form.dish}` : recipeMode.value,
      origin.value ? `${origin.value.lat},${origin.value.lon},${origin.value.source}` : '',
      form.portions, form.max_stores_per_company, form.distance_km, form.companies.join(),
    ].join('|'));
    watch(locationSettingsSignature, () => { if (origin.value) { staleNotice.value = true; logLine('warn', 'SYS', 'Location or store settings changed. Resolve again to continue.'); } });

    const previewSignature = computed(() => [origin.value ? `${origin.value.lat},${origin.value.lon}` : '', form.distance_km, form.companies.join(), form.max_stores_per_company].join('|'));
    watch(previewSignature, () => { fetchPreview(); });

    async function fetchPreview() {
      const o = origin.value;
      if (!o) { previewStores.value = []; return true; }
      try {
        const params = new URLSearchParams({ lat: String(o.lat), lon: String(o.lon), distance_km: String(form.distance_km), max_per_company: String(form.max_stores_per_company), companies: form.companies.join(',') });
        const response = await fetch(`/stores/nearby?${params}`);
        const data = await response.json();
        previewStores.value = response.ok ? (data.stores || []) : [];
        if (response.ok && previewStores.value.length) {
          const n = previewStores.value.length;
          logLine('ok', 'LOC', `location refreshed · ${n} store${n === 1 ? '' : 's'} in range · ${form.distance_km} km radius`);
        }
        return response.ok;
      } catch { previewStores.value = []; return false; }
    }

    async function resolveSetup() {
      error.value = '';
      if (!canResolveBase.value) {
        if (recipeMode.value === 'custom') error.value = duplicateTerms.value.size ? 'Merge the highlighted duplicate search terms.' : 'Give the dish a name and at least one ingredient.';
        else if (recipeMode.value === 'shopping') error.value = duplicateTerms.value.size ? 'Merge the highlighted duplicate search terms.' : 'Add at least one item to your shopping list.';
        else error.value = 'Choose a dish first.';
        return;
      }
      if (gpsActive.value) { origin.value = { lat: gps.value.lat, lon: gps.value.lon, source: 'gps' }; }
      else if (origin.value?.source === 'picked') {
        // already resolved from the map — just re-run the preview against current settings
      }
      else {
        if (!form.address) { error.value = 'Enter an address, use device GPS, or pick a point on the map.'; return; }
        resolving.value = true;
        try {
          const response = await fetch(`/geocode?address=${encodeURIComponent(form.address)}`);
          const data = await response.json();
          if (!response.ok) throw new Error(data.detail || 'Could not resolve that address');
          origin.value = { lat: data.lat, lon: data.lon, source: 'geocoded' };
          logLine('ok', 'LOC', `geocoded "${form.address}" → ${data.lat.toFixed(4)}, ${data.lon.toFixed(4)}`);
        } catch (err) { error.value = err.message; return; } finally { resolving.value = false; }
      }
      const previewOk = await fetchPreview();
      if (!previewOk || !previewStores.value.length) {
        error.value = `No stores found within ${form.distance_km} km. Try increasing the distance or selecting more supermarkets.`;
        logLine('warn', 'LOC', `No stores within ${form.distance_km} km. Increase the distance or select more supermarkets.`);
        return;
      }
      staleNotice.value = false;
      logLine('ok', 'SYS', 'Settings resolved. Ready to compare.');
    }
    function primaryAction() { readyToCompare.value ? runOptimise() : resolveSetup(); }

    async function runOptimise() {
      error.value = '';
      if (!previewStores.value.length) {
        error.value = `No stores found within ${form.distance_km} km. Try increasing the distance or selecting more supermarkets.`;
        return;
      }
      if (!gpsActive.value && form.address) {
        const history = [form.address, ...addressHistory.value.filter((address) => address !== form.address)].slice(0, 5);
        addressHistory.value = history;
        localStorage.setItem('meal-addresses', JSON.stringify(history));
      }
      const payload = { ...form };
      if (origin.value) { payload.latitude = origin.value.lat; payload.longitude = origin.value.lon; }
      if (gpsActive.value) payload.address = 'Device GPS location';
      if (recipeMode.value === 'custom') {
        payload.dish = String(draft.name).trim();
        payload.custom_dish = {
          dish_name: payload.dish,
          base_portions: Number(draft.basePortions) || 4,
          ingredients: builderPayloadRows(),
        };
      } else if (recipeMode.value === 'shopping') {
        payload.dish = 'Shopping list';
        payload.portions = 1;
        payload.custom_dish = {
          dish_name: 'Shopping list',
          base_portions: 1,
          ingredients: builderPayloadRows(),
          source_label: 'shopping_list',
        };
      }
      resultsSection.value?.resetFilters();
      payload.ingredient_filters = currentIngredientFilters();
      appliedFilterSig = filterSignature.value;
      appliedFiltersSnapshot = JSON.parse(JSON.stringify(currentIngredientFilters()));
      runBaseline = snapshotBuilderRows(); // baseline for post-run partial updates
      logLine('phase', 'DISH', recipeMode.value === 'custom'
        ? `submitting custom dish "${payload.dish}" · ${payload.custom_dish.ingredients.length} searches · ×${scaleFactor.value} portions`
        : recipeMode.value === 'shopping'
          ? `submitting shopping list · ${payload.custom_dish.ingredients.length} searches · single portion`
          : `submitting preset "${form.dish}"`);
      await start(payload);
    }

    async function fetchDishes() {
      const response = await fetch('/dishes');
      if (!response.ok) throw new Error('Could not load dishes');
      const data = await response.json();
      dishes.value = Object.entries(data).map(([key, dish]) => ({ key, label: dish.dish_name || key, portion: dish.portion || 4, ingredients: dish.ingredients || [], source: dish.source || 'curated', notes: dish.notes || '' }));
    }

    onMounted(async () => {
      logLine('phase', 'SYS', 'dish-builder dashboard online');
      try {
        await Promise.all([fetchDishes(), fetchPresetFilters()]);
        form.dish = dishes.value[0]?.key || '';
        seedIfUnseen(); // the activeScopeKey watch may have fired before /dish_filters landed
      } catch (err) { error.value = err.message; }
    });

    return {
      companies, dishes, form, addressHistory, gps, gpsBusy, gpsActive, gpsDisplay,
      useGps, clearGps, originSource, pickedCoordsLabel, onPickOrigin, onAddressSelect, clearPicked, originLabel, mapOrigin, mapStores, winnerKey, focusStore,
      resolved, readyToCompare, canResolve, actionLabel, actionHint, primaryAction,
      staleNotice, error, loading, resolving,
      recipeMode, setMode, draft, builderIngredients, builderBasePortions,
      builderRequestedPortions, duplicateTerms, validRows,
      addIngredient, removeIngredient, patchIngredient, clearBuilder, customiseFromPreset,
      generateIngredients, generating, canGenerate,
      savePreset, savingPreset, canSavePreset, recipeHint, scaleDisplay,
      scopeFilters, onUpdateFilters, onPipelineLog, canResetFilters, resetFiltersToPreset,
      canReapply, reaplying, reapplyFilters,
      updatingPrices, showUpdateButton, canUpdatePrices, priceDiff, updateIngredientPrices,
      runTerms, tunerIngredients, filterCounts, previewActive, openInTuner,
      applyToast, dismissApplyToast, openToastSummary,
      job, jobRunning, overallPct, elapsedDisplay, terminalTitle, consoleLines, result,
      resultsSection,
      settings, hardLimits, clampOverrides,
      distanceOptions, storeOptions,
    };
  },
};
</script>
