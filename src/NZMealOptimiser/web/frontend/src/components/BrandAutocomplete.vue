<template>
  <div class="brand-field">
    <div
      class="kw-input-wrap"
      :class="{ 'is-filled': !!localValue, 'is-duplicate': isDuplicate }"
    >
      <span class="kw-input-icon" aria-hidden="true">+</span>
      <input
        ref="inputEl"
        v-model="localValue"
        type="text"
        class="kw-add kw-add-line"
        :placeholder="placeholder"
        :aria-label="ariaLabel"
        :title="title"
        autocomplete="off"
        spellcheck="false"
        @keydown="onKey"
        @focus="onFocus"
        @blur="onBlur"
        @input="onInput"
      />
    </div>
    <Teleport to="body">
      <ul
        v-if="open && filtered.length"
        class="brand-dropdown-fixed"
        :style="dropdownStyle"
        role="listbox"
        :aria-label="ariaLabel || 'Brand suggestions'"
      >
        <li
          v-for="(b, i) in filtered"
          :key="b"
          class="brand-option"
          :class="{ active: i === activeIndex }"
          role="option"
          :aria-selected="i === activeIndex"
          @mousedown.prevent="select(b)"
          @mouseenter="activeIndex = i"
        >
          {{ b }}
        </li>
      </ul>
      <div
        v-else-if="open && localValue && !filtered.length && suggestions.length"
        class="brand-dropdown-fixed brand-dropdown-empty"
        :style="dropdownStyle"
      >
        No brands match "{{ localValue }}"
      </div>
    </Teleport>
  </div>
</template>

<script>
import { computed, nextTick, ref, watch } from 'vue';

const MAX_SUGGESTIONS = 50;

// Brand autocomplete — mirrors AddressAutocomplete's keyboard / pointer UX but
// pulls suggestions from a local prop (the cached run's unique product-brand
// list) instead of a network round-trip. Free-text entry is always permitted
// (matches the existing keyword inputs), so users can pre-filter a future run.
//
// Implementation notes:
// - The inner <input> uses a local v-model mirror (localValue). This avoids
//   the cursor-jump that a parent-driven :value + @input pattern causes when
//   the prop value flips during async re-renders. The parent gets a clean
//   v-model and only sees commits on Enter / blur / suggestion-click.
// - The dropdown is teleported to <body> with position:fixed anchored to the
//   input's bounding rect. This prevents it from being clipped by ancestor
//   overflow:hidden and from causing flex layout shifts in the rule-chips row.
export default {
  name: 'BrandAutocomplete',
  props: {
    modelValue: { type: String, default: '' },
    suggestions: { type: Array, default: () => [] },
    placeholder: { type: String, default: 'add brand ↵' },
    ariaLabel: { type: String, default: '' },
    title: { type: String, default: '' },
    minChars: { type: Number, default: 1 },
    isDuplicate: { type: Boolean, default: false },
  },
  emits: ['update:modelValue', 'commit', 'enter'],
  setup(props, { emit }) {
    const inputEl = ref(null);
    const open = ref(false);
    const activeIndex = ref(0);
    const localValue = ref(props.modelValue || '');

    // Mirror the prop into the local ref whenever the prop changes from the
    // outside (e.g. parent reset on ingredient switch).
    watch(() => props.modelValue, (next) => {
      if (next !== localValue.value) localValue.value = next || '';
    });

    const sorted = computed(() => {
      const set = new Set();
      for (const s of props.suggestions) {
        if (typeof s === 'string' && s.trim()) set.add(s.trim());
      }
      return [...set].sort((a, b) => a.localeCompare(b));
    });

    const filtered = computed(() => {
      const q = localValue.value.trim().toLowerCase();
      if (!q || q.length < props.minChars) return sorted.value.slice(0, MAX_SUGGESTIONS);
      return sorted.value
        .filter((b) => b.toLowerCase().includes(q))
        .slice(0, MAX_SUGGESTIONS);
    });

    watch(localValue, () => { activeIndex.value = 0; });

    // Recompute dropdown anchor position whenever it opens.
    const anchorRect = ref({ top: 0, left: 0, width: 0 });
    const dropdownStyle = computed(() => ({
      top: `${anchorRect.value.top + anchorRect.value.height + 4}px`,
      left: `${anchorRect.value.left}px`,
      minWidth: `${Math.max(anchorRect.value.width, 180)}px`,
    }));

    async function measureAnchor() {
      await nextTick();
      const el = inputEl.value;
      if (!el) return;
      const r = el.getBoundingClientRect();
      anchorRect.value = { top: r.top, left: r.left, width: r.width, height: r.height };
    }

    function onInput() {
      emit('update:modelValue', localValue.value);
      open.value = true;
      measureAnchor();
    }
    function onFocus() {
      measureAnchor();
      open.value = true;
    }
    function onBlur() {
      // Defer close so a mousedown on a teleported option still fires.
      setTimeout(() => { open.value = false; }, 150);
    }
    function onKey(event) {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        if (!open.value) { open.value = true; measureAnchor(); }
        if (filtered.value.length) activeIndex.value = (activeIndex.value + 1) % filtered.value.length;
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        if (filtered.value.length) activeIndex.value = (activeIndex.value - 1 + filtered.value.length) % filtered.value.length;
      } else if (event.key === 'Enter') {
        if (open.value && filtered.value[activeIndex.value]) {
          event.preventDefault();
          select(filtered.value[activeIndex.value]);
        } else if (localValue.value.trim()) {
          event.preventDefault();
          emit('enter', localValue.value);
        }
      } else if (event.key === 'Escape') {
        open.value = false;
      }
    }
    function select(brand) {
      localValue.value = brand;
      emit('update:modelValue', brand);
      emit('commit', brand);
      open.value = false;
    }

    return { inputEl, open, activeIndex, localValue, filtered, dropdownStyle, onInput, onKey, onFocus, onBlur, select };
  },
};
</script>
