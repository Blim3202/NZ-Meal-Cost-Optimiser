<template>
  <main class="shell">
    <header class="hero">
      <div><p class="eyebrow">NZ grocery intelligence</p><h1>Meal cost optimiser</h1><p class="lede">Compare any dish — preset or built by you — across nearby supermarkets.</p></div>
      <a class="legacy-link" href="/app">Open standard dashboard</a>
    </header>

    <div class="home-grid">
      <section class="panel search-panel area-form">
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
            </template>
            <label class="field field-wide"><span>NZ address</span><input v-model.trim="form.address" list="address-history" placeholder="Auckland CBD" :disabled="gpsActive" :required="!gpsActive"><datalist id="address-history"><option v-for="address in addressHistory" :key="address" :value="address" /></datalist></label>
            <label class="field field-sm"><span>Distance</span><input v-if="settings.overridesArmed" v-model.number="form.distance_km" type="number" min="1" max="50" step="1" required @change="clampOverrides"><select v-else v-model.number="form.distance_km"><option v-for="km in 8" :key="km" :value="km">{{ km }} km</option></select></label>
            <label v-if="recipeMode !== 'shopping'" class="field field-sm"><span>Portions</span><input v-model.number="form.portions" type="number" min="2" max="12" required></label>
            <label class="field field-sm"><span>Max stores / company</span><input v-if="settings.overridesArmed" v-model.number="form.max_stores_per_company" type="number" min="1" max="20" step="1" required @change="clampOverrides"><select v-else v-model.number="form.max_stores_per_company"><option v-for="count in 5" :key="count" :value="count">{{ count }}</option></select></label>
          </div>
          <p v-if="recipeMode === 'custom'" class="mode-note">Quantities above are scaled ×{{ scaleDisplay }} onto the {{ Number(draft.basePortions) || 1 }}-portion base recipe.</p>
          <p v-else-if="recipeMode === 'shopping'" class="mode-note">Each row is one store search — quantities are exactly what you need to buy, priced at a single portion with no scaling.</p>
          <div class="gps-row">
            <button type="button" class="ghost-button" :disabled="gpsBusy || gpsActive" @click="useGps"><span v-if="gpsBusy" class="spinner"></span>{{ gpsBusy ? 'Locating…' : 'Use my location' }}</button>
            <span v-if="gpsActive" class="chip chip-gps">📍 GPS · {{ gpsDisplay }}<button type="button" class="chip-x" title="Clear GPS location" @click="clearGps">✕</button></span>
            <span v-if="settings.overridesArmed" class="chip chip-danger" title="Settings → Danger zone overrides are enabled">⚠ Overrides active · caps {{ hardLimits.max_distance_km }} km / {{ hardLimits.max_stores_per_company }} stores</span>
          </div>
          <fieldset class="company-picker"><legend>Compare supermarkets</legend><label v-for="company in companies" :key="company.id" class="company-option" :class="`company-${company.id.toLowerCase()}`"><input v-model="form.companies" type="checkbox" :value="company.id"><span class="checkmark"></span><span>{{ company.label }}</span></label></fieldset>
          <div class="form-actions">
            <button class="primary-button" :class="{ 'is-ready': readyToCompare && !loading }" type="submit" :disabled="loading || resolving || !form.companies.length || !canResolve"><span v-if="loading || resolving" class="spinner"></span>{{ actionLabel }}</button>
            <span class="hint">{{ actionHint }}</span>
          </div>
        </form>
        <p v-if="staleNotice && !loading" class="notice-banner">⚙ Parameters changed — check to resolve settings.</p>
        <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
      </section>

      <section class="panel ingredients-panel area-recipe">
        <div class="section-heading">
          <div><p class="eyebrow">Recipe breakdown</p><h3>{{ recipeMode === 'custom' ? 'Dish builder' : recipeMode === 'shopping' ? 'Shopping list' : 'Ingredient preview' }}</h3></div>
          <div class="heading-actions">
            <span v-if="builderIngredients.length" class="chip">{{ builderIngredients.length }} items</span>
            <button v-if="recipeMode === 'preset'" type="button" class="ghost-button ghost-small" :disabled="!form.dish" title="Copy this preset into the builder and edit it" @click="customiseFromPreset">Customise ✎</button>
            <template v-else>
              <button type="button" class="ghost-button ghost-small" :disabled="!draft.ingredients.length" :title="recipeMode === 'shopping' ? 'Remove every item from the shopping list' : 'Remove every ingredient row (dish name and base portions reset too)'" @click="clearBuilder">Clear all</button>
              <button v-if="recipeMode === 'custom'" type="button" class="ghost-button ghost-small" :disabled="savingPreset || !canSavePreset" :title="canSavePreset ? 'Store this recipe in data/dishes.json' : 'Complete the dish name and at least one ingredient row first'" @click="savePreset">{{ savingPreset ? 'Saving…' : 'Save as preset' }}</button>
            </template>
          </div>
        </div>
        <DishBuilder :mode="recipeMode === 'preset' ? 'locked' : 'edit'" :ingredients="builderIngredients" :duplicate-terms="duplicateTerms" :base-portions="builderBasePortions" :requested-portions="builderRequestedPortions" @add="addIngredient" @remove="removeIngredient" @patch="patchIngredient" />
        <p class="hint">{{ recipeHint }}</p>
      </section>

      <PipelineConsole class="area-terminal" :title="terminalTitle" :lines="consoleLines" :running="jobRunning" />

      <section class="panel map-panel area-map">
        <div class="section-heading"><div><p class="eyebrow">Coverage</p><h3>Nearby stores</h3></div><span v-if="originLabel" class="chip">{{ originLabel }}</span></div>
        <MapPanel :origin="mapOrigin" :stores="mapStores" :radius-km="form.distance_km" :winner-key="winnerKey" @select-store="focusStore" />
      </section>
    </div>

    <ProgressStrip :job="job" :running="jobRunning" :pct="overallPct" :elapsed="elapsedDisplay" />

    <ResultsSection ref="resultsSection" :result="result" :companies="companies" csv-download />
  </main>
