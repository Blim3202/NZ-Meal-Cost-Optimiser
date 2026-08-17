<template>
  <main class="shell">
    <header class="hero">
      <div><p class="eyebrow">NZ grocery intelligence</p><h1>Meal cost optimiser</h1><p class="lede">Compare the ingredients for a meal across nearby supermarkets.</p></div>
      <a class="legacy-link" href="/">Open classic dashboard</a>
    </header>

    <section class="panel search-panel">
      <form @submit.prevent="runOptimise">
        <div class="form-grid">
          <label class="field field-wide"><span>Dish</span><select v-model="form.dish" required><option disabled value="">Choose a dish</option><option v-for="dish in dishes" :key="dish.key" :value="dish.key">{{ dish.label }}</option></select></label>
          <label class="field field-wide"><span>NZ address</span><input v-model.trim="form.address" list="address-history" placeholder="Auckland CBD" required><datalist id="address-history"><option v-for="address in addressHistory" :key="address" :value="address" /></datalist></label>
          <label class="field"><span>Distance</span><select v-model.number="form.distance_km"><option v-for="km in 8" :key="km" :value="km">{{ km }} km</option></select></label>
          <label class="field"><span>Portions</span><input v-model.number="form.portions" type="number" min="2" max="12" required></label>
          <label class="field"><span>Max stores / company</span><select v-model.number="form.max_stores_per_company"><option v-for="count in 5" :key="count" :value="count">{{ count }}</option></select></label>
        </div>
        <fieldset class="company-picker"><legend>Compare supermarkets</legend><label v-for="company in companies" :key="company.id" class="company-option" :class="`company-${company.id.toLowerCase()}`"><input v-model="form.companies" type="checkbox" :value="company.id"><span class="checkmark"></span><span>{{ company.label }}</span></label></fieldset>
        <div class="form-actions"><button class="primary-button" type="submit" :disabled="loading || !form.companies.length"><span v-if="loading" class="spinner"></span>{{ loading ? 'Comparing prices...' : 'Compare prices' }}</button><span class="hint">Searches up to {{ form.max_stores_per_company }} stores per selected company.</span></div>
      </form>
      <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
    </section>

    <section v-if="result" class="results-area">
      <div class="result-heading"><div><p class="eyebrow">Comparison complete</p><h2>{{ result.dish }}</h2><p class="summary">{{ result.rows.length }} products across {{ result.store_costs.length }} stores · {{ result.companies_checked.join(', ') }}</p></div><time>{{ formatDate(result.timestamp) }}</time></div>
      <section class="panel">
        <div class="section-heading"><div><p class="eyebrow">Best value</p><h3>Store cost comparison</h3></div><select v-model="storeSort" aria-label="Sort stores"><option value="price">Lowest used cost</option><option value="store">Store name</option><option value="company">Company</option></select></div>
        <div v-if="!filteredStoreCosts.length" class="empty-state">No store cost data is available.</div>
        <div v-else class="store-list"><article v-for="(store, index) in filteredStoreCosts" :key="storeKey(store)" class="store-card" :class="{ expanded: expandedStores.has(storeKey(store)) }"><button class="store-summary" type="button" @click="toggleStore(store)"><span class="rank">#{{ index + 1 }}</span><span class="store-name"><strong>{{ store.store }}</strong><small>{{ store.ingredients_matched }}/{{ store.ingredients_total }} ingredients matched</small></span><span class="badge" :class="badgeClass(store.company)">{{ companyLabel(store.company) }}</span><strong class="store-price">{{ money(store.total_used_cost) }}</strong><span class="chevron">⌄</span></button><div v-if="expandedStores.has(storeKey(store))" class="store-detail"><div class="detail-scroll"><table><thead><tr><th>Ingredient</th><th>Recipe Needed</th><th>Returned Product</th><th>Pack Size</th><th>Used Price</th><th>Purch Qty</th><th>Purch Cost</th><th>Status</th></tr></thead><tbody><tr v-for="item in store.best_per_ingredient" :key="item.search_ingredient"><td>{{ item.search_ingredient }}</td><td>{{ recipe(item) }}</td><td>{{ item.returned_ingredient || '-' }}</td><td>{{ pack(item) }}</td><td>{{ money(item.used_price) }}</td><td>{{ item.purchase_quantity || 0 }} pack(s)</td><td>{{ money(item.purchase_price) }}</td><td><span class="status" :class="statusClass(item.status)">{{ item.status || '-' }}</span></td></tr></tbody></table></div></div></article></div>
      </section>
      <section class="panel">
        <div class="section-heading results-toolbar"><div><p class="eyebrow">Product detail</p><h3>All results <span class="count">({{ filteredRows.length }} of {{ result.rows.length }})</span></h3></div><div class="filters"><select v-model="rowCompany" aria-label="Filter by company"><option value="all">All companies</option><option v-for="company in result.companies_checked" :key="company" :value="company">{{ companyLabel(company) }}</option></select><select v-model="rowSort" aria-label="Sort products"><option value="price">Price: low to high</option><option value="store">Store</option><option value="company">Company</option><option value="ingredient">Ingredient</option></select></div></div>
        <div v-if="!filteredRows.length" class="empty-state">No products match the selected filter.</div>
        <div v-else class="detail-scroll"><table class="results-table"><thead><tr><th>Company</th><th>Store</th><th>Search Term</th><th>Returned Product</th><th>Recipe Needed</th><th>Price</th><th>Pack Size</th><th>Cost Per Unit</th><th>Used Price</th><th>Purch Qty</th><th>Purch Cost</th><th>Status</th><th>SKU</th></tr></thead><tbody><tr v-for="row in filteredRows" :key="`${row.company}-${row.store}-${row.sku}-${row.search_ingredient}`"><td><span class="badge" :class="badgeClass(row.company)">{{ companyLabel(row.company) }}</span></td><td>{{ row.store || '-' }}</td><td>{{ row.search_ingredient || '-' }}</td><td>{{ row.returned_ingredient || '-' }}</td><td>{{ recipe(row) }}</td><td>{{ money(row.price) }}</td><td>{{ pack(row) }}</td><td>{{ unitPrice(row) }}</td><td>{{ money(row.used_price) }}</td><td>{{ row.purchase_quantity || 0 }}</td><td>{{ money(row.purchase_price) }}</td><td><span class="status" :class="statusClass(row.status)">{{ row.status || '-' }}</span></td><td>{{ row.sku || '-' }}</td></tr></tbody></table></div>
      </section>
    </section>
  </main>
