<template>
  <div class="row-filters">
    <button type="button" class="filter-toggle" :class="{ 'is-open': open }" :title="`${count} product filter keyword${count === 1 ? '' : 's'} active`" @click="open = !open">
      <span class="twisty">{{ open ? '▾' : '▸' }}</span> Product filters
      <span v-if="count" class="chip-mini">{{ count }}</span>
    </button>
    <div v-if="open" class="filter-editor">
      <div class="filter-group">
        <span class="fg-label">Must include</span>
        <span v-for="(word, i) in current.includes" :key="`inc-${i}`" class="kw-chip kw-include">{{ word }}<button type="button" class="kw-x" :title="`Remove '${word}'`" @click="drop('includes', i)">✕</button></span>
        <input v-model="draftInc" class="kw-add" placeholder="add keyword ↵" @keydown.enter.prevent="push('includes')">
      </div>
      <div class="filter-group">
        <span class="fg-label">Must exclude</span>
        <span v-for="(word, i) in current.excludes" :key="`exc-${i}`" class="kw-chip kw-exclude">{{ word }}<button type="button" class="kw-x" :title="`Remove '${word}'`" @click="drop('excludes', i)">✕</button></span>
        <input v-model="draftExc" class="kw-add" placeholder="add keyword ↵" @keydown.enter.prevent="push('excludes')">
      </div>
      <p class="fg-hint">Include: at least one keyword must appear in the product name (fuzzy singular/plural match). Exclude: none may appear. Filtered-out products are skipped by the store costs.</p>
    </div>
  </div>
</template>

<script>
import { computed, ref } from 'vue';

const EMPTY = () => ({ includes: [], excludes: [] });

// Per-ingredient include/exclude keyword editor. Keywords live OUTSIDE the
// ingredient rows — the parent owns a per-scope map keyed by search term so
// preset previews stay editable and edits survive mode switches.
export default {
  name: 'FilterEditor',
  props: {
    term: { type: String, required: true }, // search term this editor keys on
    rowId: { type: String, required: true }, // stable per-row key for draft inputs
    filters: { type: Object, default: () => ({}) }, // term -> {includes, excludes}
  },
  emits: ['update-filters'],
  setup(props, { emit }) {
    const open = ref(false);
    const draftInc = ref('');
    const draftExc = ref('');

    const current = computed(() => props.filters[props.term] || EMPTY());
    const count = computed(() => current.value.includes.length + current.value.excludes.length);

    function emitNext(kind, list) {
      const next = { includes: [...current.value.includes], excludes: [...current.value.excludes], [kind]: list };
      emit('update-filters', props.term, next);
    }
    function push(kind) {
      const draft = kind === 'includes' ? draftInc : draftExc;
      const word = String(draft.value || '').trim().slice(0, 40);
      if (!word || current.value[kind].some((w) => w.toLowerCase() === word.toLowerCase())) { draft.value = ''; return; }
      emitNext(kind, [...current.value[kind], word]);
      draft.value = '';
    }
    function drop(kind, index) {
      emitNext(kind, current.value[kind].filter((_, i) => i !== index));
    }

    return { open, draftInc, draftExc, current, count, push, drop };
  },
};
</script>
