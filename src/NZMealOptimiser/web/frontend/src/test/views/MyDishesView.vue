<template>
  <main class="shell">
    <header class="hero">
      <div><p class="eyebrow">Recipe library</p><h1>My Dishes</h1><p class="lede">Every stored recipe — hand-curated presets plus ones you saved from the builder. Edit any of them right here.</p></div>
      <span class="chip">{{ dishes.length }} dish{{ dishes.length === 1 ? '' : 'es' }}</span>
    </header>

    <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
    <p v-else-if="loading" class="empty-state panel">Loading recipes…</p>
    <p v-else-if="!dishes.length" class="empty-state panel">No dishes stored yet — build one on the dashboard or import one on the LLM Recipe Builder page and hit "Save as preset".</p>

    <div v-else class="dish-grid">
      <article v-for="dish in dishes" :key="dish.key" class="panel dish-card" :class="{ editing: dish.key === editingKey }">
        <!-- ── Collapsed card ─────────────────────────────────────────────── -->
        <template v-if="dish.key !== editingKey">
          <div class="section-heading">
            <div><h3>{{ dish.label }}</h3><small class="muted-meta">{{ dish.ingredients.length }} ingredient searches · base {{ dish.portion }} portions</small></div>
            <span class="badge" :class="dish.source === 'user' ? 'badge-user' : 'badge-curated'" :title="dish.source === 'user' ? 'Saved by you from the dish builder' : 'Hand-curated preset shipped with the project'">{{ dish.source === 'user' ? 'User' : 'Curated' }}</span>
          </div>
          <div v-if="dish.notes" class="notes-wrap">
            <p class="dish-notes" :class="{ open: expanded.has(dish.key) }">{{ dish.notes }}</p>
            <button v-if="dish.notes.length > NOTES_CLAMP" type="button" class="link-button" @click="toggleNotes(dish.key)">{{ expanded.has(dish.key) ? 'See less ▴' : 'See more ▾' }}</button>
          </div>
          <ul class="ingredient-list">
            <li v-for="(ing, index) in dish.ingredients.slice(0, 6)" :key="index"><span class="ing-name">{{ ing.search_term }}</span><span class="ing-qty">{{ ing.quantity }} {{ ing.unit }}</span></li>
          </ul>
          <p v-if="dish.ingredients.length > 6" class="hint">+ {{ dish.ingredients.length - 6 }} more…</p>
          <div class="form-actions dish-actions">
            <button type="button" class="ghost-button ghost-small" @click="$emit('open-dish', { key: dish.key, edit: false })">Open</button>
            <button type="button" class="ghost-button ghost-small" title="Edit this recipe right here — the card expands into a full editor" @click="startEdit(dish)">Edit ✎</button>
            <button type="button" class="ghost-button ghost-small danger-button" :disabled="deleting === dish.key" @click="removeDish(dish)">{{ deleting === dish.key ? 'Deleting…' : 'Delete 🗑' }}</button>
          </div>
        </template>

        <!-- ── Expanded inline editor ─────────────────────────────────────── -->
        <template v-else>
          <div class="section-heading">
            <div><p class="eyebrow">Editing recipe</p><h3>{{ draft.name || dish.label }}</h3><small class="muted-meta">{{ editDirtyLabel }}</small></div>
            <span class="badge" :class="dish.source === 'user' ? 'badge-user' : 'badge-curated'">{{ dish.source === 'user' ? 'User' : 'Curated' }}</span>
          </div>

          <div class="form-grid edit-fields">
            <label class="field field-name"><span>Dish name</span><input v-model.trim.lazy="draft.name" maxlength="80" placeholder="e.g. spaghetti bolognese"></label>
            <label class="field field-base"><span>Base portions</span><input v-model.number="draft.basePortions" type="number" min="1" max="24"></label>
            <label class="field field-wide"><span>Notes (optional)</span><input v-model.trim="draft.notes" maxlength="100" placeholder="Chocolate chip cookies — bbcgoodfood.com"></label>
          </div>

          <DishBuilder mode="edit" :ingredients="draft.rows" :duplicate-terms="duplicateTerms" :base-portions="Number(draft.basePortions) || 4" :requested-portions="Number(draft.basePortions) || 4" :filter-counts="ruleCounts" @add="addRow" @remove="removeRow" @patch="patchRow" @open-filters="focusTerm" />

          <div v-if="editorTerms.length" class="term-filters">
            <p class="hint rules-hint">Product-filter keywords are saved instantly to your browser and shared with the dashboard tuner — Save commits only the recipe itself (name, portions, ingredients, notes).</p>
            <div v-for="term in editorTerms" :key="term" :ref="(el) => setTermRef(term, el)" class="term-filter-block" :class="{ 'term-focus': term === focusedTerm }">
              <p class="term-name">{{ term }}</p>
              <FilterEditor :term="term" :row-id="`${dish.key}:${term}`" :filters="draft.rules" @update-filters="onRuleUpdate" />
            </div>
          </div>

          <p v-if="editError" class="error-banner" role="alert">{{ editError }}</p>
          <div class="form-actions dish-actions">
            <button type="button" class="primary-button is-ready" :disabled="saving || !canSaveEdit" :title="canSaveEdit ? 'Store these changes in data/dishes.json' : saveBlockReason" @click="saveEdit">{{ saving ? 'Saving…' : 'Save changes' }}</button>
            <button type="button" class="ghost-button ghost-small" :disabled="saving" @click="cancelEdit">{{ dirty ? 'Cancel ✕' : 'Close' }}</button>
            <span class="hint">{{ saveHint }}</span>
          </div>
        </template>
      </article>
    </div>
  </main>
