<template>
  <main class="shell">
    <header class="hero">
      <div><p class="eyebrow">Workspace preferences</p><h1>Settings</h1><p class="lede">Display, units and advanced controls. Stored locally in this browser.</p></div>
      <span v-if="settings.overridesArmed" class="chip chip-danger">⚠ Overrides armed</span>
    </header>

    <!-- ── Display ────────────────────────────────────────────────────────── -->
    <section class="panel settings-section">
      <div class="settings-head"><h3>Display</h3><button type="button" class="ghost-button ghost-small" @click="resetDisplaySettings">Reset</button></div>
      <p class="hint">The app scales fluidly at any screen size — these presets only cap how wide the content grows.</p>
      <div class="width-cards" role="radiogroup" aria-label="Content width">
        <label v-for="(preset, id) in CONTENT_WIDTHS" :key="id" class="width-card" :class="{ active: settings.contentWidth === id }">
          <input v-model="settings.contentWidth" type="radio" name="content-width" :value="id"><strong>{{ preset.label }}</strong><small>{{ preset.hint }}</small>
        </label>
      </div>
      <div class="scale-row">
        <label class="field"><span>UI scale — {{ Math.round(settings.uiScale * 100) }}%</span><input v-model.number="settings.uiScale" type="range" min="0.85" max="1.2" step="0.05"></label>
        <p class="hint">Scales every font and control via a single root factor.</p>
      </div>
    </section>

    <!-- ── Unit conversions ──────────────────────────────────────────────── -->
    <section class="panel settings-section">
      <div class="settings-head"><h3>Unit conversions</h3></div>
      <p class="hint">Canonical recipe units and the aliases that fold into them (shared by the builder dropdown and the backend scaling engine). Weight/volume/count families convert directly; anything else relies on the ≈ pack-equivalent fallback in the dish builder.</p>
      <div class="detail-scroll unit-scroll">
        <table class="unit-table">
          <thead><tr><th>Canonical</th><th>Accepted aliases</th><th>Direct scaling</th></tr></thead>
          <tbody>
            <tr v-for="row in unitRows" :key="row.canonical">
              <td><code>{{ row.canonical }}</code></td>
              <td class="alias-cell">{{ row.aliases }}</td>
              <td><span :class="row.scalable ? 'ok-hint' : 'warn-hint'">{{ row.scalable ? '✓ yes' : '≈ approx fallback' }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- ── LLM models ────────────────────────────────────────────────────── -->
    <section class="panel settings-section">
      <div class="settings-head">
        <h3>LLM models</h3>
        <div class="llm-actions">
          <span v-if="llm.state.fetchedAt" class="llm-fetched">Last fetched {{ formatFetched(llm.state.fetchedAt) }}</span>
          <button type="button" class="ghost-button ghost-small" :disabled="llm.state.refreshing" @click="llm.refresh">
            {{ llm.state.refreshing ? 'Refreshing…' : 'Refresh model list' }}
          </button>
        </div>
      </div>
      <p class="hint">Pick which chat-capable model from Mistral or Google powers each step. Live-fetched from <code>/v1/models</code> and <code>/v1beta/models</code> on first load; click <strong>Refresh model list</strong> to pick up new releases. Saved server-side in <code>data/llm_settings.json</code> — survives restarts and Cloud Run container recreation.</p>

      <div v-if="llm.state.error" class="mode-note danger-note">{{ llm.state.error }}</div>
      <div v-else-if="llm.state.notice" class="mode-note ok-note">{{ llm.state.notice }}</div>

      <div class="llm-grid">
        <div class="llm-card">
          <h4>Ingredient model</h4>
          <p class="llm-status">
            Powers the Mistral "Generate custom ingredients" + "Import recipe" paths in the Dish Builder.
            <span :class="statusBadge(llm.mistralStatus.state)">{{ llm.mistralStatus.label }}</span>
          </p>
          <label class="field">
            <span>Provider + model</span>
            <select v-model="llm.state.settings.ingredient_model.provider" @change="onProviderChange('ingredient')">
              <option value="mistral">Mistral</option>
              <option value="google" :disabled="!googleReady">Google Gemini</option>
            </select>
          </label>
          <label class="field">
            <span>Model</span>
            <select v-model="llm.state.settings.ingredient_model.model_id">
              <optgroup v-if="mistralModelOptions.length" label="Mistral">
                <option v-for="m in mistralModelOptions" :key="m.id" :value="m.id">{{ optionLabel(m) }}</option>
              </optgroup>
              <optgroup v-if="googleModelOptions.length" label="Google Gemini">
                <option v-for="m in googleModelOptions" :key="m.id" :value="m.id">{{ optionLabel(m) }}</option>
              </optgroup>
            </select>
          </label>
        </div>

        <div class="llm-card">
          <h4>Filter model</h4>
          <p class="llm-status">
            Generates the include/exclude keyword rules for each generated search term.
            <span :class="statusBadge(llm.googleStatus.state)">{{ llm.googleStatus.label }}</span>
          </p>
          <label class="field">
            <span>Provider + model</span>
            <select v-model="llm.state.settings.filter_model.provider" @change="onProviderChange('filter')">
              <option value="mistral">Mistral</option>
              <option value="google" :disabled="!googleReady">Google Gemini</option>
            </select>
          </label>
          <label class="field">
            <span>Model</span>
            <select v-model="llm.state.settings.filter_model.model_id">
              <optgroup v-if="mistralModelOptions.length" label="Mistral">
                <option v-for="m in mistralModelOptions" :key="m.id" :value="m.id">{{ optionLabel(m) }}</option>
              </optgroup>
              <optgroup v-if="googleModelOptions.length" label="Google Gemini">
                <option v-for="m in googleModelOptions" :key="m.id" :value="m.id">{{ optionLabel(m) }}</option>
              </optgroup>
            </select>
          </label>
        </div>
      </div>

      <div class="llm-actions" style="margin-top: 14px;">
        <button type="button" class="primary-button" :disabled="llm.state.saving" @click="llm.save">
          {{ llm.state.saving ? 'Saving…' : 'Save model selection' }}
        </button>
        <button type="button" class="ghost-button ghost-small" :disabled="llm.state.saving" @click="llm.resetDefaults">
          Reset to defaults
        </button>
      </div>
    </section>

    <!-- ── Advanced ──────────────────────────────────────────────────────── -->
    <section class="panel settings-section">
      <div class="settings-head"><h3>Advanced</h3></div>
      <div class="adv-grid">
        <div class="adv-card">
          <h4>API key</h4>
          <p class="hint">Reserved for future server-side features. Not wired up yet — storage and provider are still undecided.</p>
          <input type="password" placeholder="Not available yet" disabled autocomplete="off">
        </div>
        <div class="adv-card">
          <h4>Search thread pool</h4>
          <template v-if="systemInfo">
            <p class="worker-line"><strong>{{ systemInfo.max_workers }}</strong> workers active <small>(configured: {{ systemInfo.configured_workers }})</small></p>
            <p class="hint">Set <code>WEB_MAX_WORKERS</code> in <code>.env</code> and restart the server to change — the pool is created once at startup.</p>
            <p class="hint">Server-side hard caps: {{ systemInfo.hard_limits.max_distance_km }} km radius · {{ systemInfo.hard_limits.max_stores_per_company }} stores/company.</p>
          </template>
          <p v-else class="hint">Loading runtime info…</p>
        </div>
      </div>
    </section>

    <!-- ── Danger zone ───────────────────────────────────────────────────── -->
    <section class="panel danger-zone">
      <div class="settings-head"><h3>Danger zone</h3></div>
      <label class="switch-row">
        <span>
          <strong>Advanced search overrides</strong>
          <small>Unlock distance up to {{ overrideCaps.max_distance_km }} km and {{ overrideCaps.max_stores_per_company }} stores/company (absolute server caps). Larger sweeps query many more supermarket endpoints per run.</small>
        </span>
        <input v-model="overridesWanted" type="checkbox" class="switch" @change="onToggleOverrides">
      </label>
      <p v-if="settings.overridesArmed" class="mode-note danger-note">⚠ Overrides active — the dashboard's Distance and Max-stores inputs now accept values up to the hard caps. The server rejects anything beyond them.</p>
    </section>

    <!-- ── Accept-risk modal ─────────────────────────────────────────────── -->
    <Teleport to="body">
      <div v-if="showRiskModal" class="modal-backdrop" @click.self="cancelRisk">
        <div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="risk-title">
          <h3 id="risk-title">Enable advanced search overrides?</h3>
          <div class="risk-body">
            <p>This unlocks search parameters far beyond normal usage:</p>
            <ul>
              <li>Search radius up to <strong>{{ overrideCaps.max_distance_km }} km</strong> (default 8 km)</li>
              <li>Up to <strong>{{ overrideCaps.max_stores_per_company }} stores per company</strong> per run (default 5)</li>
            </ul>
            <p>Large runs fire hundreds of automated requests at Pak'nSave, New World and Woolworths. This can:</p>
            <ul>
              <li>breach those supermarkets' <strong>terms of use</strong>,</li>
              <li>trigger <strong>rate-limiting, IP blocking or store-account bans</strong>, and</li>
              <li>place load on systems you do not own.</li>
            </ul>
            <p class="risk-final">You acknowledge these risks and accept <strong>full responsibility</strong> for any consequences of running oversized searches. The operator of this service is not liable for blocks, bans or other outcomes. Hard caps of {{ overrideCaps.max_distance_km }} km and {{ overrideCaps.max_stores_per_company }} stores/company are enforced server-side regardless.</p>
          </div>
          <div class="form-actions modal-actions">
            <button type="button" class="ghost-button" @click="cancelRisk">Cancel</button>
            <button type="button" class="danger-confirm" @click="acceptRisk">I accept — enable overrides</button>
          </div>
        </div>
      </div>
    </Teleport>
  </main>
</template>

<script>
import { computed, onMounted, ref } from 'vue';
import { ALIASES, isScalableUnit } from '../unitOptions.js';
import { CONTENT_WIDTHS, resetDisplaySettings, settings } from '../settings.js';
import { useLlmModels } from '../composables/useLlmModels.js';

export default {
  name: 'SettingsView',
  setup() {
    const systemInfo = ref(null);
    const showRiskModal = ref(false);
    const overridesWanted = ref(settings.overridesArmed);
    const llm = useLlmModels();

    const unitRows = computed(() => Object.entries(ALIASES).map(([canonical, aliases]) => ({
      canonical,
      aliases: aliases.filter((alias) => alias !== canonical).join(', ') || '—',
      scalable: isScalableUnit(canonical),
    })));

    const overrideCaps = computed(() => (systemInfo.value?.hard_limits) || { max_distance_km: 50, max_stores_per_company: 20 });

    const mistralModelOptions = computed(() => llm.state.providers.mistral?.models || []);
    const googleModelOptions = computed(() => llm.state.providers.google?.models || []);
    const googleReady = computed(() => !!systemInfo.value?.llm_providers?.google);

    function onProviderChange(slot) {
      const target = slot === 'ingredient' ? 'ingredient_model' : 'filter_model';
      const spec = llm.state.settings[target];
      const list = spec.provider === 'mistral' ? mistralModelOptions.value : googleModelOptions.value;
      if (list.length && !list.find((m) => m.id === spec.model_id)) {
        spec.model_id = list[0].id;
      }
    }

    function optionLabel(m) {
      if (m.max_context_length) return `${m.id} — ${m.max_context_length.toLocaleString()} ctx`;
      if (m.input_token_limit) return `${m.id} — ${m.input_token_limit.toLocaleString()} in`;
      return m.display_name || m.id;
    }

    function statusBadge(state) {
      return ['llm-status', 'badge', `badge-${state}`].join(' ');
    }

    function formatFetched(iso) {
      if (!iso) return '';
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) return iso;
      return d.toLocaleString();
    }

    function onToggleOverrides() {
      if (overridesWanted.value && !settings.overridesArmed) {
        showRiskModal.value = true;
      } else if (!overridesWanted.value) {
        settings.overridesArmed = false; // disarming needs no confirmation
      }
    }
    function cancelRisk() {
      showRiskModal.value = false;
      overridesWanted.value = settings.overridesArmed; // snap the switch back
    }
    function acceptRisk() {
      settings.overridesArmed = true;
      showRiskModal.value = false;
    }

    onMounted(async () => {
      try {
        const response = await fetch('/system-info');
        if (response.ok) systemInfo.value = await response.json();
      } catch { /* settings page still works without it */ }
      llm.load();
    });

    return {
      CONTENT_WIDTHS, settings, resetDisplaySettings,
      unitRows, systemInfo, overrideCaps,
      showRiskModal, overridesWanted, onToggleOverrides, cancelRisk, acceptRisk,
      llm, mistralModelOptions, googleModelOptions, googleReady,
      onProviderChange, optionLabel, statusBadge, formatFetched,
    };
  },
};
</script>
