<template>
  <section class="progress-strip">
    <div class="strip-top">
      <div class="strip-phase"><p class="eyebrow">Live progress</p><strong>{{ job.status === 'idle' ? 'Awaiting request…' : (job.phase || 'Working…') }}</strong></div>
      <div v-if="job.status !== 'idle'" class="overall-bar" :class="{ indeterminate: running && !job.total_tasks }"><div class="overall-fill" :style="{ width: pct + '%' }"></div></div>
      <div v-if="job.status !== 'idle'" class="job-meta">
        <span class="chip chip-brand">⏱ {{ elapsed }}</span>
        <span class="chip">{{ job.done_tasks }}/{{ job.total_tasks }} searches</span>
        <span class="chip">{{ job.products_found }} products</span>
      </div>
    </div>
    <p v-if="job.status === 'idle'" class="strip-idle-hint">Start a comparison to track per-supermarket progress here.</p>
    <div v-if="job.status !== 'idle'" class="brand-tiles strip-tiles">
      <article v-for="c in job.companies" :key="c.id" class="brand-tile" :class="[tileClass(c), `tile-${c.id.toLowerCase()}`]">
        <svg viewBox="0 0 48 48" class="ring" aria-hidden="true"><circle class="ring-bg" cx="24" cy="24" r="20" /><circle v-if="!c.stores_total" class="ring-fill ring-idle" cx="24" cy="24" r="20" /><circle v-else class="ring-fill" cx="24" cy="24" r="20" :style="ringStyle(c)" /><path v-if="c.stores_total && c.stores_done === c.stores_total" class="ring-check" d="M15.5 24.5l6 6 11-12.5" /></svg>
        <div class="tile-body">
          <header><strong>{{ c.label }}</strong><small>{{ c.stores_done }}/{{ c.stores_total || '…' }} stores</small></header>
          <p class="tile-products">{{ c.products }}<em> products</em></p>
        </div>
      </article>
    </div>
  </section>
</template>

<script>
const RING_CIRCUMFERENCE = 2 * Math.PI * 20;

export default {
  name: 'ProgressStrip',
  props: {
    job: { type: Object, required: true },
    running: { type: Boolean, default: false },
    pct: { type: Number, default: 0 },
    elapsed: { type: String, default: '0.0s' },
  },
  setup(props) {
    function ringStyle(c) {
      const frac = c.stores_total ? c.stores_done / c.stores_total : 0;
      return { strokeDashoffset: String(RING_CIRCUMFERENCE * (1 - frac)) };
    }
    function tileClass(c) {
      return { 'is-running': props.running, 'is-done': !props.running && c.stores_total > 0 && c.stores_done === c.stores_total };
    }
    return { ringStyle, tileClass };
  },
};
</script>