</template>

<script>
import { computed, nextTick, onMounted, reactive, ref } from 'vue';
import DishBuilder from '../components/DishBuilder.vue';
import FilterEditor from '../components/FilterEditor.vue';
import { normaliseUnit } from '../unitOptions.js';
import { scopeOf, writeScope, seenScopes, markSeen, moveScope } from '../filterStore.js';

let rowSeq = 0;
const NOTES_CLAMP = 64; // ~2 clamped lines in a card; longer notes get a toggle
const emptyRow = () => ({ id: `row-${++rowSeq}`, search_term: '', quantity: '', unit: 'g', approx_quantity: '', approx_unit: '' });

const cloneRules = (rules) => Object.fromEntries(Object.entries(rules || {})
  .map(([term, f]) => [term, {
    includes: [...(f.includes || [])],
    excludes: [...(f.excludes || [])],
    brand_includes: [...(f.brand_includes || [])],
    brand_excludes: [...(f.brand_excludes || [])],
  }]));

export default {
  name: 'MyDishesView',
  components: { DishBuilder, FilterEditor },
  emits: ['open-dish'],
  setup() {
    const raw = ref({});
    const loading = ref(true);
    const error = ref('');
    const deleting = ref('');
    const expanded = reactive(new Set());
    const curatedFilters = ref({}); // /dish_filters baseline for first-open seeding

    const dishes = computed(() => Object.entries(raw.value).map(([key, dish]) => ({
      key,
      label: dish.dish_name || key,
      portion: dish.portion || 4,
      ingredients: Array.isArray(dish.ingredients) ? dish.ingredients : [],
      source: dish.source || 'curated',
      notes: String(dish.notes || ''),
    })));

    // ── Inline editor state (one expanded card at a time) ──────────────────
    const editingKey = ref('');
    const saving = ref(false);
    const editError = ref('');
    const draft = reactive({ name: '', basePortions: 4, notes: '', rows: [], rules: {} });
    const termRefs = new Map();
    const focusedTerm = ref('');

    const duplicateTerms = computed(() => {
      const counts = new Map();
      for (const row of draft.rows) {
        const term = String(row.search_term || '').trim().toLowerCase();
        if (term) counts.set(term, (counts.get(term) || 0) + 1);
      }
      return new Set([...counts.entries()].filter(([, n]) => n > 1).map(([term]) => term));
    });
    const validRows = computed(() => draft.rows
      .map((row) => ({
        search_term: String(row.search_term || '').trim(),
        quantity: Number(row.quantity),
        unit: normaliseUnit(row.unit),
        approx_quantity: Number(row.approx_quantity) > 0 ? Number(row.approx_quantity) : null,
        approx_unit: Number(row.approx_quantity) > 0 ? normaliseUnit(row.approx_unit || '') : null,
      }))
      .filter((row) => row.search_term && row.quantity > 0));
    const editorTerms = computed(() => [...new Set(validRows.value.map((row) => row.search_term))]);
    const ruleCounts = computed(() => Object.fromEntries(Object.entries(draft.rules)
      .map(([term, f]) => [term, (f.includes?.length || 0) + (f.excludes?.length || 0)])
      .filter(([, n]) => n > 0)));

    // Dirty tracks only what Save commits — rule edits persist instantly.
    const draftSig = () => JSON.stringify({
      name: String(draft.name || '').trim().toLowerCase(),
      basePortions: Number(draft.basePortions) || 4,
      notes: String(draft.notes || '').trim(),
      rows: validRows.value,
    });
    let originalSig = '';
    const dirty = computed(() => !!editingKey.value && draftSig() !== originalSig);
    const canSaveEdit = computed(() => !!String(draft.name || '').trim() && validRows.value.length > 0 && !duplicateTerms.value.size && dirty.value);
    const saveBlockReason = computed(() => {
      if (!String(draft.name || '').trim()) return 'Give the dish a name first';
      if (!validRows.value.length) return 'At least one complete ingredient row is needed';
      if (duplicateTerms.value.size) return 'Merge the highlighted duplicate search terms first';
      if (!dirty.value) return 'Nothing changed yet';
      return '';
    });
    const editDirtyLabel = computed(() => (dirty.value ? 'unsaved changes' : `${validRows.value.length} ingredient searches · base ${Number(draft.basePortions) || 4} portions`));
    const saveHint = computed(() => (dirty.value ? 'Save commits the recipe itself — renaming also moves the preset and its product-filter rules.' : 'Product-filter chips above are saved instantly — nothing else changed.'));

    function addRow() { draft.rows.push(emptyRow()); }
    function removeRow(index) { draft.rows.splice(index, 1); }
    function patchRow(index, changes) { Object.assign(draft.rows[index], changes); }

    function setTermRef(term, el) {
      if (el) termRefs.set(term, el);
      else termRefs.delete(term);
    }

    // Deep-link from a builder row's rule-count chip → its keyword editor.
    function focusTerm(term) {
      focusedTerm.value = term;
      nextTick(() => termRefs.get(term)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
      setTimeout(() => { if (focusedTerm.value === term) focusedTerm.value = ''; }, 1800);
    }

    // First open of a curated dish seeds its scope once from /dish_filters —
    // exactly the dashboard's seedIfUnseen contract, so deleting keywords
    // never resurrects the baseline on either page.
    function startEdit(dish) {
      if (editingKey.value && !confirmLeave()) return;
      editingKey.value = dish.key;
      editError.value = '';
      focusedTerm.value = '';
      draft.name = dish.label;
      draft.basePortions = Number(dish.portion) || 4;
      draft.notes = String(dish.notes || '');
      draft.rows = dish.ingredients.map((ing) => ({
        id: `row-${++rowSeq}`,
        search_term: ing.search_term || '',
        quantity: ing.quantity ?? '',
        unit: normaliseUnit(ing.unit) || 'g',
        approx_quantity: ing.approx_quantity ?? '',
        approx_unit: normaliseUnit(ing.approx_unit || ''),
      }));
      const scope = `preset:${dish.key}`;
      if (!seenScopes().has(scope)) {
        markSeen(scope);
        const curated = curatedFilters.value[dish.key];
        if (curated) writeScope(scope, cloneRules(curated));
      }
      draft.rules = cloneRules(scopeOf(scope));
      originalSig = draftSig(); // snapshot AFTER seeding — rules aren't tracked anyway
    }

    function confirmLeave() {
      return !dirty.value || window.confirm('Discard unsaved changes to this recipe?');
    }

    function cancelEdit() {
      if (!confirmLeave()) return;
      editingKey.value = '';
    }

    // Keyword add/remove writes straight through to the shared store so the
    // dashboard tuner sees the same rules without pressing Save.
    function onRuleUpdate(term, next) {
      const clean = {
        includes: (next.includes || []).filter(Boolean),
        excludes: (next.excludes || []).filter(Boolean),
        brand_includes: (next.brand_includes || []).filter(Boolean),
        brand_excludes: (next.brand_excludes || []).filter(Boolean),
      };
      const scope = { ...(scopeOf(`preset:${editingKey.value}`)) };
      const empty = !clean.includes.length && !clean.excludes.length
        && !clean.brand_includes.length && !clean.brand_excludes.length;
      if (empty) delete scope[term];
      else scope[term] = clean;
      writeScope(`preset:${editingKey.value}`, scope);
      draft.rules = cloneRules(scope);
    }

    async function saveEdit() {
      if (!canSaveEdit.value || saving.value) return;
      const name = String(draft.name).trim();
      const newKey = name.toLowerCase();
      const oldKey = editingKey.value;
      if (newKey !== oldKey && dishes.value.some((d) => d.key === newKey)
        && !window.confirm(`"${name}" already exists as a preset.\nOverwrite it?`)) return;
      saving.value = true;
      editError.value = '';
      try {
        const response = await fetch('/dishes/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            dish_name: name,
            base_portions: Number(draft.basePortions) || 4,
            ingredients: validRows.value.map((row) => (row.approx_quantity === null
              ? { search_term: row.search_term, quantity: row.quantity, unit: row.unit }
              : { ...row })),
            notes: String(draft.notes || '').trim().slice(0, 100),
          }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Could not save the recipe');
        if (newKey !== oldKey) {
          // Clean rename: drop the old entry, carry its filter rules across.
          const del = await fetch(`/dishes/${encodeURIComponent(oldKey)}`, { method: 'DELETE' });
          if (!del.ok && del.status !== 404) throw new Error((await del.json()).detail || 'Recipe saved, but removing the old name failed');
          moveScope(`preset:${oldKey}`, `preset:${newKey}`);
        }
        await fetchDishes();
        editingKey.value = '';
      } catch (err) {
        editError.value = err.message;
      } finally {
        saving.value = false;
      }
    }

    function toggleNotes(key) {
      if (expanded.has(key)) expanded.delete(key);
      else expanded.add(key);
    }

    async function fetchDishes() {
      const response = await fetch('/dishes');
      if (!response.ok) throw new Error('Could not load dishes');
      raw.value = await response.json();
    }

    async function fetchCuratedFilters() {
      try {
        const response = await fetch('/dish_filters');
        if (response.ok) curatedFilters.value = await response.json();
      } catch { /* presets are optional sugar — inline editing still works */ }
    }

    async function removeDish(dish) {
      const curatedWarning = dish.source !== 'user'
        ? `\n\n"${dish.label}" is a hand-curated preset shipped with the project — deleting it removes it from data/dishes.json for everyone (recoverable via git).`
        : '';
      const editingWarning = dish.key === editingKey.value
        ? '\n\nThis recipe is open in the editor — deleting discards your changes too.'
        : '';
      if (!window.confirm(`Delete "${dish.label}"?${curatedWarning}${editingWarning}`)) return;
      deleting.value = dish.key;
      try {
        const response = await fetch(`/dishes/${encodeURIComponent(dish.key)}`, { method: 'DELETE' });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Could not delete the dish');
        if (editingKey.value === dish.key) editingKey.value = '';
        delete raw.value[dish.key];
        raw.value = { ...raw.value };
      } catch (err) {
        error.value = err.message;
      } finally {
        deleting.value = '';
      }
    }

    onMounted(async () => {
      loading.value = true;
      error.value = '';
      try {
        await Promise.all([fetchDishes(), fetchCuratedFilters()]);
      } catch (err) {
        error.value = err.message;
      } finally {
        loading.value = false;
      }
    });

    return {
      dishes, loading, error, deleting, removeDish, expanded, toggleNotes, NOTES_CLAMP,
      editingKey, saving, editError, draft, dirty, canSaveEdit, saveBlockReason,
      editDirtyLabel, saveHint, duplicateTerms, editorTerms, ruleCounts,
      addRow, removeRow, patchRow, focusTerm, focusedTerm, setTermRef,
      startEdit, cancelEdit, onRuleUpdate, saveEdit,
    };
  },
};
</script>
