<template>
  <div class="summary-panel">
    <div class="summary-controls">
      <div class="seg-toggle" role="group" aria-label="Cost basis">
        <button type="button" class="seg-btn" :class="{ active: settings.summaryBasis === 'used' }" title="Rank by the scaled cost of using each product in this recipe" @click="settings.summaryBasis = 'used'">Used cost</button>
        <button type="button" class="seg-btn" :class="{ active: settings.summaryBasis === 'purchase' }" title="Rank by the shelf price of the packs you would buy" @click="settings.summaryBasis = 'purchase'">Purchase cost</button>
      </div>
      <div class="seg-toggle" role="group" aria-label="Basket mode">
        <button type="button" class="seg-btn" :class="{ active: settings.basketMode === 'single' }" title="One store for the whole recipe" @click="settings.basketMode = 'single'">Single store</button>
        <button type="button" class="seg-btn" :class="{ active: settings.basketMode === 'multi' }" title="Cheapest eligible product per ingredient, any store" @click="settings.basketMode = 'multi'">Best across stores</button>
      </div>
    </div>

    <!-- ── Single-store ranking ──────────────────────────────────────────── -->
    <template v-if="settings.basketMode === 'single'">
      <div v-if="!rankedStores.length" class="empty-state">No store cost data is available.</div>
      <div v-else class="store-list">
        <article v-for="(store, index) in rankedStores" :id="`store-card-${store.key}`" :key="store.key" class="store-card" :class="{ expanded: expandedStores.has(store.key) }">
          <button class="store-summary" type="button" @click="toggleStore(store.key)">
            <span class="rank">#{{ index + 1 }}</span>
            <span class="store-name"><strong>{{ store.store }}</strong><small>{{ store.matched }}/{{ store.totalTerms }} ingredients matched<template v-if="store.allIssues.length"> · ⚠ {{ store.allIssues.length }} unavailable</template></small></span>
            <span class="badge" :class="badgeClass(store.company)">{{ companyLabel(store.company) }}</span>
            <span class="store-price-wrap"><strong class="store-price" :class="{ 'price-partial': !store.complete }"><template v-if="!store.complete">~</template>{{ money(store.total) }}</strong><small class="alt-cost">{{ altLabel }} {{ money(store.altTotal) }}</small></span>
            <span class="chevron">⌄</span>
          </button>
          <div v-if="expandedStores.has(store.key)" class="store-detail">
            <p v-if="store.allIssues.length" class="issue-note">⚠ Unavailable ingredients: {{ store.allIssues.map((issue) => `${issue.term} (${issue.detail})`).join(', ') }}</p>
            <div class="detail-scroll">
              <table>
                <thead><tr><th>Ingredient</th><th>Recipe Needed</th><th>Returned Product</th><th>Brand</th><th>Pack Size</th><th>Used Price</th><th>Purch Qty</th><th>Purch Cost</th><th>Status</th></tr></thead>
                <tbody>
                  <tr v-for="item in store.picks" :key="item.term" :class="{ 'row-invalid': item.missing }">
                    <td>{{ item.term }}</td>
                    <td>{{ item.recipe }}</td>
                    <td>{{ item.title || '-' }}</td>
                    <td>{{ item.brand || '-' }}</td>
                    <td>{{ item.pack }}</td>
                    <td>{{ item.usedDisplay }}</td>
                    <td>{{ item.purchQty }}</td>
                    <td :class="{ 'cell-primary': settings.summaryBasis === 'purchase' && !item.missing }">{{ item.purchDisplay }}</td>
                    <td>{{ item.statusLabel }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </article>
      </div>
    </template>

    <!-- ── Cross-store smart basket ──────────────────────────────────────── -->
    <template v-else>
      <div v-if="!basket.items.length && !basket.missing.length" class="empty-state">No eligible products — nothing could be priced.</div>
      <article v-else class="basket-card">
        <div class="basket-head">
          <div>
            <p class="eyebrow">Smart basket</p>
            <h3 class="basket-total">{{ money(basket.total) }}<span v-if="basket.missing.length" class="price-partial">~</span></h3>
            <p class="contrib-line">{{ basket.coverage }}/{{ basket.totalTerms }} ingredients · {{ contributionLine || 'no stores needed' }}</p>
          </div>
          <span class="chip">{{ basisLabel }}</span>
        </div>
        <p v-if="basket.missing.length" class="issue-note">⚠ No eligible product anywhere for: {{ basket.missing.join(', ') }}</p>
        <div class="detail-scroll">
          <table>
            <thead><tr><th>Ingredient</th><th>Source Store</th><th>Returned Product</th><th>Brand</th><th>Used Price</th><th>Purch Cost</th><th>Status</th></tr></thead>
            <tbody>
              <tr v-for="item in basket.items" :key="item.term">
                <td>{{ item.term }}</td>
                <td><span class="badge" :class="badgeClass(item.company)">{{ companyLabel(item.company) }}</span> {{ item.store }}</td>
                <td>{{ item.title }}</td>
                <td>{{ item.brand || '-' }}</td>
                <td :class="{ 'cell-primary': settings.summaryBasis === 'used' }">{{ item.usedDisplay }}</td>
                <td :class="{ 'cell-primary': settings.summaryBasis === 'purchase' }">{{ item.purchDisplay }}</td>
                <td>{{ item.statusLabel }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>
    </template>
  </div>
</template>

<script>
import { computed, ref, watch } from 'vue';
import { settings } from '../settings.js';

// Summary tab: re-ranks stores CLIENT-SIDE from result.rows so the Used /
// Purchase basis toggle and the single- vs cross-store basket are instant.
// Eligibility mirrors the server gate: valid_ingredient !== false and the row
// carries a used_price (exact unit match or ≈ approximate scaling).
export default {
  name: 'SummaryPanel',
  props: {
    result: { type: Object, default: null },
    companies: { type: Array, required: true },
    terms: { type: Array, default: () => [] }, // requested ingredient order
  },
  setup(props, { expose }) {
    const expandedStores = ref(new Set());

    const num = (v) => (v === '' || v === null || v === undefined || Number.isNaN(Number(v)) ? null : Number(v));
    const basisPrice = (r, basis) => (basis === 'purchase' ? num(r.purchase_price) : num(r.used_price));
    function eligible(r, basis) {
      return r.valid_ingredient !== false && basisPrice(r, basis) !== null;
    }

    const orderedTerms = computed(() => {
      const seen = new Set();
      const out = [];
      for (const t of props.terms) { const k = String(t || '').trim(); if (k && !seen.has(k)) { seen.add(k); out.push(k); } }
      for (const r of props.result?.rows || []) { const k = String(r.search_ingredient || '').trim(); if (k && !seen.has(k)) { seen.add(k); out.push(k); } }
      return out;
    });

    const basisLabel = computed(() => (settings.summaryBasis === 'purchase' ? 'Ranked by purchase cost' : 'Ranked by used cost'));
    const altLabel = computed(() => (settings.summaryBasis === 'purchase' ? 'Used cost' : 'Purchase cost'));

    // Rows grouped store -> term -> [rows] once; both modes read from it.
    const grouped = computed(() => {
      const map = new Map();
      for (const r of props.result?.rows || []) {
        const key = `${r.company}|${r.store}`;
        let store = map.get(key);
        if (!store) { store = { key, company: r.company, store: r.store, byTerm: new Map() }; map.set(key, store); }
        const term = String(r.search_ingredient || '');
        let list = store.byTerm.get(term);
        if (!list) { list = []; store.byTerm.set(term, list); }
        list.push(r);
      }
      return map;
    });

    const serverStores = computed(() => props.result?.store_costs || []);

    function pickBest(rows, basis) {
      let best = null;
      for (const r of rows) {
        if (!eligible(r, basis)) continue;
        const price = basisPrice(r, basis);
        const unitPenalty = r.units_match === true ? 0 : 1;
        if (!best || price < best.price || (price === best.price && unitPenalty < best.unitPenalty)) best = { row: r, price, unitPenalty };
      }
      return best?.row || null;
    }

    function pickDisplay(row) {
      if (!row) return { recipe: '-', title: '-', brand: '-', pack: '-', usedDisplay: '-', purchDisplay: '-', purchQty: 0, statusLabel: 'unavailable' };
      const main = [row.ingredient_quantity, row.ingredient_measurement].filter((v) => v !== '' && v !== null && v !== undefined).join(' ');
      const approx = [row.ingredient_approx_quantity, row.ingredient_approx_unit].filter((v) => v !== '' && v !== null && v !== undefined && v !== 0).join(' ');
      const money = (v) => (num(v) === null ? '-' : `$${Number(v).toFixed(2)}`);
      return {
        recipe: main + ([row.ingredient_approx_quantity, row.ingredient_approx_unit].some((v) => v) ? ` (~${approx})` : '') || '-',
        title: row.returned_ingredient || '-',
        brand: row.brand || '-',
        pack: [row.quantity, row.measurement_unit].filter((v) => v !== '' && v !== null && v !== undefined).join(' ') || '-',
        usedDisplay: row.status === 'approximate' ? `~${money(row.used_price)}` : money(row.used_price),
        purchDisplay: money(row.purchase_price),
        purchQty: `${row.purchase_quantity || 0} pack(s)`,
        statusLabel: (row.status || 'ok').replace(/_/g, ' ') + (row.status === 'approximate' ? ' (≈)' : ''),
      };
    }

    // Derived unavailability detail for a term whose every row was rejected.
    function unavailableDetail(rows) {
      const filtered = rows.filter((r) => r.valid_ingredient === false).length;
      if (filtered && filtered === rows.length) return 'filtered';
      return 'unit-incompatible';
    }

    const rankedStores = computed(() => {
      const basis = settings.summaryBasis;
      const alt = basis === 'purchase' ? 'used' : 'purchase';
      const terms = orderedTerms.value;
      const candidates = new Map();
      for (const s of serverStores.value) candidates.set(`${s.company}|${s.store}`, { company: s.company, store: s.store, server: s });
      for (const g of grouped.value.values()) if (!candidates.has(g.key)) candidates.set(g.key, { company: g.company, store: g.store, server: null });

      const out = [];
      for (const { company, store, server } of candidates.values()) {
        const g = grouped.value.get(`${company}|${store}`);
        const byTerm = g?.byTerm || new Map();
        const picks = [];
        let total = 0;
        let altTotal = 0;
        let matched = 0;
        const derivedIssues = [];
        for (const term of terms) {
          const rows = byTerm.get(term) || [];
          const chosen = pickBest(rows, basis);
          const altChosen = pickBest(rows, alt);
          if (chosen) {
            matched += 1;
            total += basisPrice(chosen, basis);
            const d = pickDisplay(chosen);
            picks.push({ term, missing: false, ...d });
          } else {
            picks.push({ term, missing: true, ...pickDisplay(null), statusLabel: rows.length ? `unavailable (${unavailableDetail(rows)})` : 'not found' });
            if (rows.length) derivedIssues.push({ term, detail: unavailableDetail(rows) });
          }
          if (altChosen) altTotal += basisPrice(altChosen, alt);
        }
        const serverIssues = (server?.issues || []).filter((i) => !derivedIssues.some((d) => d.term === i.search_ingredient))
          .map((i) => ({ term: i.search_ingredient, detail: (i.status || '').replace(/_/g, ' ') }));
        out.push({
          key: `${company}|${store}`, company, store,
          total, altTotal, matched, totalTerms: terms.length,
          complete: terms.length > 0 && matched === terms.length,
          picks, allIssues: [...serverIssues, ...derivedIssues],
        });
      }
      // Complete baskets first (a partial basket can't win on its gaps), then cheapest.
      return out.sort((a, b) => ((a.complete === b.complete) ? a.total - b.total : a.complete ? -1 : 1));
    });

    // #1 auto-expands; re-collapse when the ranking itself changes shape.
    watch([rankedStores, () => settings.summaryBasis, () => settings.basketMode], () => {
      const top = rankedStores.value[0];
      expandedStores.value = top ? new Set([top.key]) : new Set();
    }, { immediate: true });

    const basket = computed(() => {
      const basis = settings.summaryBasis;
      const terms = orderedTerms.value;
      const all = props.result?.rows || [];
      const items = [];
      const missing = [];
      const contributions = new Map();
      let total = 0;
      for (const term of terms) {
        const pool = all.filter((r) => String(r.search_ingredient || '') === term);
        const chosen = pickBest(pool, basis);
        if (!chosen) { if (pool.length) missing.push(`${term} (${unavailableDetail(pool)})`); else missing.push(term); continue; }
        total += basisPrice(chosen, basis);
        const cKey = `${chosen.company}|${chosen.store}`;
        const c = contributions.get(cKey) || { company: chosen.company, store: chosen.store, count: 0 };
        c.count += 1;
        contributions.set(cKey, c);
        items.push({ term, company: chosen.company, store: chosen.store, title: chosen.returned_ingredient || '-', ...pickDisplay(chosen) });
      }
      const contribList = [...contributions.values()].sort((a, b) => b.count - a.count);
      return {
        items, missing, total, totalTerms: terms.length,
        coverage: terms.length - missing.length,
        contributionLine: contribList.map((c) => `${c.store} ×${c.count}`).join(' · '),
      };
    });

    function toggleStore(key) {
      const next = new Set(expandedStores.value);
      next.has(key) ? next.delete(key) : next.add(key);
      expandedStores.value = next;
    }
    function focusStore(pin) {
      const key = `${pin.company}-${pin.store}`;
      settings.basketMode = 'single';
      if (!expandedStores.value.has(key)) toggleStore(key);
    }

    function companyLabel(company) { return props.companies.find((item) => item.id === company)?.label || company; }
    function badgeClass(company) { return `badge-${String(company).toLowerCase()}`; }
    function money(value) { return value === null || value === undefined || Number.isNaN(Number(value)) ? '-' : `$${Number(value).toFixed(2)}`; }

    expose({ focusStore });

    return {
      settings, rankedStores, basket, basisLabel, altLabel, expandedStores,
      toggleStore, focusStore, companyLabel, badgeClass, money,
    };
  },
};
</script>