</template>

<script>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import MapPanel from '../components/MapPanel.vue';
import PipelineConsole from '../components/PipelineConsole.vue';
import ProgressStrip from '../components/ProgressStrip.vue';
import ResultsSection from '../components/ResultsSection.vue';
import DishBuilder from '../components/DishBuilder.vue';
import { useJobRunner } from '../composables/useJobRunner.js';
import { normaliseUnit } from '../unitOptions.js';
import { storesOf, winnerKeyOf } from '../resultUtils.js';
import { settings } from '../settings.js';

const companyData = [{ id: 'PaknSave', label: "Pak'nSave" }, { id: 'NewWorld', label: 'New World' }, { id: 'Woolworths', label: 'Woolworths' }];
const NZ_BOUNDS = { latMin: -47.6, latMax: -34.2, lonMin: 166.2, lonMax: 178.9 };
const NORMAL_CAPS = { distance: 8, stores: 5 };
const OVERRIDE_CAPS = { distance: 50, stores: 20 };

export default {
  components: { MapPanel, PipelineConsole, ProgressStrip, ResultsSection, DishBuilder },
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
    let rowSeq = 0;
    const emptyRow = () => ({ id: `row-${++rowSeq}`, search_term: '', quantity: '', unit: 'g', approx_quantity: '', approx_unit: '' });
    const draft = reactive({ name: '', basePortions: 4, ingredients: [] });

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
    const canResolve = computed(() => canResolveBase.value && (gpsActive.value || !!form.address));
    const canSavePreset = computed(() => !!String(draft.name || '').trim() && validRows.value.length > 0 && duplicateTerms.value.size === 0);

    function addIngredient() { draft.ingredients.push(emptyRow()); }
    function removeIngredient(index) { draft.ingredients.splice(index, 1); }
    function patchIngredient(index, changes) { Object.assign(draft.ingredients[index], changes); }

    function clearBuilder() {
      const count = draft.ingredients.length;
      if (!count && !String(draft.name || '').trim() && Number(draft.basePortions) === 4) return;
      const message = recipeMode.value === 'shopping'
        ? `Clear all ${count} item${count === 1 ? '' : 's'} from the shopping list?`
        : 'Clear all ingredients?\nThe dish name and base portions will be reset too.';
      if (!window.confirm(message)) return;
      draft.ingredients = [];
      draft.name = '';
      draft.basePortions = 4;
      logLine('warn', 'DISH', `builder cleared — ${count} row${count === 1 ? '' : 's'} removed`);
    }

    function loadIntoDraft(key) {
      const dish = dishes.value.find((d) => d.key === key);
      if (!dish) return false;
      draft.name = dish.label;
      draft.basePortions = Number(dish.portion) || 4;
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
      logLine('ok', 'DISH', `customising "${draft.name}" — ${draft.ingredients.length} rows copied to builder`);
    }

    function setMode(mode) {
      if (mode === recipeMode.value) return;
      recipeMode.value = mode;
      // First visit to the builder: seed it with the currently selected preset.
      if (mode === 'custom' && !draft.ingredients.length && form.dish) {
        loadIntoDraft(form.dish);
        logLine('ok', 'DISH', `builder seeded from "${draft.name}" — edit freely or clear rows`);
      } else if (mode === 'custom') {
        logLine('phase', 'DISH', 'builder open — add ingredients manually');
      } else if (mode === 'shopping') {
        logLine('phase', 'DISH', 'shopping list — add items with the exact quantity you need');
      }
    }

    // ── Cross-view entry point (My Dishes → dashboard) ─────────────────────
    function loadPreset(key, edit = false) {
      if (!dishes.value.some((d) => d.key === key)) return;
      form.dish = key;
      if (edit) customiseFromPreset();
    }
    expose({ loadPreset });

    const builderPayloadRows = () => validRows.value.map((row) => (row.approx_quantity === null
      ? { search_term: row.search_term, quantity: row.quantity, unit: row.unit }
      : { ...row }));

    async function savePreset() {
      if (!canSavePreset.value || savingPreset.value) return;
      const name = String(draft.name).trim();
      const key = name.toLowerCase();
      if (dishes.value.some((d) => d.key === key) && !window.confirm(`"${name}" already exists as a preset.\nOverwrite it?`)) return;
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
          }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Could not save the preset');
        await fetchDishes();
        form.dish = data.key;
        recipeMode.value = 'preset';
        if (origin.value) staleNotice.value = true; // recipe changed vs resolved setup
        logLine('ok', 'DISH', `preset ${data.updated ? 'updated' : 'created'}: "${data.key}" · ${validRows.value.length} ingredients @ ${Number(draft.basePortions)} portions`);
      } catch (err) {
        error.value = err.message;
      } finally {
        savingPreset.value = false;
      }
    }

    const recipeHint = computed(() => {
      if (recipeMode.value === 'custom') return 'Each row becomes one search per store. The ≈ fields give cans/items a gram or ml equivalent so used-costs can be scaled.';
      if (recipeMode.value === 'shopping') return 'List the items you need with the quantity you want — each row is one search per store, priced as-is.';
      return 'These are the searches the price comparison will run. Use Customise to tweak them.';
    });

    // ── Location / map plumbing (shared behaviour with the standard page) ──
    const gpsActive = computed(() => !!gps.value);
    const gpsDisplay = computed(() => (gps.value ? `${gps.value.lat.toFixed(3)}, ${gps.value.lon.toFixed(3)}` : ''));
    const mapOrigin = computed(() => origin.value || result.value?.origin || null);
    const originLabel = computed(() => { const o = mapOrigin.value; if (!o) return ''; return o.source === 'gps' ? 'Using device GPS' : 'Geocoded origin'; });
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
        if (!validRows.value.length) return 'Add at least one ingredient with a term and quantity.';
        if (duplicateTerms.value.size) return 'Merge the highlighted duplicate search terms.';
      } else if (recipeMode.value === 'shopping') {
        if (!validRows.value.length) return 'Add at least one item with a term and quantity.';
        if (duplicateTerms.value.size) return 'Merge the highlighted duplicate search terms.';
      } else if (!form.dish) return 'Choose a dish first.';
      if (!resolved.value) return 'Step 1 — verify the dish and location first.';
      if (staleNotice.value) return 'Parameters changed — resolve again to continue.';
      if (!previewStores.value.length) return 'No stores in range — increase the distance or select more supermarkets.';
      return 'Dish and location verified — ready to compare.';
    });

    function useGps() {
      if (!navigator.geolocation) { error.value = 'Geolocation is not supported by this browser.'; return; }
      gpsBusy.value = true;
      navigator.geolocation.getCurrentPosition((pos) => {
        const { latitude, longitude } = pos.coords;
        if (latitude < NZ_BOUNDS.latMin || latitude > NZ_BOUNDS.latMax || longitude < NZ_BOUNDS.lonMin || longitude > NZ_BOUNDS.lonMax) {
          gpsBusy.value = false;
          error.value = 'Your device appears to be outside New Zealand — enter an NZ address instead.';
          return;
        }
        gps.value = { lat: latitude, lon: longitude };
        gpsBusy.value = false;
        error.value = '';
      }, (err) => {
        gpsBusy.value = false;
        error.value = err.code === err.PERMISSION_DENIED ? 'Location permission denied — enter an address instead.' : 'Could not get your location — enter an address instead.';
      }, { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
    }
    function clearGps() { gps.value = null; }
    function focusStore(pin) { resultsSection.value?.focusStore(pin); }

    // ── Danger-zone overrides: clamp helper + arming transitions ───────────
    function clampOverrides() {
      const caps = settings.overridesArmed ? OVERRIDE_CAPS : NORMAL_CAPS;
      form.distance_km = Math.min(caps.distance, Math.max(1, Math.round(Number(form.distance_km) || 5)));
      form.max_stores_per_company = Math.min(caps.stores, Math.max(1, Math.round(Number(form.max_stores_per_company) || 3)));
    }
    watch(() => settings.overridesArmed, (armed) => {
      clampOverrides();
      logLine('warn', 'SYS', armed
        ? `overrides armed — distance up to ${OVERRIDE_CAPS.distance} km, up to ${OVERRIDE_CAPS.stores} stores/company (hard server caps)`
        : 'overrides disarmed — inputs returned to standard ranges');
    });

    watch(() => form.address, () => { if (origin.value?.source === 'geocoded') { origin.value = null; logLine('warn', 'LOC', 'address changed — re-resolve location'); } });
    watch(gps, (lock) => {
      if (lock) { origin.value = { lat: lock.lat, lon: lock.lon, source: 'gps' }; logLine('ok', 'LOC', `device gps locked · ${lock.lat.toFixed(4)}, ${lock.lon.toFixed(4)}`); }
      else if (origin.value?.source === 'gps') { origin.value = null; logLine('warn', 'LOC', 'gps cleared'); }
    });
    watch(() => form.dish, (key) => {
      if (recipeMode.value !== 'preset') return;
      const dish = dishes.value.find((d) => d.key === key);
      if (!key) logLine('warn', 'DISH', 'recipe cleared — choose a dish');
      else if (dish) logLine('ok', 'DISH', `recipe refreshed · ${dish.label} · ${dish.ingredients.length} ingredient searches`);
      else logLine('warn', 'DISH', `recipe unavailable (${key})`);
    });

    const recipeSignature = computed(() => {
      if (recipeMode.value === 'preset') return ['preset', form.dish].join('|');
      if (recipeMode.value === 'shopping') return ['shopping', JSON.stringify(draft.ingredients)].join('|');
      return ['custom', draft.name, draft.basePortions, JSON.stringify(draft.ingredients)].join('|');
    });
    const settingsSignature = computed(() => [recipeSignature.value, form.address, form.portions, form.max_stores_per_company, form.distance_km, form.companies.join()].join('|'));
    watch(settingsSignature, () => { if (origin.value) { staleNotice.value = true; logLine('warn', 'SYS', 'parameters changed — check to resolve settings'); } });

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
      else {
        if (!form.address) { error.value = 'Enter an address or use device GPS.'; return; }
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
        error.value = `No stores found within ${form.distance_km} km — try increasing the distance or selecting more supermarkets.`;
        logLine('warn', 'LOC', `no stores within ${form.distance_km} km — increase the distance or select more supermarkets`);
        return;
      }
      staleNotice.value = false;
      logLine('ok', 'SYS', 'settings resolved — ready to compare');
    }
    function primaryAction() { readyToCompare.value ? runOptimise() : resolveSetup(); }

    async function runOptimise() {
      error.value = '';
      if (!previewStores.value.length) {
        error.value = `No stores found within ${form.distance_km} km — try increasing the distance or selecting more supermarkets.`;
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
      dishes.value = Object.entries(data).map(([key, dish]) => ({ key, label: dish.dish_name || key, portion: dish.portion || 4, ingredients: dish.ingredients || [], source: dish.source || 'curated' }));
    }

    onMounted(async () => {
      logLine('phase', 'SYS', 'dish-builder dashboard online');
      try {
        await fetchDishes();
        form.dish = dishes.value[0]?.key || '';
      } catch (err) { error.value = err.message; }
    });

    return {
      companies, dishes, form, addressHistory, gps, gpsBusy, gpsActive, gpsDisplay,
      useGps, clearGps, originLabel, mapOrigin, mapStores, winnerKey, focusStore,
      resolved, readyToCompare, canResolve, actionLabel, actionHint, primaryAction,
      staleNotice, error, loading, resolving,
      recipeMode, setMode, draft, builderIngredients, builderBasePortions,
      builderRequestedPortions, duplicateTerms, validRows,
      addIngredient, removeIngredient, patchIngredient, clearBuilder, customiseFromPreset,
      savePreset, savingPreset, canSavePreset, recipeHint, scaleDisplay,
      job, jobRunning, overallPct, elapsedDisplay, terminalTitle, consoleLines, result,
      resultsSection,
      settings, hardLimits, clampOverrides,
    };
  },
};
</script>
