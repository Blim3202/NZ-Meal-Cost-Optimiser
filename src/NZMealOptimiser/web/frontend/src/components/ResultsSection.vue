<template>
  <section v-if="result" class="results-area">
    <div class="result-heading"><div><p class="eyebrow">Comparison complete</p><h2>{{ result.dish }} <span v-if="result.dish_source === 'custom'" class="chip chip-custom">Custom recipe</span><span v-else-if="result.dish_source === 'shopping_list'" class="chip chip-shopping">Shopping list</span><span v-else-if="result.dish_source === 'curated'" class="chip">Preset</span></h2><p class="summary">{{ result.rows.length }} products across {{ result.store_costs.length }} stores · {{ result.companies_checked.join(', ') }}</p></div><time>{{ formatDate(result.timestamp) }}</time></div>
    <section class="panel">
      <div class="section-heading"><div><p class="eyebrow">Best value</p><h3>Store cost comparison</h3></div><select v-model="storeSort" aria-label="Sort stores"><option value="price">Lowest used cost</option><option value="store">Store name</option><option value="company">Company</option></select></div>
      <div v-if="!filteredStoreCosts.length" class="empty-state">No store cost data is available.</div>
      <div v-else class="store-list"><article v-for="(store, index) in filteredStoreCosts" :id="`store-card-${storeKey(store)}`" :key="storeKey(store)" class="store-card" :class="{ expanded: expandedStores.has(storeKey(store)) }"><button class="store-summary" type="button" @click="toggleStore(store)"><span class="rank">#{{ index + 1 }}</span><span class="store-name"><strong>{{ store.store }}</strong><small>{{ store.ingredients_matched }}/{{ store.ingredients_total }} ingredients matched<template v-if="store.issues && store.issues.length"> · ⚠ {{ store.issues.length }} unavailable</template></small></span><span class="badge" :class="badgeClass(store.company)">{{ companyLabel(store.company) }}</span><strong class="store-price" :class="{ 'price-partial': store.complete === false }" :title="store.complete === false ? 'Partial basket — some ingredients could not be priced at this store' : ''"><template v-if="store.complete === false">~</template>{{ money(store.total_used_cost) }}</strong><span class="chevron">⌄</span></button><div v-if="expandedStores.has(storeKey(store))" class="store-detail"><p v-if="store.issues && store.issues.length" class="issue-note">⚠ Unavailable ingredients: {{ store.issues.map((issue) => `${issue.search_ingredient} (${issue.status.replace(/_/g, ' ')})`).join(', ') }}</p><div class="detail-scroll"><table><thead><tr><th>Ingredient</th><th>Recipe Needed</th><th>Returned Product</th><th>Brand</th><th>Pack Size</th><th>Used Price</th><th>Purch Qty</th><th>Purch Cost</th><th>Status</th></tr></thead><tbody><tr v-for="item in store.best_per_ingredient" :key="item.search_ingredient"><td>{{ item.search_ingredient }}</td><td>{{ recipe(item) }}</td><td>{{ item.returned_ingredient || '-' }}</td><td>{{ item.brand || '-' }}</td><td>{{ pack(item) }}</td><td>{{ usedPrice(item) }}</td><td>{{ item.purchase_quantity || 0 }} pack(s)</td><td>{{ money(item.purchase_price) }}</td><td><span class="status" :class="statusClass(item.status)">{{ statusLabel(item.status) || '-' }}</span></td></tr></tbody></table></div></div></article></div>
    </section>
    <section class="panel">
      <div class="section-heading"><div><p class="eyebrow">Product detail</p><h3>All results <span class="count">({{ filteredRows.length }} of {{ result.rows.length }})</span></h3></div><button v-if="csvDownload" type="button" class="ghost-button ghost-small" :disabled="!filteredRows.length" title="Export the current filtered view as a CSV download" @click="downloadCsv">Download CSV ⭳</button></div>
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
          <option value="per_unit_price">Cost per unit</option>
          <option value="purchase_quantity">Purchase qty</option>
          <option value="purchase_price">Purchase cost</option>
        </select>
        <button v-if="numSortKey !== 'default'" type="button" class="dir-btn" @click="flipDir">{{ numSortDir === 'asc' ? '↑ asc' : '↓ desc' }}</button>
      </div>
      <div v-if="!filteredRows.length" class="empty-state">No products match the selected filter.</div>
      <div v-else class="detail-scroll"><table class="results-table"><thead><tr><th>Company</th><th>Store</th><th>Search Term</th><th>Returned Product</th><th>Brand</th><th>Recipe Needed</th><th>Price</th><th>Pack Size</th><th>Cost Per Unit</th><th>Used Price</th><th>Purch Qty</th><th>Purch Cost</th><th>Status</th><th>SKU</th></tr></thead><tbody><tr v-for="row in filteredRows" :key="`${row.company}-${row.store}-${row.sku}-${row.search_ingredient}`"><td><span class="badge" :class="badgeClass(row.company)">{{ companyLabel(row.company) }}</span></td><td>{{ row.store || '-' }}</td><td>{{ row.search_ingredient || '-' }}</td><td>{{ row.returned_ingredient || '-' }}</td><td>{{ row.brand || '-' }}</td><td>{{ recipe(row) }}</td><td>{{ money(row.price) }}</td><td>{{ pack(row) }}</td><td>{{ unitPrice(row) }}</td><td>{{ usedPrice(row) }}</td><td>{{ row.purchase_quantity || 0 }}</td><td>{{ money(row.purchase_price) }}</td><td><span class="status" :class="statusClass(row.status)">{{ statusLabel(row.status) || '-' }}</span></td><td>{{ row.sku || '-' }}</td></tr></tbody></table></div>
    </section>
  </section>
