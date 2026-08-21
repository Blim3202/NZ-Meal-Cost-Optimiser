<template>
  <div class="map-wrap">
    <div ref="mapEl" class="map-canvas"></div>
    <p v-if="!stores.length" class="map-hint">{{ origin ? 'No stores in range — widen the distance or move the origin.' : 'Resolve setup to preview nearby stores.' }}</p>
    <div class="map-legend">
      <span v-for="item in legendItems" :key="item.label" class="legend-item"><i class="legend-dot" :style="{ background: item.color }"></i>{{ item.label }}</span>
      <span class="legend-item"><i class="legend-dot legend-origin-dot"></i>You</span>
    </div>
  </div>
</template>

<script>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

// Single source of truth for brand pin colours (inline-styled pins + legend).
const BRAND_COLORS = { PaknSave: '#f36f21', NewWorld: '#d0021b', Woolworths: '#00b140' };
const COMPANY_LABELS = { PaknSave: "Pak'nSave", NewWorld: 'New World', Woolworths: 'Woolworths' };
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));

export default {
  name: 'MapPanel',
  props: {
    origin: { type: Object, default: null }, // {lat, lon, source}
    stores: { type: Array, default: () => [] }, // [{company, store, lat, lon, distance_km, total_used_cost, issues}]
    radiusKm: { type: Number, default: 5 },
    winnerKey: { type: String, default: '' },
  },
  emits: ['select-store'],
  setup(props, { emit }) {
    const mapEl = ref(null);
    let map = null;
    let markerLayer = null;
    let originMarker = null;
    let radiusCircle = null;
    let resizeObserver = null;

    const legendItems = Object.entries(BRAND_COLORS).map(([id, color]) => ({ label: COMPANY_LABELS[id], color }));

    function storePinHtml(store) {
      const key = `${store.company}-${store.store}`;
      const winner = key === props.winnerKey;
      const color = BRAND_COLORS[store.company] || '#5a6b7a';
      return `<span class="store-pin${winner ? ' is-winner' : ''}" style="background:${color}">${winner ? '★' : ''}</span>`;
    }

    function storeTooltip(store) {
      const issues = store.issues && store.issues.length ? `<br>⚠ ${store.issues.length} unresolved search${store.issues.length > 1 ? 'es' : ''}` : '';
      const cost = store.total_used_cost;
      const costLine = cost === null || cost === undefined || cost === ''
        ? 'Price preview — run Compare prices'
        : `Total used cost: $${Number(cost).toFixed(2)}`;
      return `<strong>${escapeHtml(store.store)}</strong><br>${escapeHtml(COMPANY_LABELS[store.company] || store.company)} · ${Number(store.distance_km ?? 0).toFixed(1)} km<br>${costLine}${issues}`;
    }

    function renderStores() {
      if (!map) return;
      markerLayer.clearLayers();
      let plotted = 0;
      for (const store of props.stores) {
        if (store.lat === null || store.lon === null || store.lat === undefined || store.lon === undefined) continue;
        L.marker([store.lat, store.lon], { icon: L.divIcon({ className: '', html: storePinHtml(store), iconSize: [20, 20], iconAnchor: [10, 10] }) })
          .bindTooltip(storeTooltip(store), { direction: 'top', offset: [0, -8], opacity: 1 })
          .on('click', () => emit('select-store', { company: store.company, store: store.store }))
          .addTo(markerLayer);
        plotted += 1;
      }
      fitView(plotted);
    }

    function renderOrigin() {
      if (!map) return;
      if (originMarker) { originMarker.remove(); originMarker = null; }
      const o = props.origin;
      if (!o || o.lat === null || o.lon === null || o.lat === undefined || o.lon === undefined) { radiusCircle.setRadius(0); fitView(props.stores.filter(hasCoords).length); return; }
      originMarker = L.marker([o.lat, o.lon], {
        icon: L.divIcon({ className: '', html: '<span class="origin-pin"></span>', iconSize: [18, 18], iconAnchor: [9, 9] }),
        zIndexOffset: 1000,
        interactive: false,
      }).addTo(map);
      radiusCircle.setLatLng([o.lat, o.lon]).setRadius((props.radiusKm || 0) * 1000);
      fitView(props.stores.filter(hasCoords).length);
    }

    const hasCoords = (store) => store.lat !== null && store.lon !== null && store.lat !== undefined && store.lon !== undefined;

    function fitView(plottedStores) {
      const points = [];
      if (originMarker) points.push(originMarker.getLatLng());
      markerLayer.eachLayer((layer) => points.push(layer.getLatLng()));
      if (!points.length) { map.setView([-41.2, 172.8], 5); return; }
      if (points.length === 1) { map.setView(points[0], Math.max(map.getZoom(), 13)); return; }
      map.fitBounds(L.latLngBounds(points).pad(0.25), { maxZoom: 14 });
      void plottedStores;
    }

    function ensureMap() {
      if (map || !mapEl.value) return;
      map = L.map(mapEl.value, { zoomControl: true });
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      }).addTo(map);
      radiusCircle = L.circle([-41.2, 172.8], { radius: 0, color: '#5a6b7a', weight: 1, dashArray: '5 5', fillColor: '#5a6b7a', fillOpacity: 0.05 }).addTo(map);
      markerLayer = L.layerGroup().addTo(map);
      map.setView([-41.2, 172.8], 5);
      renderStores();
      renderOrigin();
      resizeObserver = new ResizeObserver(() => { if (map) map.invalidateSize(); });
      resizeObserver.observe(mapEl.value);
    }

    watch(() => props.stores, renderStores);
    watch(() => props.origin, renderOrigin);
    watch(() => props.radiusKm, (km) => { if (radiusCircle && props.origin) radiusCircle.setRadius((km || 0) * 1000); });

    onMounted(ensureMap);
    onBeforeUnmount(() => {
      if (resizeObserver) resizeObserver.disconnect();
      if (map) map.remove();
      map = null;
    });

    return { mapEl, legendItems };
  },
};
</script>
