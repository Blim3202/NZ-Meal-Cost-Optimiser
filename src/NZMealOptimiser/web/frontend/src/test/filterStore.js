// Shared browser-local store for product-filter keyword rules.
//
// All rules live in ONE localStorage blob ('meal-filters-v1') under per-dish /
// per-mode scope keys ("preset:<key>", "custom", "shopping"). A single
// module-level ref means every view importing it shares the same in-memory
// state, and the deep watch mirrors every mutation back to storage so the
// dashboard tuner and the My Dishes inline editor can never drift apart.
//
// Scope shape: { [scopeKey]: { [search_term]: {
//                  includes: [], excludes: [],
//                  brand_includes: [], brand_excludes: [] } },
//                _seen: [scopeKey, ...] }
// "_seen" records scopes already seeded from data/dish_filters.json so
// deleting keywords never resurrects curated baselines on revisit. Brand
// filters are user-set only (never seeded from the curated file or LLM).
import { ref, watch } from 'vue';

const FILTERS_LS_KEY = 'meal-filters-v1';

export const filterStore = ref(loadFilterStore());

watch(filterStore, (store) => {
  try { localStorage.setItem(FILTERS_LS_KEY, JSON.stringify(store)); } catch { /* storage full/blocked */ }
}, { deep: true });

function loadFilterStore() {
  try {
    const raw = JSON.parse(localStorage.getItem(FILTERS_LS_KEY));
    return raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {};
  } catch { return {}; }
}

export function scopeOf(key) {
  return filterStore.value[key] || {};
}

export function writeScope(key, scope) {
  filterStore.value = { ...filterStore.value, [key]: scope };
}

export function seenScopes() {
  return new Set(filterStore.value._seen || []);
}

export function markSeen(key) {
  if (seenScopes().has(key)) return;
  filterStore.value = { ...filterStore.value, _seen: [...(filterStore.value._seen || []), key] };
}

// Attach keyword rules to a named preset at save time: cleans the map (empty
// rules dropped), writes the preset:<key> scope and marks it seen so the
// dashboard's seedIfUnseen never clobbers it with a curated baseline. Used by
// the dashboard's "Save as preset" (custom-mode rules) and the LLM Recipe
// Builder's direct save (freshly generated rules — always overwrite).
export function seedPresetRules(key, rules) {
  const clean = Object.fromEntries(Object.entries(rules || {})
    .map(([term, f]) => [term, {
      includes: [...(f.includes || [])],
      excludes: [...(f.excludes || [])],
      brand_includes: [...(f.brand_includes || [])],
      brand_excludes: [...(f.brand_excludes || [])],
    }])
    .filter(([, f]) => f.includes.length || f.excludes.length || f.brand_includes.length || f.brand_excludes.length));
  writeScope(`preset:${key}`, clean);
  markSeen(`preset:${key}`);
  return Object.keys(clean).length;
}

// Rename support: carry a preset's rules over to its new key and drop the old
// one entirely (scope + seen flag) so no orphaned keywords linger.
export function moveScope(from, to) {
  const current = filterStore.value;
  if (!(from in current) && !seenScopes().has(from)) return;
  const next = Object.fromEntries(Object.entries(current).filter(([k]) => k !== from));
  next[to] = current[from] || {};
  const seen = seenScopes();
  seen.delete(from);
  seen.add(to);
  next._seen = [...seen];
  filterStore.value = next;
}
