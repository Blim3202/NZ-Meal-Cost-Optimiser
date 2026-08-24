<template>
  <main class="shell">
    <header class="hero">
      <div><p class="eyebrow">Recipe library</p><h1>My Dishes</h1><p class="lede">Every stored recipe — hand-curated presets plus ones you saved from the builder.</p></div>
      <span class="chip">{{ dishes.length }} dish{{ dishes.length === 1 ? '' : 'es' }}</span>
    </header>

    <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
    <p v-else-if="loading" class="empty-state panel">Loading recipes…</p>
    <p v-else-if="!dishes.length" class="empty-state panel">No dishes stored yet — build one on the dashboard and hit “Save as preset”.</p>

    <div v-else class="dish-grid">
      <article v-for="dish in dishes" :key="dish.key" class="panel dish-card">
        <div class="section-heading">
          <div><h3>{{ dish.label }}</h3><small class="muted-meta">{{ dish.ingredients.length }} ingredient searches · base {{ dish.portion }} portions</small></div>
          <span class="badge" :class="dish.source === 'user' ? 'badge-user' : 'badge-curated'" :title="dish.source === 'user' ? 'Saved by you from the dish builder' : 'Hand-curated preset shipped with the project'">{{ dish.source === 'user' ? 'User' : 'Curated' }}</span>
        </div>
        <ul class="ingredient-list">
          <li v-for="(ing, index) in dish.ingredients.slice(0, 6)" :key="index"><span class="ing-name">{{ ing.search_term }}</span><span class="ing-qty">{{ ing.quantity }} {{ ing.unit }}</span></li>
        </ul>
        <p v-if="dish.ingredients.length > 6" class="hint">+ {{ dish.ingredients.length - 6 }} more…</p>
        <div class="form-actions dish-actions">
          <button type="button" class="ghost-button ghost-small" @click="$emit('open-dish', { key: dish.key, edit: false })">Open</button>
          <button type="button" class="ghost-button ghost-small" title="Copy into the dish builder for editing" @click="$emit('open-dish', { key: dish.key, edit: true })">Edit ✎</button>
          <button type="button" class="ghost-button ghost-small danger-button" :disabled="deleting === dish.key" @click="removeDish(dish)">{{ deleting === dish.key ? 'Deleting…' : 'Delete 🗑' }}</button>
        </div>
      </article>
    </div>
  </main>
</template>

<script>
import { computed, onMounted, ref } from 'vue';

export default {
  name: 'MyDishesView',
  emits: ['open-dish'],
  setup() {
    const raw = ref({});
    const loading = ref(true);
    const error = ref('');
    const deleting = ref('');

    const dishes = computed(() => Object.entries(raw.value).map(([key, dish]) => ({
      key,
      label: dish.dish_name || key,
      portion: dish.portion || 4,
      ingredients: Array.isArray(dish.ingredients) ? dish.ingredients : [],
      source: dish.source || 'curated',
    })));

    async function fetchDishes() {
      loading.value = true;
      error.value = '';
      try {
        const response = await fetch('/dishes');
        if (!response.ok) throw new Error('Could not load dishes');
        raw.value = await response.json();
      } catch (err) {
        error.value = err.message;
      } finally {
        loading.value = false;
      }
    }

    async function removeDish(dish) {
      const curatedWarning = dish.source !== 'user'
        ? `\n\n"${dish.label}" is a hand-curated preset shipped with the project — deleting it removes it from data/dishes.json for everyone (recoverable via git).`
        : '';
      if (!window.confirm(`Delete "${dish.label}"?${curatedWarning}`)) return;
      deleting.value = dish.key;
      try {
        const response = await fetch(`/dishes/${encodeURIComponent(dish.key)}`, { method: 'DELETE' });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Could not delete the dish');
        delete raw.value[dish.key];
        raw.value = { ...raw.value };
      } catch (err) {
        error.value = err.message;
      } finally {
        deleting.value = '';
      }
    }

    onMounted(fetchDishes);

    return { dishes, loading, error, deleting, removeDish };
  },
};
</script>
