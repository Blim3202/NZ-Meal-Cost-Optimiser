<template>
  <div class="row-filters">
    <button type="button" class="filter-toggle" :class="{ 'is-open': open }" :title="`${count} product filter keyword${count === 1 ? '' : 's'} active`" @click="open = !open">
      <span class="twisty">{{ open ? '▾' : '▸' }}</span> Product filters
      <span v-if="count" class="chip-mini">{{ count }}</span>
    </button>
    <div v-if="open" class="filter-editor">
      <div class="filter-group">
        <span class="fg-label">Include Term</span>
        <span v-for="(word, i) in current.includes" :key="`inc-${i}`" class="kw-chip kw-include">{{ word }}<button type="button" class="kw-x" :title="`Remove '${word}'`" @click="drop('includes', i)">✕</button></span>
        <form class="kw-form" @submit.prevent="push('includes')">
          <div class="kw-input-wrap" :class="{ 'is-filled': !!draftInc, 'is-duplicate': incDuplicate }">
            <span class="kw-input-icon" aria-hidden="true">+</span>
            <input
              v-model="draftInc"
              class="kw-add"
              type="search"
              autocomplete="off"
              autocorrect="off"
              autocapitalize="off"
              spellcheck="false"
              enterkeyhint="done"
              placeholder="add term"
              :aria-label="`Add include term for ${term}`"
              @keydown.enter.prevent="push('includes')"
              @keyup.enter="push('includes')"
            >
            <button v-if="draftInc.trim()" type="submit" class="kw-add-btn" :title="`Add '${draftInc.trim()}'`" aria-label="Add include term">+</button>
          </div>
        </form>
      </div>
      <div class="filter-group">
        <span class="fg-label">Exclude Term</span>
        <span v-for="(word, i) in current.excludes" :key="`exc-${i}`" class="kw-chip kw-exclude">{{ word }}<button type="button" class="kw-x" :title="`Remove '${word}'`" @click="drop('excludes', i)">✕</button></span>
        <form class="kw-form" @submit.prevent="push('excludes')">
          <div class="kw-input-wrap" :class="{ 'is-filled': !!draftExc, 'is-duplicate': excDuplicate }">
            <span class="kw-input-icon" aria-hidden="true">+</span>
            <input
              v-model="draftExc"
              class="kw-add"
              type="search"
              autocomplete="off"
              autocorrect="off"
              autocapitalize="off"
              spellcheck="false"
              enterkeyhint="done"
              placeholder="add term"
              :aria-label="`Add exclude term for ${term}`"
              @keydown.enter.prevent="push('excludes')"
              @keyup.enter="push('excludes')"
            >
            <button v-if="draftExc.trim()" type="submit" class="kw-add-btn" :title="`Add '${draftExc.trim()}'`" aria-label="Add exclude term">+</button>
          </div>
        </form>
      </div>
      <p class="fg-hint">Every include term must appear in the product name (fuzzy singular/plural, e.g. carrot matches carrots) and no exclude term may appear. Brand filters in the Optimiser tuner are checked first and override these name filters when set. Filtered products remain visible but are excluded from store costs.</p>
    </div>
  </div>
</template>

<script>
import { computed, ref } from 'vue';

const MAX_KW = 15;
const MAX_LEN = 40;
const EMPTY = () => ({ includes: [], excludes: [] });

function normalize(list) {
  return list.map((w) => String(w).trim().toLowerCase());
}

// Per-ingredient include/exclude keyword editor. Keywords live OUTSIDE the
// ingredient rows — the parent owns a per-scope map keyed by search term so
// preset previews stay editable and edits survive mode switches.
export default {
  name: 'FilterEditor',
  props: {
    term: { type: String, required: true },
    rowId: { type: String, required: true },
    filters: { type: Object, default: () => ({}) },
  },
  emits: ['update-filters'],
  setup(props, { emit }) {
    const open = ref(false);
    const draftInc = ref('');
    const draftExc = ref('');

    const current = computed(() => props.filters[props.term] || EMPTY());
    const count = computed(() => (current.value.includes?.length || 0) + (current.value.excludes?.length || 0));

    const incDuplicate = computed(() => {
      const w = draftInc.value.trim().toLowerCase();
      return !!w && (normalize(current.value.includes).includes(w) || normalize(current.value.excludes).includes(w));
    });
    const excDuplicate = computed(() => {
      const w = draftExc.value.trim().toLowerCase();
      return !!w && (normalize(current.value.excludes).includes(w) || normalize(current.value.includes).includes(w));
    });

    function emitNext(kind, list) {
      const next = { ...current.value, [kind]: list };
      emit('update-filters', props.term, next);
    }
    function push(kind) {
      const draft = kind === 'includes' ? draftInc : draftExc;
      const word = String(draft.value || '').trim().slice(0, MAX_LEN);
      if (!word) { draft.value = ''; return; }
      const lower = word.toLowerCase();
      const opposite = kind === 'includes' ? 'excludes' : 'includes';
      if (normalize(current.value[kind] || []).includes(lower) || normalize(current.value[opposite] || []).includes(lower)) { draft.value = ''; return; }
      if ((current.value[kind] || []).length >= MAX_KW) { draft.value = ''; return; }
      emitNext(kind, [...(current.value[kind] || []), word]);
      draft.value = '';
    }
    function drop(kind, index) {
      emitNext(kind, (current.value[kind] || []).filter((_, i) => i !== index));
    }

    return { open, draftInc, draftExc, current, count, incDuplicate, excDuplicate, push, drop };
  },
};
</script>
