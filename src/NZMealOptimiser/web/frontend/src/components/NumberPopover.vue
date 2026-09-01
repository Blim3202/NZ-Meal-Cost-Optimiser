<template>
  <div class="number-popover" :class="{ open }">
    <div class="number-popover-input">
      <input
        ref="inputEl"
        v-model="text"
        type="text"
        inputmode="numeric"
        pattern="[0-9]*"
        :maxlength="maxlength"
        :placeholder="placeholder"
        :aria-label="ariaLabel"
        :aria-expanded="open"
        aria-haspopup="listbox"
        autocomplete="off"
        @focus="onFocus"
        @input="onInput"
        @keydown="onKeydown"
        @blur="onBlur"
      />
      <span v-if="suffix" class="number-popover-suffix">{{ suffix }}</span>
      <button
        type="button"
        class="number-popover-caret"
        :aria-label="open ? 'Hide options' : 'Show options'"
        :aria-expanded="open"
        @mousedown.prevent="toggleOpen"
      >▾</button>
    </div>
    <ul v-if="open" ref="listEl" class="number-popover-list" role="listbox">
      <li
        v-for="n in options"
        :key="n"
        role="option"
        :aria-selected="n === modelValue"
        :class="{ active: n === modelValue }"
        @mousedown.prevent="select(n)"
      >{{ n }}</li>
    </ul>
  </div>
</template>

<script>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';

const ROW_HEIGHT_PX = 36;

export default {
  name: 'NumberPopover',
  props: {
    modelValue: { type: Number, required: true },
    options: { type: Array, required: true },
    placeholder: { type: [String, Number], default: '' },
    suffix: { type: String, default: '' },
    maxlength: { type: Number, default: 3 },
    ariaLabel: { type: String, default: '' },
  },
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    const text = ref(String(props.modelValue));
    const open = ref(false);
    const inputEl = ref(null);
    const listEl = ref(null);

    watch(() => props.modelValue, (n) => {
      if (document.activeElement !== inputEl.value) text.value = String(n);
    });

    function onFocus() {
      text.value = '';
      open.value = true;
    }
    function onInput() {
      text.value = text.value.replace(/\D+/g, '').replace(/^0+(?=\d)/, '');
      open.value = true;
    }
    function onKeydown(e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        commit();
        inputEl.value?.blur();
      } else if (e.key === 'Escape') {
        text.value = String(props.modelValue);
        open.value = false;
        inputEl.value?.blur();
      } else if (e.key === 'ArrowDown') {
        if (!open.value) open.value = true;
        else scrollList(1);
        e.preventDefault();
      } else if (e.key === 'ArrowUp') {
        scrollList(-1);
        e.preventDefault();
      }
    }
    function onBlur() {
      commit();
      open.value = false;
    }
    function commit() {
      const parsed = Math.max(1, Math.round(Number(text.value) || props.modelValue));
      const max = props.options.length ? props.options[props.options.length - 1] : parsed;
      const clamped = Math.min(max, parsed);
      text.value = String(clamped);
      if (clamped !== props.modelValue) emit('update:modelValue', clamped);
    }
    function select(n) {
      emit('update:modelValue', n);
      text.value = String(n);
      open.value = false;
      inputEl.value?.blur();
    }
    function toggleOpen() {
      if (open.value) {
        open.value = false;
      } else {
        open.value = true;
        inputEl.value?.focus();
      }
    }
    function scrollList(delta) {
      const list = listEl.value;
      if (!list) return;
      list.scrollTop = Math.max(0, list.scrollTop + delta * ROW_HEIGHT_PX);
    }
    function onDocPointer(e) {
      if (!open.value) return;
      const root = inputEl.value?.closest('.number-popover');
      if (root && !root.contains(e.target)) open.value = false;
    }
    onMounted(() => { document.addEventListener('mousedown', onDocPointer); });
    onBeforeUnmount(() => { document.removeEventListener('mousedown', onDocPointer); });

    return { text, open, inputEl, listEl, onFocus, onInput, onKeydown, onBlur, select, toggleOpen };
  },
};
</script>
