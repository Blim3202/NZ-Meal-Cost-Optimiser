<template>
  <main class="shell">
    <header class="hero">
      <div><p class="eyebrow">NZ grocery intelligence</p><h1>Meal cost optimiser</h1><p class="lede">Compare the ingredients for a meal across nearby supermarkets.</p></div>
      <a class="legacy-link" href="/">Open classic dashboard</a>
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
        <p v-if="!dishIngredients.length" class="empty-state">Choose a dish to preview its ingredient searches.</p>
        <ul v-else class="ingredient-list">
          <li v-for="(ing, index) in dishIngredients" :key="`${ing.search_term}-${index}`"><span class="ing-name">{{ ing.search_term }}</span><span class="ing-qty">{{ ing.quantity }} {{ ing.unit }}<template v-if="ing.approx_quantity"> · ~{{ ing.approx_quantity }} {{ ing.approx_unit }}</template></span></li>
        </ul>
        <p class="hint">These are the searches the price comparison will run.</p>
      </section>
      <section class="terminal area-terminal">
        <header class="terminal-head"><span class="tl-dot"></span><span class="tl-dot"></span><span class="tl-dot"></span><span class="terminal-title">pipeline console — {{ terminalTitle }}</span></header>
        <div class="terminal-body" ref="terminalEl">
          <p v-for="line in consoleLines" :key="line.key" class="t-line" :class="`t-${line.kind}`"><span class="t-time">{{ line.boot ? line.time : `+${line.t.toFixed(1)}s` }}</span><span v-if="line.co" class="t-tag" :class="`tag-${line.co.toLowerCase()}`">{{ line.co }}</span><span class="t-text">{{ line.text }}</span></p>
          <p v-if="jobRunning" class="t-line t-caret"><span class="caret">▍</span></p>
        </div>
      </section>
      <section class="panel map-panel area-map">
        <div class="section-heading"><div><p class="eyebrow">Coverage</p><h3>Nearby stores</h3></div><span v-if="originLabel" class="chip">{{ originLabel }}</span></div>
        <MapPanel :origin="mapOrigin" :stores="mapStores" :radius-km="form.distance_km" :winner-key="winnerKey" @select-store="focusStore" />
      </section>
    </div>

    <section v-if="jobVisible" class="progress-strip">
      <div class="strip-top">
        <div class="strip-phase"><p class="eyebrow">Live progress</p><strong>{{ job.phase || 'Working…' }}</strong></div>
        <div class="overall-bar" :class="{ indeterminate: jobRunning && !job.total_tasks }"><div class="overall-fill" :style="{ width: overallPct + '%' }"></div></div>
        <div class="job-meta">
          <span class="chip chip-brand">⏱ {{ elapsedDisplay }}</span>
          <span class="chip">{{ job.done_tasks }}/{{ job.total_tasks }} searches</span>
          <span class="chip">{{ job.products_found }} products</span>
        </div>
      </div>
      <div class="brand-tiles strip-tiles">
        <article v-for="c in job.companies" :key="c.id" class="brand-tile" :class="[tileClass(c), `tile-${c.id.toLowerCase()}`]">
          <svg viewBox="0 0 48 48" class="ring" aria-hidden="true"><circle class="ring-bg" cx="24" cy="24" r="20" /><circle v-if="!c.stores_total" class="ring-fill ring-idle" cx="24" cy="24" r="20" /><circle v-else class="ring-fill" cx="24" cy="24" r="20" :style="ringStyle(c)" /><path v-if="c.stores_total && c.stores_done === c.stores_total" class="ring-check" d="M15.5 24.5l6 6 11-12.5" /></svg>
          <div class="tile-body">
            <header><strong>{{ c.label }}</strong><small>{{ c.stores_done }}/{{ c.stores_total || '…' }} stores</small></header>
            <p class="tile-products">{{ c.products }}<em> products</em></p>
          </div>
        </article>
      </div>
    </section>

    <section v-if="result" class="results-area">
      <div class="result-heading"><div><p class="eyebrow">Comparison complete</p><h2>{{ result.dish }}</h2><p class="summary">{{ result.rows.length }} products across {{ result.store_costs.length }} stores · {{ result.companies_checked.join(', ') }}</p></div><time>{{ formatDate(result.timestamp) }}</time></div>
      <section class="panel">
        <div class="section-heading"><div><p class="eyebrow">Best value</p><h3>Store cost comparison</h3></div><select v-model="storeSort" aria-label="Sort stores"><option value="price">Lowest used cost</option><option value="store">Store name</option><option value="company">Company</option></select></div>
        <div v-if="!filteredStoreCosts.length" class="empty-state">No store cost data is available.</div>
        <div v-else class="store-list"><article v-for="(store, index) in filteredStoreCosts" :id="`store-card-${storeKey(store)}`" :key="storeKey(store)" class="store-card" :class="{ expanded: expandedStores.has(storeKey(store)) }"><button class="store-summary" type="button" @click="toggleStore(store)"><span class="rank">#{{ index + 1 }}</span><span class="store-name"><strong>{{ store.store }}</strong><small>{{ store.ingredients_matched }}/{{ store.ingredients_total }} ingredients matched<template v-if="store.issues && store.issues.length"> · ⚠ {{ store.issues.length }} failed</template></small></span><span class="badge" :class="badgeClass(store.company)">{{ companyLabel(store.company) }}</span><strong class="store-price">{{ money(store.total_used_cost) }}</strong><span class="chevron">⌄</span></button><div v-if="expandedStores.has(storeKey(store))" class="store-detail"><p v-if="store.issues && store.issues.length" class="issue-note">⚠ Unresolved searches: {{ store.issues.map((issue) => `${issue.search_ingredient} (${issue.status})`).join(', ') }}</p><div class="detail-scroll"><table><thead><tr><th>Ingredient</th><th>Recipe Needed</th><th>Returned Product</th><th>Brand</th><th>Pack Size</th><th>Used Price</th><th>Purch Qty</th><th>Purch Cost</th><th>Status</th></tr></thead><tbody><tr v-for="item in store.best_per_ingredient" :key="item.search_ingredient"><td>{{ item.search_ingredient }}</td><td>{{ recipe(item) }}</td><td>{{ item.returned_ingredient || '-' }}</td><td>{{ item.brand || '-' }}</td><td>{{ pack(item) }}</td><td>{{ usedPrice(item) }}</td><td>{{ item.purchase_quantity || 0 }} pack(s)</td><td>{{ money(item.purchase_price) }}</td><td><span class="status" :class="statusClass(item.status)">{{ item.status || '-' }}</span></td></tr></tbody></table></div></div></article></div>
      </section>
      <section class="panel">
        <div class="section-heading"><div><p class="eyebrow">Product detail</p><h3>All results <span class="count">({{ filteredRows.length }} of {{ result.rows.length }})</span></h3></div></div>
        <div class="filter-bar">
          <div v-for="(values, key) in catOptions" :key="key" class="cat-filter" :class="{ open: openFilter === key, active: shownCount(key) < values.length }" @click.stop>
            <button type="button" class="cat-toggle" @click="toggleOpen(key)">{{ catLabels[key] }}<span class="cat-count">{{ shownCount(key) }}/{{ values.length }}</span></button>
            <div v-if="openFilter === key" class="cat-list">
              <label v-for="v in values" :key="v" class="cat-option"><input type="checkbox" :checked="!excluded[key].has(v)" @change="toggleCat(key, v)"><span>{{ v || '(blank)' }}</span></label>
            </div>
          </div>
          <input v-model="textFilters.returned_ingredient" class="text-filter" placeholder="Search product…" type="search">
          <input v-model="textFilters.sku" class="text-filter text-filter-sku" placeholder="SKU…" type="search">
          <select v-model="numSortKey" class="num-sort" aria-label="Numeric sort">
            <option value="default">Sort: Company / Store / Term</option>
            <option value="price">Price</option>
            <option value="purchase_quantity">Purchase qty</option>
            <option value="purchase_price">Purchase cost</option>
          </select>
          <button v-if="numSortKey !== 'default'" type="button" class="dir-btn" @click="flipDir">{{ numSortDir === 'asc' ? '↑ asc' : '↓ desc' }}</button>
        </div>
        <div v-if="!filteredRows.length" class="empty-state">No products match the selected filter.</div>
        <div v-else class="detail-scroll"><table class="results-table"><thead><tr><th>Company</th><th>Store</th><th>Search Term</th><th>Returned Product</th><th>Brand</th><th>Recipe Needed</th><th>Price</th><th>Pack Size</th><th>Cost Per Unit</th><th>Used Price</th><th>Purch Qty</th><th>Purch Cost</th><th>Status</th><th>SKU</th></tr></thead><tbody><tr v-for="row in filteredRows" :key="`${row.company}-${row.store}-${row.sku}-${row.search_ingredient}`"><td><span class="badge" :class="badgeClass(row.company)">{{ companyLabel(row.company) }}</span></td><td>{{ row.store || '-' }}</td><td>{{ row.search_ingredient || '-' }}</td><td>{{ row.returned_ingredient || '-' }}</td><td>{{ row.brand || '-' }}</td><td>{{ recipe(row) }}</td><td>{{ money(row.price) }}</td><td>{{ pack(row) }}</td><td>{{ unitPrice(row) }}</td><td>{{ usedPrice(row) }}</td><td>{{ row.purchase_quantity || 0 }}</td><td>{{ money(row.purchase_price) }}</td><td><span class="status" :class="statusClass(row.status)">{{ row.status || '-' }}</span></td><td>{{ row.sku || '-' }}</td></tr></tbody></table></div>
      </section>
    </section>
  </main>