</template>

<script>
import { computed, nextTick, reactive, ref, watch } from 'vue';

const CAT_COLUMNS = ['company', 'store', 'search_ingredient', 'brand', 'status'];
const catLabels = { company: 'Company', store: 'Store', search_ingredient: 'Search term', brand: 'Brand', status: 'Status' };

export default {
  name: 'ResultsSection',
  props: {
    result: { type: Object, default: null },
    companies: { type: Array, required: true },
    csvDownload: { type: Boolean, default: false },
  },
  setup(props) {
    const expandedStores = ref(new Set());
    const storeSort = ref('price');
    const excluded = reactive(Object.fromEntries(CAT_COLUMNS.map((k) => [k, new Set()])));
    const textFilters = reactive({ returned_ingredient: '', sku: '' });
    const numSortKey = ref('default');
    const numSortDir = ref('asc');
    const openFilter = ref('');

    const catOptions = computed(() => {
      const rows = props.result?.rows || [];
      return Object.fromEntries(CAT_COLUMNS.map((k) => [k, [...new Set(rows.map((r) => r[k] || ''))].sort((a, b) => a.localeCompare(b))]));
    });

    watch(() => props.result, () => resetFilters());

    function resetFilters() {
      CAT_COLUMNS.forEach((k) => excluded[k].clear());
      textFilters.returned_ingredient = '';
      textFilters.sku = '';
      numSortKey.value = 'default';
      numSortDir.value = 'asc';
      openFilter.value = '';
      expandedStores.value = new Set();
    }

    const filteredRows = computed(() => {
      let rows = props.result?.rows || [];
      for (const key of CAT_COLUMNS) { const ex = excluded[key]; if (ex.size) rows = rows.filter((r) => !ex.has(r[key] || '')); }
      const productQuery = textFilters.returned_ingredient.trim().toLowerCase();
      if (productQuery) rows = rows.filter((r) => (r.returned_ingredient || '').toLowerCase().includes(productQuery));
      const skuQuery = textFilters.sku.trim().toLowerCase();
      if (skuQuery) rows = rows.filter((r) => (r.sku || '').toLowerCase().includes(skuQuery));
      rows = [...rows];
      if (numSortKey.value !== 'default') {
        const dir = numSortDir.value === 'asc' ? 1 : -1;
        const key = numSortKey.value;
        const num = (r) => { const v = r[key]; const n = Number(v); return v === '' || v === null || v === undefined || Number.isNaN(n) ? null : n; };
        rows.sort((a, b) => {
          const av = num(a); const bv = num(b);
          if (av === null && bv === null) return 0;
          if (av === null) return 1; // rows without a value always sink to the bottom
          if (bv === null) return -1;
          return dir * (av - bv);
        });
      } else {
        rows.sort((a, b) => (a.company || '').localeCompare(b.company || '') || (a.store || '').localeCompare(b.store || '') || (a.search_ingredient || '').localeCompare(b.search_ingredient || ''));
      }
      return rows;
    });

    const filteredStoreCosts = computed(() => {
      const stores = [...(props.result?.store_costs || [])];
      if (storeSort.value === 'store') return stores.sort((a, b) => a.store.localeCompare(b.store));
      if (storeSort.value === 'company') return stores.sort((a, b) => a.company.localeCompare(b.company) || a.store.localeCompare(b.store));
      return stores.sort((a, b) => ((a.complete === false) - (b.complete === false)) || a.total_used_cost - b.total_used_cost);
    });

    function toggleCat(key, value) { const set = excluded[key]; set.has(value) ? set.delete(value) : set.add(value); }
    function shownCount(key) { return catOptions.value[key].length - excluded[key].size; }
    function toggleOpen(key) { openFilter.value = openFilter.value === key ? '' : key; }
    function flipDir() { numSortDir.value = numSortDir.value === 'asc' ? 'desc' : 'asc'; }

    function toggleStore(store) { const next = new Set(expandedStores.value); const key = storeKey(store); next.has(key) ? next.delete(key) : next.add(key); expandedStores.value = next; }
    function storeKey(store) { return `${store.company}-${store.store}`; }

    // Map pin click → expand that store's card and scroll it into view.
    function focusStore(pin) {
      const key = `${pin.company}-${pin.store}`;
      if (!expandedStores.value.has(key)) toggleStore({ company: pin.company, store: pin.store });
      nextTick(() => document.getElementById(`store-card-${key}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }));
    }

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
    function companyLabel(company) { return props.companies.find((item) => item.id === company)?.label || company; }
    function badgeClass(company) { return `badge-${company.toLowerCase()}`; }
    function statusClass(status) { return `status-${(status || 'error').replace('_', '-')}`; }
    // Payload statuses are snake_case ("not_found", "incompatible_units");
    // display them with spaces.
    function statusLabel(status) { return (status || '').replace(/_/g, ' '); }
    function formatDate(value) { return value ? new Date(value).toLocaleString() : ''; }

    const CSV_HEADER = ['Company', 'Store', 'Search Term', 'Returned Product', 'Brand', 'Recipe Needed', 'Price', 'Pack Size', 'Cost Per Unit', 'Used Price', 'Purch Qty', 'Purch Cost', 'Status', 'SKU'];
    const csvNum = (value) => (value === '' || value === null || value === undefined || Number.isNaN(Number(value)) ? '' : Number(value));
    const csvUnitPrice = (row) => (row.per_unit_price === '' || row.per_unit_price === null || row.per_unit_price === undefined || Number.isNaN(Number(row.per_unit_price)) ? '' : `${Number(row.per_unit_price).toFixed(2)}/${row.per_unit_quantity || ''}`);
    const CSV_CELL_GETTERS = [
      (r) => companyLabel(r.company),
      (r) => r.store,
      (r) => r.search_ingredient,
      (r) => r.returned_ingredient,
      (r) => r.brand,
      (r) => recipe(r),
      (r) => csvNum(r.price),
      (r) => pack(r),
      (r) => csvUnitPrice(r),
      (r) => csvNum(r.used_price),
      (r) => r.purchase_quantity ?? 0,
      (r) => csvNum(r.purchase_price),
      (r) => statusLabel(r.status),
      (r) => r.sku,
    ];
    function csvCell(value) {
      const text = String(value ?? '');
      return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
    }
    function downloadCsv() {
      if (!filteredRows.value.length) return;
      const lines = [CSV_HEADER.join(',')];
      for (const row of filteredRows.value) lines.push(CSV_CELL_GETTERS.map((get) => csvCell(get(row))).join(','));
      const blob = new Blob(['\uFEFF' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      const slug = String(props.result?.dish || 'results').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'results';
      link.href = url;
      link.download = `${slug}-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    }

    return { expandedStores, storeSort, excluded, textFilters, numSortKey, numSortDir, openFilter, catLabels, catOptions, filteredRows, filteredStoreCosts, resetFilters, focusStore, toggleCat, shownCount, toggleOpen, flipDir, toggleStore, storeKey, money, usedPrice, recipe, pack, unitPrice, companyLabel, badgeClass, statusClass, statusLabel, formatDate, downloadCsv };
  },
};
</script>
