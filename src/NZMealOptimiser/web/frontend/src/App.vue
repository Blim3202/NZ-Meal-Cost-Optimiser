<template>
  <main class="shell">
    <header class="hero">
      <div><p class="eyebrow">NZ grocery intelligence</p><h1>Meal cost optimiser</h1><p class="lede">Compare the ingredients for a meal across nearby supermarkets.</p></div>
      <a class="legacy-link" href="/test">Open dish-builder beta</a>
    </header>

    <div class="home-grid">
      <section class="panel search-panel area-form">
        <form @submit.prevent="primaryAction">
          <div class="form-grid">
            <label class="field field-wide"><span>Dish</span><select v-model="form.dish" required><option disabled value="">Choose a dish</option><option v-for="dish in dishes" :key="dish.key" :value="dish.key">{{ dish.label }}</option></select></label>
            <label class="field field-wide"><span>NZ address</span><input v-model.trim="form.address" list="address-history" placeholder="Auckland CBD" :disabled="gpsActive" :required="!gpsActive"><datalist id="address-history"><option v-for="address in addressHistory" :key="address" :value="address" /></datalist></label>
            <label class="field field-sm"><span>Distance</span><select v-model.number="form.distance_km"><option v-for="km in 8" :key="km" :value="km">{{ km }} km</option></select></label>
            <label class="field field-sm"><span>Portions</span><input v-model.number="form.portions" type="number" min="2" max="12" required></label>
            <label class="field field-sm"><span>Max stores / company</span><select v-model.number="form.max_stores_per_company"><option v-for="count in 5" :key="count" :value="count">{{ count }}</option></select></label>
          </div>
          <div class="gps-row">
            <button type="button" class="ghost-button" :disabled="gpsBusy || gpsActive" @click="useGps"><span v-if="gpsBusy" class="spinner"></span>{{ gpsBusy ? 'Locating…' : 'Use my location' }}</button>
            <span v-if="gpsActive" class="chip chip-gps">📍 GPS · {{ gpsDisplay }}<button type="button" class="chip-x" title="Clear GPS location" @click="clearGps">✕</button></span>
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
        <div class="section-heading"><div><p class="eyebrow">Recipe breakdown</p><h3>Ingredient preview</h3></div><span v-if="dishIngredients.length" class="chip">{{ dishIngredients.length }} items</span></div>
        <DishBuilder mode="locked" :ingredients="dishIngredients" />
        <p class="hint">These are the searches the price comparison will run.</p>
      </section>
      <PipelineConsole class="area-terminal" :title="terminalTitle" :lines="consoleLines" :running="jobRunning" />
      <section class="panel map-panel area-map">
        <div class="section-heading"><div><p class="eyebrow">Coverage</p><h3>Nearby stores</h3></div><span v-if="originLabel" class="chip">{{ originLabel }}</span></div>
        <MapPanel :origin="mapOrigin" :stores="mapStores" :radius-km="form.distance_km" :winner-key="winnerKey" @select-store="focusStore" />
      </section>
    </div>

    <ProgressStrip :job="job" :running="jobRunning" :pct="overallPct" :elapsed="elapsedDisplay" />

    <ResultsSection ref="resultsSection" :result="result" :companies="companies" />
  </main>
</template>

<script>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import MapPanel from './components/MapPanel.vue';
import PipelineConsole from './components/PipelineConsole.vue';
import ProgressStrip from './components/ProgressStrip.vue';
import ResultsSection from './components/ResultsSection.vue';
import DishBuilder from './components/DishBuilder.vue';
import { useJobRunner } from './composables/useJobRunner.js';
import { storesOf, winnerKeyOf } from './resultUtils.js';

const companyData = [{ id: 'PaknSave', label: "Pak'nSave" }, { id: 'NewWorld', label: 'New World' }, { id: 'Woolworths', label: 'Woolworths' }];
const NZ_BOUNDS = { latMin: -47.6, latMax: -34.2, lonMin: 166.2, lonMax: 178.9 };

