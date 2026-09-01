<template>
  <div class="address-field" :class="{ 'has-value': !!modelValue, 'is-open': open && (loading || suggestions.length || empty || error) }">
    <div class="address-input-wrap">
      <input
        ref="inputEl"
        type="text"
        :value="modelValue"
        :placeholder="placeholder"
        :disabled="disabled"
        autocomplete="off"
        spellcheck="false"
        :aria-expanded="open"
        aria-haspopup="listbox"
        aria-autocomplete="list"
        @input="onInput"
        @keydown="onKeydown"
        @focus="onFocus"
        @blur="onBlur"
      />
      <button
        v-if="modelValue && !disabled"
        type="button"
        class="address-clear"
        title="Clear address"
        aria-label="Clear address"
        @mousedown.prevent="clear"
      >✕</button>
    </div>
    <ul
      v-if="open && (loading || suggestions.length || empty || error)"
      ref="listEl"
      class="address-dropdown"
      role="listbox"
      :aria-label="`${suggestions.length} address suggestion${suggestions.length === 1 ? '' : 's'}`"
    >
      <li v-if="loading" class="address-empty" role="status">Searching addresses…</li>
      <li v-else-if="error" class="address-error" role="alert">{{ error }}</li>
      <li v-else-if="empty" class="address-empty">No matches yet — keep typing.</li>
      <li
        v-for="(s, i) in suggestions"
        :key="`${s.lat},${s.lon}`"
        :class="['address-option', { active: i === activeIndex }]"
        role="option"
        :aria-selected="i === activeIndex"
        @mousedown.prevent="select(s)"
        @mouseenter="activeIndex = i"
      >
        <span class="address-primary">{{ s.display }}<span v-if="s.type" class="address-type">{{ s.type }}</span></span>
        <span v-if="s.postcode" class="address-secondary">Postcode {{ s.postcode }}</span>
      </li>
    </ul>
    <p class="address-attribution">Search by <a href="https://photon.komoot.io/" target="_blank" rel="noopener">Photon</a> · © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors</p>
  </div>
</template>

<script>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';

const DEBOUNCE_MS = 300;
const MIN_CHARS = 2;
const DEFAULT_LIMIT = 8;

export default {
  name: 'AddressAutocomplete',
  props: {
    modelValue: { type: String, default: '' },
    placeholder: { type: String, default: 'Auckland CBD' },
    disabled: { type: Boolean, default: false },
    countryCode: { type: String, default: 'NZ' },
    limit: { type: Number, default: DEFAULT_LIMIT },
  },
  emits: ['update:modelValue', 'select'],
  setup(props, { emit }) {
    const inputEl = ref(null);
    const listEl = ref(null);
    const open = ref(false);
    const loading = ref(false);
    const suggestions = ref([]);
    const activeIndex = ref(-1);
    const error = ref('');
    const empty = ref(false);
    let debounceTimer = null;
    let abortController = null;
    let requestSeq = 0;

    const hasMinChars = computed(() => String(props.modelValue || '').trim().length >= MIN_CHARS);

    function clear() {
      emit('update:modelValue', '');
      suggestions.value = [];
      activeIndex.value = -1;
      error.value = '';
      empty.value = false;
      open.value = false;
      inputEl.value?.focus();
    }

    function close() {
      open.value = false;
      activeIndex.value = -1;
    }

    function resetState() {
      suggestions.value = [];
      empty.value = false;
      error.value = '';
      activeIndex.value = -1;
    }

    async function fetchSuggestions() {
      const q = String(props.modelValue || '').trim();
      if (q.length < MIN_CHARS) {
        resetState();
        loading.value = false;
        return;
      }
      const seq = ++requestSeq;
      if (abortController) abortController.abort();
      abortController = new AbortController();
      loading.value = true;
      error.value = '';
      empty.value = false;
      try {
        const params = new URLSearchParams({ q, countrycode: props.countryCode || 'NZ', limit: String(props.limit || DEFAULT_LIMIT) });
        const response = await fetch(`/geocode/autocomplete?${params.toString()}`, { signal: abortController.signal });
        if (seq !== requestSeq) return;
        const data = await response.json();
        if (!response.ok) {
          error.value = data?.detail || 'Address search failed — try again.';
          suggestions.value = [];
        } else {
          suggestions.value = Array.isArray(data.suggestions) ? data.suggestions : [];
          empty.value = suggestions.value.length === 0;
        }
      } catch (err) {
        if (err.name === 'AbortError' || seq !== requestSeq) return;
        error.value = 'Address search failed — check your connection.';
        suggestions.value = [];
      } finally {
        if (seq === requestSeq) loading.value = false;
      }
    }

    function onInput(event) {
      emit('update:modelValue', event.target.value);
      if (!open.value) open.value = true;
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(fetchSuggestions, DEBOUNCE_MS);
    }

    function onFocus() {
      if (hasMinChars.value) {
        open.value = true;
        if (!suggestions.value.length && !loading.value) fetchSuggestions();
      }
    }

    function onBlur() {
      // Defer close so mousedown on a suggestion can still fire.
      setTimeout(() => close(), 120);
    }

    function onKeydown(event) {
      if (event.key === 'ArrowDown') {
        if (!open.value) { open.value = true; return; }
        if (suggestions.value.length) activeIndex.value = (activeIndex.value + 1) % suggestions.value.length;
        event.preventDefault();
      } else if (event.key === 'ArrowUp') {
        if (suggestions.value.length) activeIndex.value = activeIndex.value <= 0 ? suggestions.value.length - 1 : activeIndex.value - 1;
        event.preventDefault();
      } else if (event.key === 'Enter') {
        if (open.value && activeIndex.value >= 0 && suggestions.value[activeIndex.value]) {
          select(suggestions.value[activeIndex.value]);
          event.preventDefault();
        }
      } else if (event.key === 'Escape') {
        close();
      }
    }

    function select(suggestion) {
      emit('update:modelValue', suggestion.display);
      emit('select', suggestion);
      open.value = false;
      activeIndex.value = -1;
      inputEl.value?.blur();
    }

    function onDocPointer(event) {
      if (!open.value) return;
      const root = inputEl.value?.closest('.address-field');
      if (root && !root.contains(event.target)) close();
    }

    watch(() => props.modelValue, (next) => {
      if (!next || String(next).trim().length < MIN_CHARS) resetState();
    });

    onMounted(() => { document.addEventListener('mousedown', onDocPointer); });
    onBeforeUnmount(() => {
      document.removeEventListener('mousedown', onDocPointer);
      if (debounceTimer) clearTimeout(debounceTimer);
      if (abortController) abortController.abort();
    });

    return { inputEl, listEl, open, loading, suggestions, activeIndex, error, empty, onInput, onFocus, onBlur, onKeydown, clear, select };
  },
};
</script>
