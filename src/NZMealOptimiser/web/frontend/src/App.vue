<template>
  <div class="app-frame" :class="{ 'drawer-open': drawerOpen }">
    <header class="mobile-topbar">
      <button type="button" class="ghost-button ghost-small" aria-label="Open navigation" @click="drawerOpen = true">☰</button>
      <span class="topbar-brand"><strong>Meal Optimiser</strong><small>/</small></span>
    </header>

    <AppSidebar :current="currentView" :rail="railMode" @navigate="navigate" />
    <div v-if="drawerOpen && isMobile" class="drawer-backdrop" @click="drawerOpen = false"></div>

    <div class="app-main">
      <!-- Only the LLM Recipe Builder survives view switches: its pasted
           recipe + generated breakdown stay filled while users run other
           queries elsewhere in the app. Everything else remounts as before. -->
      <keep-alive include="RecipeBuilderView">
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

    // My Dishes → dashboard handoff (optionally straight into edit mode).
    function openDish({ key, edit }) {
      navigate('dashboard');
      nextTick(() => activeView.value?.loadPreset(key, edit));
    }

    // LLM Recipe Builder → dashboard handoff with a freshly generated draft.
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
