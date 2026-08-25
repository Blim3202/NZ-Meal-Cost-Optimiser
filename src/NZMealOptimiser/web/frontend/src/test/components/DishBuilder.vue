<template>
  <div class="dish-builder">
    <template v-if="mode === 'locked'">
      <p v-if="!ingredients.length" class="empty-state">Choose a dish to preview its ingredient searches.</p>
      <ul v-else class="ingredient-list">
        <li v-for="(ing, index) in ingredients" :key="index"><span class="ing-name">{{ ing.search_term }}</span><span class="ing-qty">{{ displayQty(ing) }}</span><FilterEditor v-if="termOf(ing)" :term="termOf(ing)" :row-id="`lock-${index}`" :filters="filters" @update-filters="forward" /></li>
      </ul>
    </template>
    <template v-else>
      <p v-if="!ingredients.length" class="empty-state">No ingredients yet — add the first search below.</p>
      <ul v-else class="builder-list">
        <li v-for="(ing, index) in ingredients" :key="ing.id" class="builder-item" :class="{ 'row-dup': isDuplicate(ing), 'row-blank': isBlank(ing) }">
          <div class="builder-main">
            <input class="bi-term" :value="ing.search_term" placeholder="Search term — e.g. beef mince" @input="patch(index, { search_term: $event.target.value })">
            <input class="bi-qty" type="number" min="0" step="any" :value="ing.quantity" @input="patch(index, { quantity: $event.target.value })">
            <select class="bi-unit" :value="unitValue(ing)" @change="patch(index, { unit: $event.target.value })">
              <option v-if="!isKnownUnit(ing.unit)" :value="normaliseUnit(ing.unit) || ''">{{ normaliseUnit(ing.unit) || 'unit?' }}</option>
              <optgroup v-for="g in UNIT_GROUPS" :key="g.group" :label="g.group">
                <option v-for="u in g.units" :key="u" :value="u">{{ u }}</option>
              </optgroup>
            </select>
            <button type="button" class="bi-del" title="Remove ingredient" @click="$emit('remove', index)">✕</button>
          </div>
          <div v-if="needsApprox(ing)" class="builder-approx">
            <span class="approx-label">≈ pack equivalent</span>
            <input class="bi-approx-qty" type="number" min="0" step="any" placeholder="e.g. 400" :value="ing.approx_quantity" @input="patch(index, { approx_quantity: $event.target.value })">
            <select class="bi-approx-unit" :value="ing.approx_unit || ''" @change="patch(index, { approx_unit: $event.target.value })">
              <option value="" disabled>unit</option>
              <option v-for="u in APPROX_UNITS" :key="u" :value="u">{{ u }}</option>
            </select>
            <span v-if="!hasApprox(ing)" class="warn-hint">add for accurate scaling</span>
            <span v-else class="ok-hint" title="Approx fallback set">✓</span>
          </div>
          <FilterEditor v-if="termOf(ing)" :term="termOf(ing)" :row-id="ing.id" :filters="filters" @update-filters="forward" />
          <p v-if="isDuplicate(ing)" class="row-error">Duplicate search term — merge or rename one of these rows.</p>
        </li>
      </ul>
      <div class="builder-footer">
        <button type="button" class="ghost-button add-row" @click="$emit('add')">+ Add ingredient</button>
        <span class="chip scaling-note" :class="{ 'scaling-active': scaleFactor !== 1 }">
          <template v-if="scaleFactor !== 1">Scales ×{{ trimFactor }} → {{ requestedPortions }} portions</template>
          <template v-else>Base recipe · {{ basePortions }} portion{{ basePortions === 1 ? '' : 's' }}</template>
        </span>
      </div>
    </template>
  </div>
</template>

<script>
import { computed } from 'vue';
import { APPROX_UNITS, UNIT_GROUPS, isScalableUnit, normaliseUnit } from '../unitOptions.js';
import FilterEditor from './FilterEditor.vue';

const KNOWN_UNITS = new Set(UNIT_GROUPS.flatMap((g) => g.units));

export default {
  name: 'DishBuilder',
  components: { FilterEditor },
  props: {
    mode: { type: String, default: 'locked' }, // locked (read-only preview) | edit
    ingredients: { type: Array, required: true },
    duplicateTerms: { type: Set, default: () => new Set() },
    basePortions: { type: Number, default: 4 },
    requestedPortions: { type: Number, default: 4 },
    filters: { type: Object, default: () => ({}) }, // search_term -> {includes, excludes}
  },
  emits: ['add', 'remove', 'patch', 'update-filters'],
  setup(props, { emit }) {
    const scaleFactor = computed(() => (props.basePortions > 0 ? props.requestedPortions / props.basePortions : 1));
    const trimFactor = computed(() => {
      const f = scaleFactor.value;
      return Number.isInteger(f) ? String(f) : String(Math.round(f * 100) / 100);
    });

    function patch(index, changes) { emit('patch', index, changes); }
    function needsApprox(ing) { return !isScalableUnit(ing.unit); }
    function hasApprox(ing) { return Number(ing.approx_quantity) > 0 && !!normaliseUnit(ing.approx_unit); }
    function isDuplicate(ing) { return !!String(ing.search_term).trim() && props.duplicateTerms.has(String(ing.search_term).trim().toLowerCase()); }
    function isBlank(ing) { return !String(ing.search_term).trim(); }
    function isKnownUnit(unit) { return KNOWN_UNITS.has(normaliseUnit(unit)); }
    function unitValue(ing) { return normaliseUnit(ing.unit); }
    function termOf(ing) { return String(ing.search_term || '').trim(); }
    function forward(term, next) { emit('update-filters', term, next); }
    function displayQty(ing) {
      const qty = ing.quantity === null || ing.quantity === undefined ? '' : `${ing.quantity} `;
      const approx = ing.approx_quantity ? ` · ~${ing.approx_quantity} ${ing.approx_unit}` : '';
      return `${qty}${ing.unit}${approx}`;
    }

    return { APPROX_UNITS, UNIT_GROUPS, scaleFactor, trimFactor, patch, needsApprox, hasApprox, isDuplicate, isBlank, isKnownUnit, unitValue, termOf, forward, displayQty };
  },
};
</script>