</template>

<script>
import { computed, onMounted, reactive, ref } from 'vue';

const companyData = [{ id: 'PaknSave', label: "Pak'nSave" }, { id: 'NewWorld', label: 'New World' }, { id: 'Woolworths', label: 'Woolworths' }];

export default {
  setup() {
    const dishes = ref([]); const result = ref(null); const error = ref(''); const loading = ref(false); const expandedStores = ref(new Set());
    const rowCompany = ref('all'); const rowSort = ref('price'); const storeSort = ref('price');
    const form = reactive({ dish: '', address: '', distance_km: 5, portions: 4, max_stores_per_company: 3, companies: companyData.map((company) => company.id) });
    const addressHistory = ref(JSON.parse(localStorage.getItem('meal-addresses') || '[]')); const companies = companyData;

    onMounted(async () => {
      try { const response = await fetch('/dishes'); if (!response.ok) throw new Error('Could not load dishes'); const data = await response.json(); dishes.value = Object.entries(data).map(([key, dish]) => ({ key, label: dish.dish_name || key })); form.dish = dishes.value[0]?.key || ''; } catch (err) { error.value = err.message; }
    });
    async function runOptimise() {
      error.value = ''; result.value = null; loading.value = true;
      const history = [form.address, ...addressHistory.value.filter((address) => address !== form.address)].slice(0, 5); addressHistory.value = history; localStorage.setItem('meal-addresses', JSON.stringify(history));
      try { const response = await fetch('/optimise', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...form, companies: form.companies.length ? form.companies : undefined }) }); const data = await response.json(); if (!response.ok) throw new Error(data.detail || 'The optimisation request failed'); result.value = data; } catch (err) { error.value = err.message; } finally { loading.value = false; }
    }
    const filteredRows = computed(() => sortRows([...((result.value?.rows || []).filter((row) => rowCompany.value === 'all' || row.company === rowCompany.value))], rowSort.value));
    const filteredStoreCosts = computed(() => { const stores = [...(result.value?.store_costs || [])]; if (storeSort.value === 'store') return stores.sort((a, b) => a.store.localeCompare(b.store)); if (storeSort.value === 'company') return stores.sort((a, b) => a.company.localeCompare(b.company) || a.store.localeCompare(b.store)); return stores.sort((a, b) => a.total_used_cost - b.total_used_cost); });
    function sortRows(rows, mode) { return rows.sort((a, b) => mode === 'store' ? (a.store || '').localeCompare(b.store || '') : mode === 'company' ? (a.company || '').localeCompare(b.company || '') : mode === 'ingredient' ? (a.search_ingredient || '').localeCompare(b.search_ingredient || '') : Number(a.price || 0) - Number(b.price || 0)); }
    function toggleStore(store) { const next = new Set(expandedStores.value); const key = storeKey(store); next.has(key) ? next.delete(key) : next.add(key); expandedStores.value = next; }
    function storeKey(store) { return `${store.company}-${store.store}`; }
    function money(value) { return value === '' || value === null || value === undefined || Number.isNaN(Number(value)) ? '-' : `$${Number(value).toFixed(2)}`; }
    function recipe(item) { const main = [item.ingredient_quantity, item.ingredient_measurement].filter((value) => value !== '' && value !== null && value !== undefined).join(' '); const approx = [item.ingredient_approx_quantity, item.ingredient_approx_unit].filter((value) => value !== '' && value !== null && value !== undefined && value !== 0).join(' '); return main + (approx ? ` (~${approx})` : '') || '-'; }
    function pack(item) { return [item.quantity, item.measurement_unit].filter((value) => value !== '' && value !== null && value !== undefined).join(' ') || '-'; }
    function unitPrice(row) { return row.per_unit_price !== '' && row.per_unit_price !== null && row.per_unit_price !== undefined ? `$${row.per_unit_price}/${row.per_unit_quantity}` : '-'; }
    function companyLabel(company) { return companies.find((item) => item.id === company)?.label || company; }
    function badgeClass(company) { return `badge-${company.toLowerCase()}`; }
    function statusClass(status) { return `status-${(status || 'error').replace('_', '-')}`; }
    function formatDate(value) { return value ? new Date(value).toLocaleString() : ''; }
    return { addressHistory, companies, dishes, error, expandedStores, filteredRows, filteredStoreCosts, form, formatDate, companyLabel, badgeClass, loading, money, pack, recipe, result, rowCompany, rowSort, runOptimise, statusClass, storeKey, storeSort, toggleStore, unitPrice };
  }
};
</script>