</template>

<script>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue';
import MapPanel from './components/MapPanel.vue';

const companyData = [{ id: 'PaknSave', label: "Pak'nSave" }, { id: 'NewWorld', label: 'New World' }, { id: 'Woolworths', label: 'Woolworths' }];
const POLL_MS = 700;
const RING_CIRCUMFERENCE = 2 * Math.PI * 20;
const CAT_COLUMNS = ['company', 'store', 'search_ingredient', 'brand', 'status'];
const catLabels = { company: 'Company', store: 'Store', search_ingredient: 'Search term', brand: 'Brand', status: 'Status' };
const NZ_BOUNDS = { latMin: -47.6, latMax: -34.2, lonMin: 166.2, lonMax: 178.9 };

export default {
  components: { MapPanel },
  setup() {
    const dishes = ref([]); const result = ref(null); const error = ref(''); const loading = ref(false); const expandedStores = ref(new Set());
    const storeSort = ref('price');
    const form = reactive({ dish: '', address: '', distance_km: 5, portions: 4, max_stores_per_company: 3, companies: companyData.map((company) => company.id) });
    const addressHistory = ref(JSON.parse(localStorage.getItem('meal-addresses') || '[]')); const companies = companyData;
    const gps = ref(null); const gpsBusy = ref(false);
    const origin = ref(null); const resolving = ref(false);
    const previewStores = ref([]); const staleNotice = ref(false);
    const feed = ref([]); let feedSeq = 0;
    const clockNow = () => { const d = new Date(); return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`; };
    function logLine(kind, co, text) { feed.value.push({ key: `feed-${++feedSeq}`, boot: true, time: clockNow(), kind, co, text }); }

    // Map data: origin prefers a live GPS lock (instant preview), then falls
    // back to the run's resolved origin; pins come from store_costs geo.
    const gpsActive = computed(() => !!gps.value);
    const gpsDisplay = computed(() => (gps.value ? `${gps.value.lat.toFixed(3)}, ${gps.value.lon.toFixed(3)}` : ''));
    const mapOrigin = computed(() => origin.value || result.value?.origin || null);
    const originLabel = computed(() => { const o = mapOrigin.value; if (!o) return ''; return o.source === 'gps' ? 'Using device GPS' : 'Geocoded origin'; });
    const hasStoreCoords = (s) => s.lat !== null && s.lon !== null && s.lat !== undefined && s.lon !== undefined;
    const mapStores = computed(() => {
      if (result.value) return (result.value.store_costs || []).filter(hasStoreCoords);
      return previewStores.value;
    });
    const winnerKey = computed(() => {
      const costs = result.value?.store_costs || [];
      if (!costs.length) return '';
      const best = costs.reduce((a, b) => (b.total_used_cost < a.total_used_cost ? b : a));
      return `${best.company}-${best.store}`;
    });
    const resolved = computed(() => !!origin.value);
    const readyToCompare = computed(() => resolved.value && !staleNotice.value);
    const canResolve = computed(() => !!form.dish && (gpsActive.value || !!form.address));
    const actionLabel = computed(() => (loading.value ? 'Comparing prices...' : resolving.value ? 'Resolving…' : readyToCompare.value ? 'Compare prices' : 'Resolve setup'));
    const actionHint = computed(() => {
      if (!form.companies.length) return 'Select at least one supermarket.';
      if (loading.value) return 'Results stream into the console below.';
      if (resolving.value) return 'Checking dish and location…';
      if (!resolved.value) return 'Step 1 — verify the dish and location first.';
      if (staleNotice.value) return 'Parameters changed — resolve again to continue.';
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
      if (!o) { previewStores.value = []; return; }
      try {
        const params = new URLSearchParams({ lat: String(o.lat), lon: String(o.lon), distance_km: String(form.distance_km), max_per_company: String(form.max_stores_per_company), companies: form.companies.join(',') });
        const response = await fetch(`/stores/nearby?${params}`);
        const data = await response.json();
        previewStores.value = response.ok ? (data.stores || []) : [];
        if (response.ok && previewStores.value.length) {
          const n = previewStores.value.length;
          logLine('ok', 'LOC', `location refreshed · ${n} store${n === 1 ? '' : 's'} in range · ${form.distance_km} km radius`);
        }
      } catch { previewStores.value = []; }
    }

    async function resolveSetup() {
      error.value = '';
      if (!form.dish) { error.value = 'Choose a dish first.'; return; }
      if (gpsActive.value) { origin.value = { lat: gps.value.lat, lon: gps.value.lon, source: 'gps' }; staleNotice.value = false; logLine('ok', 'SYS', 'settings resolved — ready to compare'); return; }
      if (!form.address) { error.value = 'Enter an address or use device GPS.'; return; }
      resolving.value = true;
      try {
        const response = await fetch(`/geocode?address=${encodeURIComponent(form.address)}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Could not resolve that address');
        origin.value = { lat: data.lat, lon: data.lon, source: 'geocoded' };
        staleNotice.value = false;
        logLine('ok', 'LOC', `geocoded "${form.address}" → ${data.lat.toFixed(4)}, ${data.lon.toFixed(4)}`);
        logLine('ok', 'SYS', 'settings resolved — ready to compare');
      } catch (err) { error.value = err.message; } finally { resolving.value = false; }
    }
    function primaryAction() { readyToCompare.value ? runOptimise() : resolveSetup(); }

    function focusStore(pin) {
      const key = `${pin.company}-${pin.store}`;
      if (!expandedStores.value.has(key)) toggleStore({ company: pin.company, store: pin.store });
      nextTick(() => document.getElementById(`store-card-${key}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }));
    }

    // All-results filter bar: excluded-value sets per categorical column
    // (empty set = column unfiltered), substring lookups for text columns,
    // and an optional numeric sort with direction.
    const excluded = reactive(Object.fromEntries(CAT_COLUMNS.map((k) => [k, new Set()])));
    const textFilters = reactive({ returned_ingredient: '', sku: '' });
    const numSortKey = ref('default'); const numSortDir = ref('asc');
    const openFilter = ref('');
    const catOptions = computed(() => {
      const rows = result.value?.rows || [];
      return Object.fromEntries(CAT_COLUMNS.map((k) => [k, [...new Set(rows.map((r) => r[k] || ''))].sort((a, b) => a.localeCompare(b))]));
    });

    // Live job state, driven by POST /optimise/jobs + GET /optimise/{id} polling
    const job = reactive({ id: null, status: 'idle', phase: '', companies: [], events: [], total_tasks: 0, done_tasks: 0, products_found: 0, error_detail: '', elapsed: 0 });
    let cursor = -1; let pollTimer = null; let tickTimer = null; let pollRun = 0;
    const terminalEl = ref(null);

    const jobVisible = computed(() => job.status !== 'idle');
    const jobRunning = computed(() => job.status === 'queued' || job.status === 'running');
    const overallPct = computed(() => (job.total_tasks ? Math.round((job.done_tasks / job.total_tasks) * 100) : 0));
    const elapsedDisplay = computed(() => formatElapsed(job.elapsed));
    const terminalTitle = computed(() => (job.events.length ? `${job.events.length} events` : 'standby'));
    const consoleLines = computed(() => [...feed.value, ...job.events.map((event) => ({ ...event, key: `ev-${event.i}` }))]);
    watch(() => consoleLines.value.length, () => { scrollTerminal(); });

    onMounted(async () => {
      document.addEventListener('click', () => { openFilter.value = ''; });
      logLine('phase', 'SYS', 'dashboard online');
      try { const response = await fetch('/dishes'); if (!response.ok) throw new Error('Could not load dishes'); const data = await response.json(); dishes.value = Object.entries(data).map(([key, dish]) => ({ key, label: dish.dish_name || key, ingredients: dish.ingredients || [] })); form.dish = dishes.value[0]?.key || ''; } catch (err) { error.value = err.message; }
    });
    async function runOptimise() {
      error.value = ''; result.value = null;
      if (!gpsActive.value && form.address) {
        const history = [form.address, ...addressHistory.value.filter((address) => address !== form.address)].slice(0, 5);
        addressHistory.value = history; localStorage.setItem('meal-addresses', JSON.stringify(history));
      }
      stopTimers(); resetFilters();
      Object.assign(job, { id: null, status: 'queued', phase: 'Queuing…', companies: [], events: [], total_tasks: 0, done_tasks: 0, products_found: 0, error_detail: '', elapsed: 0 });
      cursor = -1; loading.value = true;
      const run = ++pollRun;
      const payload = { ...form };
      if (origin.value) { payload.latitude = origin.value.lat; payload.longitude = origin.value.lon; }
      if (gpsActive.value) payload.address = 'Device GPS location';
      try {
        const response = await fetch('/optimise/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...payload, companies: payload.companies.length ? payload.companies : undefined }) });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Could not start the optimisation');
        job.id = data.job_id;
        tickTimer = setInterval(() => { if (jobRunning.value) job.elapsed += 0.25; }, 250);
        poll(run);
      } catch (err) { error.value = err.message; loading.value = false; job.status = 'idle'; }
    }

    async function poll(run) {
      if (!job.id || run !== pollRun) return;
      try {
        const response = await fetch(`/optimise/${job.id}?events_since=${cursor}`);
        if (!response.ok) throw new Error(`Poll failed (${response.status})`);
        applySnapshot(await response.json());
        if (job.status === 'complete' || job.status === 'error') { finishJob(); return; }
      } catch { /* transient network hiccup — keep polling */ }
      if (run === pollRun) pollTimer = setTimeout(() => poll(run), POLL_MS);
    }

    function applySnapshot(d) {
      job.status = d.status; job.phase = d.phase;
      job.total_tasks = d.total_tasks; job.done_tasks = d.done_tasks; job.products_found = d.products_found;
      job.elapsed = Math.max(job.elapsed, d.elapsed_seconds || 0);
      if (d.companies.length) job.companies = d.companies;
      if (d.events && d.events.length) { job.events.push(...d.events); cursor = d.next_cursor; scrollTerminal(); }
      if (d.status === 'error') job.error_detail = d.error_detail || '';
      if (d.result) result.value = d.result;
    }

    function finishJob() {
      stopTimers();
      loading.value = false;
      if (job.status === 'error') error.value = job.error_detail || 'The optimisation failed';
    }

    function stopTimers() { clearTimeout(pollTimer); clearInterval(tickTimer); tickTimer = null; }

    function scrollTerminal() { nextTick(() => { const el = terminalEl.value; if (el) el.scrollTop = el.scrollHeight; }); }
    function formatElapsed(seconds) {
      const sec = Math.max(0, seconds || 0);
      if (sec < 60) return `${sec.toFixed(1)}s`;
      return `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, '0')}`;
    }
    function ringStyle(c) { const frac = c.stores_total ? c.stores_done / c.stores_total : 0; return { strokeDashoffset: String(RING_CIRCUMFERENCE * (1 - frac)) }; }
    function tileClass(c) { return { 'is-running': jobRunning.value, 'is-done': !jobRunning.value && c.stores_total > 0 && c.stores_done === c.stores_total }; }
    function resetFilters() {
      CAT_COLUMNS.forEach((k) => excluded[k].clear());
      textFilters.returned_ingredient = ''; textFilters.sku = '';
      numSortKey.value = 'default'; numSortDir.value = 'asc'; openFilter.value = '';
    }
    function toggleCat(key, value) { const set = excluded[key]; set.has(value) ? set.delete(value) : set.add(value); }
    function shownCount(key) { return catOptions.value[key].length - excluded[key].size; }
    function toggleOpen(key) { openFilter.value = openFilter.value === key ? '' : key; }
    function flipDir() { numSortDir.value = numSortDir.value === 'asc' ? 'desc' : 'asc'; }

    const filteredRows = computed(() => {
      let rows = result.value?.rows || [];
      for (const key of CAT_COLUMNS) { const ex = excluded[key]; if (ex.size) rows = rows.filter((r) => !ex.has(r[key] || '')); }
      const productQuery = textFilters.returned_ingredient.trim().toLowerCase();
      if (productQuery) rows = rows.filter((r) => (r.returned_ingredient || '').toLowerCase().includes(productQuery));
      const skuQuery = textFilters.sku.trim().toLowerCase();
      if (skuQuery) rows = rows.filter((r) => (r.sku || '').toLowerCase().includes(skuQuery));
      rows = [...rows];
      if (numSortKey.value !== 'default') {
        const dir = numSortDir.value === 'asc' ? 1 : -1;
        const key = numSortKey.value;
        rows.sort((a, b) => dir * ((Number(a[key]) || 0) - (Number(b[key]) || 0)));
      } else {
        rows.sort((a, b) => (a.company || '').localeCompare(b.company || '') || (a.store || '').localeCompare(b.store || '') || (a.search_ingredient || '').localeCompare(b.search_ingredient || ''));
      }
      return rows;
    });
    const filteredStoreCosts = computed(() => { const stores = [...(result.value?.store_costs || [])]; if (storeSort.value === 'store') return stores.sort((a, b) => a.store.localeCompare(b.store)); if (storeSort.value === 'company') return stores.sort((a, b) => a.company.localeCompare(b.company) || a.store.localeCompare(b.store)); return stores.sort((a, b) => a.total_used_cost - b.total_used_cost); });
    function toggleStore(store) { const next = new Set(expandedStores.value); const key = storeKey(store); next.has(key) ? next.delete(key) : next.add(key); expandedStores.value = next; }
    function storeKey(store) { return `${store.company}-${store.store}`; }
    function money(value) { return value === '' || value === null || value === undefined || Number.isNaN(Number(value)) ? '-' : `$${Number(value).toFixed(2)}`; }
    function usedPrice(item) {
      const val = money(item.used_price);
      if (val === '-') return '-';
      return item.status === 'approximate' ? `~${val}` : val;
    }
    function recipe(item) { const main = [item.ingredient_quantity, item.ingredient_measurement].filter((value) => value !== '' && value !== null && value !== undefined).join(' '); const approx = [item.ingredient_approx_quantity, item.ingredient_approx_unit].filter((value) => value !== '' && value !== null && value !== undefined && value !== 0).join(' '); return main + (approx ? ` (~${approx})` : '') || '-'; }
    function pack(item) { return [item.quantity, item.measurement_unit].filter((value) => value !== '' && value !== null && value !== undefined).join(' ') || '-'; }
    function unitPrice(row) {
      if (row.per_unit_price === '' || row.per_unit_price === null || row.per_unit_price === undefined || Number.isNaN(Number(row.per_unit_price))) return '-';
      const formatted = `$${Number(row.per_unit_price).toFixed(2)}/${row.per_unit_quantity || ''}`;
      return row.status === 'approximate' ? `~${formatted}` : formatted;
    }
    function companyLabel(company) { return companies.find((item) => item.id === company)?.label || company; }
    function badgeClass(company) { return `badge-${company.toLowerCase()}`; }
    function statusClass(status) { return `status-${(status || 'error').replace('_', '-')}`; }
    function formatDate(value) { return value ? new Date(value).toLocaleString() : ''; }
    return { actionHint, actionLabel, addressHistory, canResolve, catLabels, catOptions, clearGps, companies, consoleLines, dishIngredients, dishes, elapsedDisplay, error, excluded, expandedStores, filteredRows, filteredStoreCosts, flipDir, focusStore, form, formatDate, companyLabel, badgeClass, gps, gpsActive, gpsBusy, gpsDisplay, job, jobRunning, jobVisible, loading, mapOrigin, mapStores, money, numSortDir, numSortKey, openFilter, originLabel, overallPct, pack, primaryAction, readyToCompare, recipe, resolving, resolved, resolveSetup, result, ringStyle, shownCount, statusClass, staleNotice, storeKey, storeSort, terminalEl, terminalTitle, textFilters, tileClass, toggleCat, toggleOpen, toggleStore, unitPrice, usedPrice, useGps, winnerKey };
  }
};
</script>
