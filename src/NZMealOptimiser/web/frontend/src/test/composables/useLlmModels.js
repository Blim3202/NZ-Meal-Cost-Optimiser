import { computed, reactive } from 'vue';

const DEFAULTS = {
  ingredient_model: { provider: 'mistral', model_id: 'mistral-medium-latest' },
  filter_model: { provider: 'google', model_id: 'gemini-3.1-flash-lite' },
};

function modelKey(model) {
  return model && model.provider && model.model_id ? `${model.provider}::${model.model_id}` : '';
}

function summariseProvider(provider) {
  if (!provider) return { state: 'empty', label: 'Not fetched yet' };
  if (provider.available) {
    const count = (provider.models || []).length;
    return { state: 'ok', label: `Loaded ${count} model${count === 1 ? '' : 's'}` };
  }
  return { state: 'err', label: `Failed: ${provider.error || 'unknown error'}` };
}

export function useLlmModels() {
  const state = reactive({
    fetchedAt: null,
    providers: { mistral: null, google: null },
    settings: {
      ingredient_model: { ...DEFAULTS.ingredient_model },
      filter_model: { ...DEFAULTS.filter_model },
    },
    loading: false,
    refreshing: false,
    saving: false,
    error: null,
    notice: null,
  });

  function setNotice(kind, text) {
    state.error = kind === 'error' ? text : null;
    state.notice = kind === 'ok' ? text : state.notice;
  }

  async function load() {
    state.loading = true;
    try {
      const resp = await fetch('/llm/models');
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      state.fetchedAt = data.fetched_at || null;
      state.providers = data.providers || { mistral: null, google: null };
      if (data.settings) state.settings = data.settings;
    } catch (e) {
      setNotice('error', `Could not load model list: ${e.message}`);
    } finally {
      state.loading = false;
    }
  }

  async function refresh() {
    state.refreshing = true;
    setNotice('ok', null);
    try {
      const resp = await fetch('/llm/models/refresh', { method: 'POST' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      state.fetchedAt = data.fetched_at || null;
      state.providers = data.providers || { mistral: null, google: null };
      if (data.settings) state.settings = data.settings;
      setNotice('ok', 'Model list refreshed.');
    } catch (e) {
      setNotice('error', `Refresh failed: ${e.message}`);
    } finally {
      state.refreshing = false;
    }
  }

  async function save() {
    state.saving = true;
    setNotice('ok', null);
    try {
      const resp = await fetch('/llm/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(state.settings),
      });
      if (!resp.ok) {
        const body = await resp.text();
        throw new Error(body || `HTTP ${resp.status}`);
      }
      const saved = await resp.json();
      state.settings = saved;
      setNotice('ok', 'Saved.');
    } catch (e) {
      setNotice('error', `Save failed: ${e.message}`);
    } finally {
      state.saving = false;
    }
  }

  function resetDefaults() {
    state.settings = {
      ingredient_model: { ...DEFAULTS.ingredient_model },
      filter_model: { ...DEFAULTS.filter_model },
    };
    setNotice('ok', 'Defaults restored — click Save to apply.');
  }

  const mistralStatus = computed(() => summariseProvider(state.providers.mistral));
  const googleStatus = computed(() => summariseProvider(state.providers.google));

  return {
    state,
    mistralStatus,
    googleStatus,
    load,
    refresh,
    save,
    resetDefaults,
  };
}

export const LLM_MODEL_DEFAULTS = DEFAULTS;
export { modelKey };
