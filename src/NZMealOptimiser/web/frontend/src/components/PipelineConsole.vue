<template>
  <section class="terminal">
    <header class="terminal-head"><span class="tl-dot"></span><span class="tl-dot"></span><span class="tl-dot"></span><span class="terminal-title">Pipeline console · {{ title }}</span></header>
    <div class="terminal-body" ref="bodyEl">
      <p v-for="line in lines" :key="line.key" class="t-line" :class="`t-${line.kind}`"><span class="t-time">{{ line.boot ? line.time : `+${line.t.toFixed(1)}s` }}</span><span v-if="line.co" class="t-tag" :class="`tag-${line.co.toLowerCase()}`">{{ line.co }}</span><span class="t-text">{{ line.text }}</span></p>
      <p v-if="running" class="t-line t-caret"><span class="caret">▍</span></p>
    </div>
  </section>
</template>

<script>
import { nextTick, ref, watch } from 'vue';

export default {
  name: 'PipelineConsole',
  props: {
    title: { type: String, default: 'standby' },
    lines: { type: Array, default: () => [] },
    running: { type: Boolean, default: false },
  },
  setup(props) {
    const bodyEl = ref(null);
    function scrollToEnd() {
      nextTick(() => { const el = bodyEl.value; if (el) el.scrollTop = el.scrollHeight; });
    }
    watch(() => props.lines.length, scrollToEnd);
    return { bodyEl };
  },
};
</script>
