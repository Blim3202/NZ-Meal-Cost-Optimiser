<template>
  <section class="results-area">
    <div v-if="result" class="result-heading"><div><p class="eyebrow">Comparison complete</p><h2>{{ result.dish }} <span v-if="result.dish_source === 'custom'" class="chip chip-custom">Custom recipe</span><span v-else-if="result.dish_source === 'shopping_list'" class="chip chip-shopping">Shopping list</span><span v-else-if="result.dish_source === 'curated'" class="chip">Preset</span></h2><p class="summary">{{ result.rows.length }} products across {{ result.store_costs.length }} stores · {{ result.companies_checked.join(', ') }}</p></div><time>{{ formatDate(result.timestamp) }}</time></div>

    <section class="panel results-tabs-panel">
      <div class="tabs-bar" role="tablist" aria-label="Results views">
        <button id="tab-summary" type="button" class="tab-btn" :class="{ active: activeTab === 'summary' }" role="tab" :aria-selected="activeTab === 'summary'" @click="activeTab = 'summary'">Summary</button>
        <button id="tab-tuner" type="button" class="tab-btn" :class="{ active: activeTab === 'tuner' }" role="tab" :aria-selected="activeTab === 'tuner'" @click="showTuner()">Filter tuner<span v-if="filterKeywordCount" class="chip-mini">{{ filterKeywordCount }}</span></button>
        <button id="tab-results" type="button" class="tab-btn" :class="{ active: activeTab === 'results' }" role="tab" :aria-selected="activeTab === 'results'" @click="activeTab = 'results'">All results</button>
        <span class="tabs-spacer"></span>
        <span v-if="canReapply && activeTab !== 'tuner'" class="dirty-hint" title="Product filters changed since this run">⚙ filters changed</span>
        <button v-if="canReapply" type="button" class="primary-button apply-btn" :disabled="applying" title="Recalculate ingredient validity, store costs and the winner from the cached products — no new supermarket queries" @click="$emit('apply')"><span v-if="applying" class="spinner"></span>{{ applying ? 'Applying…' : 'Apply filters' }}</button>
      </div>

      <SummaryPanel v-if="result" v-show="activeTab === 'summary'" ref="summaryPanel" :result="result" :companies="companies" :terms="terms" :job-id="jobId" :filters="filters" @update-filters="(term, next) => $emit('update-filters', term, next)" @pipeline-log="(e) => $emit('pipeline-log', e)" />
      <div v-else-if="activeTab === 'summary'" class="tab-empty">Compare prices to view this table.</div>
      <FilterTunerPanel v-if="activeTab === 'tuner'" :job-id="jobId" :active="previewActive" :ingredients="tunerIngredients" :filters="filters" :stores="result ? result.store_costs || [] : []" :companies="companies" :selected-term="tunerTerm" :dish="result?.dish || ''" @update-filters="(term, next) => $emit('update-filters', term, next)" @select-term="tunerTerm = $event" @pipeline-log="(e) => $emit('pipeline-log', e)" />
      <AllResultsPanel v-if="result" v-show="activeTab === 'results'" ref="allResults" :result="result" :companies="companies" />
      <div v-else-if="activeTab === 'results'" class="tab-empty">Compare prices to view this table.</div>
    </section>
  </section>
</template>

<script>
import { computed, ref, watch } from 'vue';
import SummaryPanel from './SummaryPanel.vue';
import FilterTunerPanel from './FilterTunerPanel.vue';
import AllResultsPanel from './AllResultsPanel.vue';

// One results card, three pages: Summary (rankings + basket), Filter tuner
// (full-space keyword editor with live preview), All results (sortable table).
// Always rendered — pre-run it shows the tuner with the builder's ingredients
// while Summary/All results carry a placeholder. A fresh result jumps to
// Summary; an "Apply filters" click keeps you on the tuner instead.
export default {
  name: 'ResultsTabs',
  components: { SummaryPanel, FilterTunerPanel, AllResultsPanel },
  props: {
    result: { type: Object, default: null },
    companies: { type: Array, required: true },
    terms: { type: Array, default: () => [] }, // requested ingredient order
    tunerIngredients: { type: Array, default: () => [] }, // [{term, qty}]
    filters: { type: Object, default: () => ({}) },
    jobId: { type: String, default: '' },
    previewActive: { type: Boolean, default: false },
    canReapply: { type: Boolean, default: false },
    applying: { type: Boolean, default: false },
  },
  emits: ['apply', 'update-filters', 'pipeline-log'],
  setup(props, { expose }) {
    const activeTab = ref('tuner');
    const tunerTerm = ref('');
    const summaryPanel = ref(null);
    const allResults = ref(null);
    let suppressJump = false;

    const filterKeywordCount = computed(() => Object.values(props.filters)
      .reduce((n, f) => n
        + (f.includes?.length || 0)
        + (f.excludes?.length || 0)
        + (f.brand_includes?.length || 0)
        + (f.brand_excludes?.length || 0), 0));

    function showTuner(term) {
      activeTab.value = 'tuner';
      if (term) tunerTerm.value = term;
      else if (!tunerTerm.value || !props.tunerIngredients.some((i) => i.term === tunerTerm.value)) {
        tunerTerm.value = props.tunerIngredients[0]?.term || '';
      }
    }
    // A new result invalidates the selected tuner ingredient. Fresh results
    // (a completed run) jump to Summary; one produced by reapply is suppressed
    // by the parent calling suppressJumpOnce() before swapping the result, so
    // keyword tuning isn't interrupted (and a failed apply arms nothing).
    watch(() => props.result, () => {
      tunerTerm.value = props.tunerIngredients[0]?.term || '';
      if (suppressJump) { suppressJump = false; return; }
      if (props.result) activeTab.value = 'summary';
    });
    watch(() => props.tunerIngredients, (list) => {
      if (!list.some((i) => i.term === tunerTerm.value)) tunerTerm.value = list[0]?.term || '';
    });

    function focusStore(pin) {
      activeTab.value = 'summary';
      summaryPanel.value?.focusStore(pin);
    }
    function openSummary() { activeTab.value = 'summary'; }
    function resetFilters() {
      allResults.value?.resetFilters();
    }

    expose({ focusStore, resetFilters, openTuner: showTuner, openSummary, suppressJumpOnce: () => { suppressJump = true; } });

    function formatDate(value) { return value ? new Date(value).toLocaleString() : ''; }
    return { activeTab, tunerTerm, summaryPanel, allResults, filterKeywordCount, showTuner, formatDate };
  },
};
</script>