export default {
  components: { MapPanel, PipelineConsole, ProgressStrip, ResultsSection, DishBuilder },
  setup() {
    const {
      job, result, loading, error, logLine, start,
      jobRunning, overallPct, elapsedDisplay, terminalTitle, consoleLines,
    } = useJobRunner();

    const dishes = ref([]);
    const form = reactive({ dish: '', address: '', distance_km: 5, portions: 4, max_stores_per_company: 3, companies: companyData.map((company) => company.id) });
    const addressHistory = ref(JSON.parse(localStorage.getItem('meal-addresses') || '[]')); const companies = companyData;
    const gps = ref(null); const gpsBusy = ref(false);
    const origin = ref(null); const resolving = ref(false);
    const previewStores = ref([]); const staleNotice = ref(false);
    const resultsSection = ref(null);

    // Map data: origin prefers a live GPS lock (instant preview), then falls
    // back to the run's resolved origin; pins come from store_costs geo.
    const gpsActive = computed(() => !!gps.value);
    const gpsDisplay = computed(() => (gps.value ? `${gps.value.lat.toFixed(3)}, ${gps.value.lon.toFixed(3)}` : ''));
    const mapOrigin = computed(() => origin.value || result.value?.origin || null);
    const originLabel = computed(() => { const o = mapOrigin.value; if (!o) return ''; return o.source === 'gps' ? 'Using device GPS' : 'Geocoded origin'; });
    const mapStores = computed(() => storesOf(result.value, previewStores.value));
    const winnerKey = computed(() => winnerKeyOf(result.value));
    const resolved = computed(() => !!origin.value);
    const readyToCompare = computed(() => resolved.value && !staleNotice.value && previewStores.value.length > 0);
    const canResolve = computed(() => !!form.dish && (gpsActive.value || !!form.address));
    const actionLabel = computed(() => (loading.value ? 'Comparing prices...' : resolving.value ? 'Resolving…' : readyToCompare.value ? 'Compare prices' : 'Resolve setup'));
    const actionHint = computed(() => {
      if (!form.companies.length) return 'Select at least one supermarket.';
      if (loading.value) return 'Results stream into the console below.';
      if (resolving.value) return 'Checking dish and location…';
      if (!form.dish) return 'Choose a dish first.';
      if (!resolved.value) return 'Step 1 — verify the dish and location first.';
      if (staleNotice.value) return 'Parameters changed — resolve again to continue.';
      if (!previewStores.value.length) return 'No stores in range — increase the distance or select more supermarkets.';
      return 'Dish and location verified — ready to compare.';
    });
    const dishIngredients = computed(() => dishes.value.find((d) => d.key === form.dish)?.ingredients || []);

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

    watch(() => form.address, () => { if (origin.value?.source === 'geocoded') { origin.value = null; logLine('warn', 'LOC', 'address changed — re-resolve location'); } });
    watch(gps, (lock) => {
      if (lock) { origin.value = { lat: lock.lat, lon: lock.lon, source: 'gps' }; logLine('ok', 'LOC', `device gps locked · ${lock.lat.toFixed(4)}, ${lock.lon.toFixed(4)}`); }
      else if (origin.value?.source === 'gps') { origin.value = null; logLine('warn', 'LOC', 'gps cleared'); }
    });
    watch(() => form.dish, (key) => {
      const dish = dishes.value.find((d) => d.key === key);
      if (!key) logLine('warn', 'DISH', 'recipe cleared — choose a dish');
      else if (dish) logLine('ok', 'DISH', `recipe refreshed · ${dish.label} · ${dish.ingredients.length} ingredient searches`);
      else logLine('warn', 'DISH', `recipe unavailable (${key})`);
    });

    // Any setup change after a successful resolve makes the verification
    // stale: the button flips back to "Resolve setup" and a notice appears,
    // while the map/recipe previews stay live.
    const settingsSignature = computed(() => [form.dish, form.address, form.portions, form.max_stores_per_company, form.distance_km, form.companies.join()].join('|'));
    watch(settingsSignature, () => { if (origin.value) { staleNotice.value = true; logLine('warn', 'SYS', 'parameters changed — check to resolve settings'); } });

    // Store preview tracks origin + search shape; refires on resolve success,
    // distance/company/max changes, and clears itself when origin is lost.
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
      if (!form.dish) { error.value = 'Choose a dish first.'; return; }
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
        addressHistory.value = history; localStorage.setItem('meal-addresses', JSON.stringify(history));
      }
      const payload = { ...form };
      if (origin.value) { payload.latitude = origin.value.lat; payload.longitude = origin.value.lon; }
      if (gpsActive.value) payload.address = 'Device GPS location';
      resultsSection.value?.resetFilters();
      await start(payload);
    }

    onMounted(async () => {
      logLine('phase', 'SYS', 'dashboard online');
      try { const response = await fetch('/dishes'); if (!response.ok) throw new Error('Could not load dishes'); const data = await response.json(); dishes.value = Object.entries(data).map(([key, dish]) => ({ key, label: dish.dish_name || key, portion: dish.portion || 4, ingredients: dish.ingredients || [] })); form.dish = dishes.value[0]?.key || ''; } catch (err) { error.value = err.message; }
    });

    return {
      actionHint, actionLabel, addressHistory, canResolve, clearGps, companies,
      consoleLines, dishIngredients, dishes, elapsedDisplay, error, focusStore,
      form, gpsActive, gpsBusy, gpsDisplay, job, jobRunning, loading, mapOrigin,
      mapStores, originLabel, overallPct, primaryAction, readyToCompare, resolving, resolved,
      resolveSetup, result, resultsSection, staleNotice, terminalTitle, useGps,
      winnerKey,
    };
  },
};
</script>
