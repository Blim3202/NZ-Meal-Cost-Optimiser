// User settings store for the /test dashboard — reactive singleton persisted
// to localStorage under one key. Display settings are applied as CSS custom
// properties on :root (--content-max / --font-scale) so every stylesheet
// rule reads them without per-component plumbing.

import { reactive, watch } from 'vue';

const STORAGE_KEY = 'meal-settings';

// Content-width presets ("default screen resolution" selector). Values feed
// --content-max; the shell clamps to the viewport automatically.
export const CONTENT_WIDTHS = {
  compact: { label: 'Compact', value: '1180px', hint: 'Small laptops · 1180 px cap' },
  standard: { label: 'Standard', value: '1440px', hint: 'Default · 1440 px cap' },
  wide: { label: 'Wide', value: '1760px', hint: 'Large monitors · 1760 px cap' },
  full: { label: 'Full width', value: '100%', hint: 'Use the whole viewport' },
};

function loadStored() {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    return typeof raw === 'object' && raw ? raw : {};
  } catch {
    return {};
  }
}

export const settings = reactive({
  contentWidth: 'standard',
  uiScale: 1,
  // Danger zone — armed only after the accept-risk modal is confirmed.
  overridesArmed: false,
  // Summary tab preferences (results card): which price drives rankings and
  // whether the shopper buys everything at one store or mixes and matches.
  summaryBasis: 'used', // 'used' | 'purchase'
  basketMode: 'single', // 'single' | 'multi'
  ...loadStored(),
});

// Sanitise persisted values against stale/garbage localStorage.
if (!['used', 'purchase'].includes(settings.summaryBasis)) settings.summaryBasis = 'used';
if (!['single', 'multi'].includes(settings.basketMode)) settings.basketMode = 'single';

watch(
  settings,
  () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      contentWidth: settings.contentWidth,
      uiScale: settings.uiScale,
      overridesArmed: settings.overridesArmed,
      summaryBasis: settings.summaryBasis,
      basketMode: settings.basketMode,
    }));
    applyDisplaySettings();
  },
  { deep: true },
);

export function applyDisplaySettings() {
  const preset = CONTENT_WIDTHS[settings.contentWidth] || CONTENT_WIDTHS.standard;
  const scale = Math.min(1.2, Math.max(0.85, Number(settings.uiScale) || 1));
  document.documentElement.style.setProperty('--content-max', preset.value);
  document.documentElement.style.setProperty('--font-scale', String(scale));
}

export function resetDisplaySettings() {
  settings.contentWidth = 'standard';
  settings.uiScale = 1;
}
