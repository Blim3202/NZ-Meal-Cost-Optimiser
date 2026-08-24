<template>
  <aside class="sidebar">
    <div class="sidebar-brand" @click="$emit('navigate', 'dashboard')">
      <span class="brand-mark">MO</span>
      <span class="brand-text"><strong>Meal Optimiser</strong><small>NZ grocery intelligence</small></span>
    </div>

    <nav class="sidebar-nav" aria-label="Main navigation">
      <button v-for="item in NAV_ITEMS" :key="item.id" type="button" class="side-item" :class="{ active: current === item.id }" :title="rail ? item.label : undefined" @click="$emit('navigate', item.id)">
        <span class="side-icon" v-html="item.icon"></span><span class="side-label">{{ item.label }}</span>
      </button>
      <button type="button" class="side-item side-external" title="Open the FastAPI Swagger UI (new tab)" @click="openApiDocs">
        <span class="side-icon" v-html="ICONS.api"></span><span class="side-label">API Help ↗</span>
      </button>
    </nav>

    <div class="sidebar-foot">
      <button type="button" class="side-item" :class="{ active: current === 'settings' }" :title="rail ? 'Settings' : undefined" @click="$emit('navigate', 'settings')">
        <span class="side-icon" v-html="ICONS.gear"></span><span class="side-label">Settings</span>
      </button>
    </div>
  </aside>
</template>

<script>
const svg = (paths) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;

export const ICONS = {
  dashboard: svg('<rect x="3" y="3" width="7.5" height="7.5" rx="1.5"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="1.5"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="1.5"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.5"/>'),
  dishes: svg('<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>'),
  builder: svg('<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9z"/>'),
  docs: svg('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M9 13h6M9 17h4"/>'),
  api: svg('<path d="M8 9l-4 3 4 3"/><path d="M16 9l4 3-4 3"/><path d="M13.5 5l-3 14"/>'),
  gear: svg('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.01a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h.01a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.01a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>'),
};

const NAV_ITEMS = [
  { id: 'dashboard', label: 'Dashboard', icon: ICONS.dashboard },
  { id: 'dishes', label: 'My Dishes', icon: ICONS.dishes },
  { id: 'builder', label: 'LLM Recipe Builder', icon: ICONS.builder },
  { id: 'docs', label: 'Documentation', icon: ICONS.docs },
];

export default {
  name: 'AppSidebar',
  props: {
    current: { type: String, required: true },
    rail: { type: Boolean, default: false }, // icon-only mode (tablet widths)
  },
  emits: ['navigate'],
  setup() {
    function openApiDocs() { window.open('/docs', '_blank', 'noopener'); }
    return { NAV_ITEMS, ICONS, openApiDocs };
  },
};
</script>
