// Shared viewport state — one resize listener for the whole app.
// Semantic breakpoints mirror the CSS media queries in styles.css
// (mobile <=768, tablet <=1080, desktop above). Layout itself stays pure
// CSS; JS only needs this for behaviour (e.g. closing the mobile drawer).

import { computed, ref } from 'vue';

const MOBILE_MAX = 768;
const COMPACT_MAX = 1080;

const width = ref(typeof window === 'undefined' ? 1440 : window.innerWidth);

let listening = false;
function update() { width.value = window.innerWidth; }
if (typeof window !== 'undefined' && !listening) {
  window.addEventListener('resize', update, { passive: true });
  listening = true;
}

const isMobile = computed(() => width.value <= MOBILE_MAX);
const isCompact = computed(() => width.value <= COMPACT_MAX);

export function useViewport() {
  return { width, isMobile, isCompact, MOBILE_MAX, COMPACT_MAX };
}
