<template>
  <div class="all-results">
    <div class="ar-toolbar">
      <span class="count">Showing {{ filteredRows.length }} of {{ result?.rows?.length || 0 }} products</span>
      <button v-if="csvDownload" type="button" class="ghost-button ghost-small" :disabled="!filteredRows.length" title="Export the current filtered view as a CSV download" @click="downloadCsv">Download CSV ⭳</button>
    </div>
    <div class="filter-bar">
      <div v-for="(values, key) in catOptions" :key="key" class="cat-filter" :class="{ open: openFilter === key, active: shownCount(key) < values.length }" @click.stop>
        <button type="button" class="cat-toggle" @click="toggleOpen(key)">{{ catLabels[key] }}<span class="cat-count">{{ shownCount(key) }}/{{ values.length }}</span></button>
        <div v-if="openFilter === key" class="cat-list">
          <label v-for="v in values" :key="v" class="cat-option"><input type="checkbox" :checked="!excluded[key].has(v)" @change="toggleCat(key, v)"><span>{{ v || '(blank)' }}</span></label>
        </div>
      </div>
      <input v-model="textFilters.returned_ingredient" class="text-filter" placeholder="Search product…" type="search">
      <input v-model="textFilters.sku" class="text-filter text-filter-sku" placeholder="SKU…" type="search">
      <button type="button" class="ghost-button ghost-small hide-toggle" :disabled="!incompatibleCount && !hideIncompatible" :title="hideIncompatible ? 'Show every product again' : 'Hide products rejected by ingredient filters or unit mismatches'" @click="toggleHideIncompatible">{{ hideIncompatible ? 'Show all' : `Hide incompatible (${incompatibleCount})` }}</button>
    </div>
    <div v-if="!filteredRows.length" class="empty-state">No products match the selected filter.</div>
    <div v-else class="detail-scroll">
      <table class="results-table">
        <thead>
          <tr>
            <th v-for="col in COLUMNS" :key="col.key" :class="{ sortable: true, active: sortKey === col.key }" :title="`Sort by ${col.label}`" @click="sortBy(col)">
              {{ col.label }}<span v-if="sortKey === col.key" class="sort-ind">{{ sortDir === 'asc' ? '▲' : '▼' }}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in filteredRows" :key="`${row.company}-${row.store}-${row.sku}-${row.search_ingredient}`" :class="{ 'row-invalid': row.valid_ingredient === false, 'row-unit-no': unitState(row) === 'no' }">
            <td><span class="badge" :class="badgeClass(row.company)">{{ companyLabel(row.company) }}</span></td>
            <td>{{ row.store || '-' }}</td>
            <td>{{ row.search_ingredient || '-' }}</td>
            <td>{{ row.returned_ingredient || '-' }}</td>
            <td>{{ row.brand || '-' }}</td>
            <td>{{ recipe(row) }}</td>
            <td>{{ money(row.price) }}</td>
            <td>{{ pack(row) }}</td>
            <td>{{ unitPrice(row) }}</td>
            <td>{{ usedPrice(row) }}</td>
            <td>{{ row.purchase_quantity || 0 }}</td>
            <td>{{ money(row.purchase_price) }}</td>
            <td><span class="match-cell" :class="unitMatchClass(row)" :title="unitMatchTitle(row)">{{ unitMatchText(row) }}</span></td>
            <td><span class="match-cell" :class="ingMatchClass(row)" :title="ingMatchTitle(row)">{{ ingMatchText(row) }}</span></td>
            <td>{{ row.sku || '-' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script>
import { computed, reactive, ref, watch } from 'vue';

const CAT_COLUMNS = ['company', 'store', 'search_ingredient', 'brand'];
const catLabels = { company: 'Company', store: 'Store', search_ingredient: 'Search term', brand: 'Brand' };

// Column registry drives both the sortable headers and the default ordering.
const COLUMNS = [
  { key: 'company', label: 'Company', get: (r) => r.company || '' },
  { key: 'store', label: 'Store', get: (r) => r.store || '' },
  { key: 'search_ingredient', label: 'Search Term', get: (r) => r.search_ingredient || '' },
  { key: 'returned_ingredient', label: 'Returned Product', get: (r) => r.returned_ingredient || '' },
  { key: 'brand', label: 'Brand', get: (r) => r.brand || '' },
  { key: '_recipe', label: 'Recipe Needed' },
  { key: 'price', label: 'Price', num: true, get: (r) => r.price },
  { key: '_pack', label: 'Pack Size' },
  { key: 'per_unit_price', label: 'Cost Per Unit', num: true, get: (r) => r.per_unit_price },
  { key: 'used_price', label: 'Used Price', num: true, get: (r) => r.used_price },
  { key: 'purchase_quantity', label: 'Purch Qty', num: true, get: (r) => r.purchase_quantity },
  { key: 'purchase_price', label: 'Purch Cost', num: true, get: (r) => r.purchase_price },
  // Derived booleans sort ✓-first ascending; blanks sink with the nulls.
  { key: '_unit_match', label: 'Unit Match', num: true },
  { key: '_ing_match', label: 'Ingredient Match', num: true },
  { key: 'sku', label: 'SKU', get: (r) => r.sku || '' },
];

export default {
  name: 'AllResultsPanel',
  props: {
    result: { type: Object, default: null },
    companies: { type: Array, required: true },
    csvDownload: { type: Boolean, default: true },
  },
  setup(props) {
    const excluded = reactive(Object.fromEntries(CAT_COLUMNS.map((k) => [k, new Set()])));
    const textFilters = reactive({ returned_ingredient: '', sku: '' });
    const openFilter = ref('');
    const sortKey = ref('');
    const sortDir = ref('asc');
    const hideIncompatible = ref(false);

    const catOptions = computed(() => {
      const rows = props.result?.rows || [];
      return Object.fromEntries(CAT_COLUMNS.map((k) => [k, [...new Set(rows.map((r) => r[k] || ''))].sort((a, b) => a.localeCompare(b))]));
    });

    function ingOk(row) { return row.valid_ingredient !== false; }
    // Unit-match classification reads only row.status — the single authoritative
    // field stamped by parse_optimiser_columns. Absent status = never scaled → 'na'.
    function unitState(row) {
      if (!row.status) return 'na';
      if (row.status === 'ok') return 'ok';
      if (row.status === 'approximate') return 'approx';
      return 'no';
    }
    function compatible(row) { return ingOk(row) && unitState(row) !== 'no'; }
    function unitSortValue(row) { return { na: null, ok: 0, approx: 1, no: 2 }[unitState(row)]; }
    function ingSortValue(row) { return row.valid_ingredient === undefined && row.status === undefined ? null : (ingOk(row) ? 0 : 1); }

    const incompatibleCount = computed(() => (props.result?.rows || []).filter((r) => !compatible(r)).length);
    function toggleHideIncompatible() { hideIncompatible.value = !hideIncompatible.value; }

    watch(() => props.result, () => resetFilters());

    function resetFilters() {
      CAT_COLUMNS.forEach((k) => excluded[k].clear());
      textFilters.returned_ingredient = '';
      textFilters.sku = '';
      openFilter.value = '';
      sortKey.value = '';
      sortDir.value = 'asc';
      hideIncompatible.value = false;
    }

    const filteredRows = computed(() => {
      let rows = props.result?.rows || [];
      for (const key of CAT_COLUMNS) { const ex = excluded[key]; if (ex.size) rows = rows.filter((r) => !ex.has(r[key] || '')); }
      const productQuery = textFilters.returned_ingredient.trim().toLowerCase();
      if (productQuery) rows = rows.filter((r) => (r.returned_ingredient || '').toLowerCase().includes(productQuery));
      const skuQuery = textFilters.sku.trim().toLowerCase();
      if (skuQuery) rows = rows.filter((r) => (r.sku || '').toLowerCase().includes(skuQuery));
      if (hideIncompatible.value) rows = rows.filter(compatible);

      rows = [...rows];
      const col = COLUMNS.find((c) => c.key === sortKey.value);
      if (!col) {
        rows.sort((a, b) => (a.company || '').localeCompare(b.company || '') || (a.store || '').localeCompare(b.store || '') || (a.search_ingredient || '').localeCompare(b.search_ingredient || ''));
        return rows;
      }
      const dir = sortDir.value === 'asc' ? 1 : -1;
      const valueOf = (r) => {
        if (col.key === '_recipe') return recipe(r);
        if (col.key === '_pack') return pack(r);
        if (col.key === '_unit_match') return unitSortValue(r);
        if (col.key === '_ing_match') return ingSortValue(r);
        return col.get(r);
      };
      rows.sort((a, b) => {
        const av = valueOf(a);
        const bv = valueOf(b);
        const aNum = col.num ? toNum(av) : null;
        const bNum = col.num ? toNum(bv) : null;
        if (col.num) {
          if (aNum === null && bNum === null) return 0;
          if (aNum === null) return 1; // blank values always sink
          if (bNum === null) return -1;
          return dir * (aNum - bNum);
        }
        const as = String(av ?? '');
        const bs = String(bv ?? '');
        if (!as && !bs) return 0;
        if (!as) return 1;
        if (!bs) return -1;
        return dir * as.localeCompare(bs);
      });
      return rows;
    });

    function toNum(v) {
      if (v === '' || v === null || v === undefined || typeof v === 'boolean') return v === true ? 0 : v === false ? 1 : null;
      const n = Number(v);
      return Number.isNaN(n) ? null : n;
    }

    function sortBy(col) {
      if (sortKey.value === col.key) sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc';
      else { sortKey.value = col.key; sortDir.value = 'asc'; }
    }

    function toggleCat(key, value) { const set = excluded[key]; set.has(value) ? set.delete(value) : set.add(value); }
    function shownCount(key) { return catOptions.value[key].length - excluded[key].size; }
    function toggleOpen(key) { openFilter.value = openFilter.value === key ? '' : key; }

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

    function unitMatchClass(row) { return `m-${unitState(row)}`; }
    function unitMatchText(row) { return { na: '–', ok: '✓', approx: '~', no: '✗' }[unitState(row)]; }
    function unitMatchTitle(row) {
      return {
        na: 'No scaling data for this row',
        approx: 'Partial match — scaled via ≈ pack equivalent',
        ok: 'Pack matches the recipe units',
        no: 'Pack does not match the recipe units — needs ≈ equivalent',
      }[unitState(row)];
    }
    function ingMatchClass(row) { return ingOk(row) ? 'm-ok' : 'm-no'; }
    function ingMatchText(row) { return ingOk(row) ? '✓' : '✗'; }
    function ingMatchTitle(row) { return ingOk(row) ? 'Passed the ingredient filters' : row.filter_reason || 'Rejected by ingredient filters'; }

    // ── CSV export (current filtered view) ─────────────────────────────────
    const CSV_HEADER = ['Company', 'Store', 'Search Term', 'Returned Product', 'Brand', 'Recipe Needed', 'Price', 'Pack Size', 'Cost Per Unit', 'Used Price', 'Purch Qty', 'Purch Cost', 'Unit Match', 'Ingredient Match', 'SKU'];
    const csvNum = (value) => (value === '' || value === null || value === undefined || Number.isNaN(Number(value)) ? '' : Number(value));
    const csvUnitPrice = (row) => (row.per_unit_price === '' || row.per_unit_price === null || row.per_unit_price === undefined || Number.isNaN(Number(row.per_unit_price)) ? '' : `${Number(row.per_unit_price).toFixed(2)}/${row.per_unit_quantity || ''}`);
    const matchWord = (ok) => (ok ? 'yes' : 'no');
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
      (r) => ({ ok: 'yes', approx: 'partial', no: 'no', na: '' }[unitState(r)]),
      (r) => matchWord(ingOk(r)),
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

    return {
      COLUMNS, catLabels, catOptions, excluded, textFilters, openFilter, sortKey, sortDir,
      hideIncompatible, incompatibleCount, toggleHideIncompatible,
      filteredRows, resetFilters, sortBy, toggleCat, shownCount, toggleOpen,
      money, usedPrice, recipe, pack, unitPrice, companyLabel, badgeClass,
      unitState, unitMatchClass, unitMatchText, unitMatchTitle, ingMatchClass, ingMatchText, ingMatchTitle,
      downloadCsv,
    };
  },
};
</script>
