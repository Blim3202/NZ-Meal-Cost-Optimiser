<template>
  <div class="app-frame" :class="{ 'drawer-open': drawerOpen }">
    <header class="mobile-topbar">
      <button type="button" class="ghost-button ghost-small" aria-label="Open navigation" @click="drawerOpen = true">
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="currentColor">
          <rect x="3" y="6"  width="18" height="2" rx="1" />
          <rect x="3" y="11" width="18" height="2" rx="1" />
          <rect x="3" y="16" width="18" height="2" rx="1" />
        </svg>
      </button>
      <span class="topbar-brand"><strong>Meal Optimiser</strong><small>/app</small></span>
    </header>

    <AppSidebar :current="currentView" :rail="railMode" @navigate="navigate" />
    <div v-if="drawerOpen && isMobile" class="drawer-backdrop" @click="drawerOpen = false"></div>

    <div class="app-main">
      <!-- Dashboard + LLM Recipe Builder survive view switches: the form card
           (dish, address, distance, portions, custom builder rows, GPS,
           run results, live progress, console feed, in-flight job) all stay
           filled while users visit My Dishes, Settings, Documentation, etc. -->
      <keep-alive include="DashboardView,RecipeBuilderView">
        <component :is="activeComponent" ref="activeView" @open-dish="openDish" @open-draft="openDraft" />
      </keep-alive>
    </div>
  </div>
</template>

<script>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import AppSidebar from './components/AppSidebar.vue';
import DashboardView from './views/DashboardView.vue';
import MyDishesView from './views/MyDishesView.vue';
import RecipeBuilderView from './views/RecipeBuilderView.vue';
import DocsView from './views/DocsView.vue';
import SettingsView from './views/SettingsView.vue';
import { useViewport } from './composables/useViewport.js';
import { applyDisplaySettings } from './settings.js';

const VIEWS = {
  dashboard: DashboardView,
  dishes: MyDishesView,
  builder: RecipeBuilderView,
  docs: DocsView,
  settings: SettingsView,
};

export default {
  components: { AppSidebar },
  setup() {
    const { isCompact, isMobile } = useViewport();
    const currentView = ref('dashboard');
    const drawerOpen = ref(false);
    const activeView = ref(null);

    const activeComponent = computed(() => VIEWS[currentView.value] || DashboardView);
    const railMode = computed(() => isCompact.value && !isMobile.value);

    function navigate(id) {
      currentView.value = id;
      drawerOpen.value = false;
      window.scrollTo({ top: 0 });
    }

    // My Dishes â†’ dashboard handoff (optionally straight into edit mode).
    function openDish({ key, edit }) {
      navigate('dashboard');
      nextTick(() => activeView.value?.loadPreset(key, edit));
    }

    // LLM Recipe Builder â†’ dashboard handoff with a freshly generated draft.
    function openDraft(draft) {
      navigate('dashboard');
      nextTick(() => activeView.value?.loadDraft(draft));
    }

    // Leaving mobile widths always closes the overlay drawer.
    watch(isMobile, (mobile) => { if (!mobile) drawerOpen.value = false; });

    let offApply = null;
    onMounted(() => {
      applyDisplaySettings();
      window.addEventListener('resize', applyDisplaySettings, { passive: true });
      offApply = () => window.removeEventListener('resize', applyDisplaySettings);
    });
    onUnmounted(() => offApply?.());

    return {
      currentView, drawerOpen, activeView, activeComponent, railMode, isMobile,
      navigate, openDish, openDraft,
    };
  },
};
</script>
