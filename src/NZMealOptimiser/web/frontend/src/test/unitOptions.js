// Canonical recipe-unit registry — mirrors UNIT_ALIASES in
// NZMealOptimiser/llm/llm_utils.py so the builder dropdown and the backend
// scaling engine agree on vocabulary.

export const UNIT_GROUPS = [
  { group: 'Weight', units: ['g', 'kg', 'oz'] },
  { group: 'Volume', units: ['ml', 'l'] },
  { group: 'Spoons & cups', units: ['tsp', 'tbsp', 'cup'] },
  { group: 'Count & packs', units: ['each', 'pack'] },
  { group: 'Item / packaged', units: ['can', 'jar', 'bottle', 'bag', 'box', 'bunch', 'head', 'block', 'clove', 'slice', 'fillet', 'chop', 'stalk', 'medium', 'large', 'base'] },
];

const SCALABLE = new Set(['g', 'kg', 'oz', 'ml', 'l', 'tsp', 'tbsp', 'cup', 'each', 'pack']);

export const isScalableUnit = (unit) => SCALABLE.has(normaliseUnit(unit));

export const DEFAULT_ALIASES = {
  g: ['g', 'gram', 'grams', 'gm', 'gms'],
  kg: ['kg', 'kilogram', 'kilograms', 'kilo', 'kilos'],
  oz: ['oz', 'ounce', 'ounces'],
  ml: ['ml', 'millilitre', 'millilitres', 'milliliter', 'milliliters'],
  l: ['l', 'litre', 'litres', 'liter', 'liters'],
  tsp: ['tsp', 'teaspoon', 'teaspoons'],
  tbsp: ['tbsp', 'tablespoon', 'tablespoons'],
  cup: ['cup', 'cups'],
  each: ['each', 'ea', 'unit', 'units', 'pc', 'pcs', 'piece', 'pieces',
    'egg', 'eggs'],
  pack: ['pack', 'pk', 'packet', 'packets', 'pkt'],
  can: ['can', 'cans', 'tin', 'tins'],
  jar: ['jar', 'jars'],
  bottle: ['bottle', 'bottles'],
  bag: ['bag', 'bags'],
  box: ['box', 'boxes'],
  bunch: ['bunch', 'bunches'],
  head: ['head', 'heads'],
  block: ['block', 'blocks'],
  clove: ['clove', 'cloves'],
  slice: ['slice', 'slices'],
  fillet: ['fillet', 'fillets'],
  chop: ['chop', 'chops'],
  stalk: ['stalk', 'stalks'],
  medium: ['medium'],
  large: ['large'],
  base: ['base', 'bases'],
};

export const SCALINGS = {
  g: { factor: 1, base: 'g', label: '1 g = 1 g' },
  kg: { factor: 1000, base: 'g', label: '1 kg = 1,000 g' },
  oz: { factor: 28.3495, base: 'g', label: '1 oz = 28.35 g' },
  ml: { factor: 1, base: 'ml', label: '1 ml = 1 ml' },
  l: { factor: 1000, base: 'ml', label: '1 l = 1,000 ml' },
  tsp: { factor: 5, base: 'ml', label: '1 tsp = 5 ml' },
  tbsp: { factor: 15, base: 'ml', label: '1 tbsp = 15 ml' },
  cup: { factor: 240, base: 'ml', label: '1 cup = 240 ml' },
  each: { factor: 1, base: 'count', label: '1 each = 1 count' },
  pack: { factor: 1, base: 'count', label: '1 pack = 1 count' },
};

export function scalingLabel(canonical) {
  const s = SCALINGS[canonical];
  return s ? s.label : '—';
}

const SS_KEY = 'meal-unit-aliases';

function cloneAliases(src) {
  const out = {};
  for (const [k, v] of Object.entries(src)) out[k] = [...v];
  return out;
}

function loadAliases() {
  try {
    if (typeof sessionStorage === 'undefined') return cloneAliases(DEFAULT_ALIASES);
    const raw = sessionStorage.getItem(SS_KEY);
    if (!raw) return cloneAliases(DEFAULT_ALIASES);
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return cloneAliases(DEFAULT_ALIASES);
    const out = cloneAliases(DEFAULT_ALIASES);
    for (const [k, v] of Object.entries(parsed)) {
      if (k in out && Array.isArray(v) && v.length) {
        const cleaned = v.map((a) => String(a).trim()).filter(Boolean);
        if (cleaned.length) out[k] = cleaned;
      }
    }
    return out;
  } catch {
    return cloneAliases(DEFAULT_ALIASES);
  }
}

export const ALIASES = loadAliases();

export function persistAliases() {
  try {
    if (typeof sessionStorage !== 'undefined') sessionStorage.setItem(SS_KEY, JSON.stringify(ALIASES));
  } catch { /* quota or private mode — edits stay in-memory */ }
}

export function resetAliases() {
  const fresh = cloneAliases(DEFAULT_ALIASES);
  for (const k of Object.keys(ALIASES)) delete ALIASES[k];
  Object.assign(ALIASES, fresh);
  try { if (typeof sessionStorage !== 'undefined') sessionStorage.removeItem(SS_KEY); } catch { /* ignore */ }
}

export function findAliasConflict(alias) {
  const lower = String(alias).trim().toLowerCase();
  if (!lower) return null;
  for (const [canon, list] of Object.entries(ALIASES)) {
    if (list.some((a) => String(a).toLowerCase() === lower)) return canon;
  }
  return null;
}

export function canRemoveAlias(canonical, alias) {
  const list = ALIASES[canonical] || [];
  if (list.length <= 1) return false;
  if (String(alias).toLowerCase() === String(canonical).toLowerCase()) return false;
  return true;
}

export function addAlias(canonical, alias) {
  const raw = String(alias).trim();
  if (!raw) return { ok: false, error: 'Enter an alias' };
  if (!(canonical in ALIASES)) return { ok: false, error: 'Unknown unit' };
  const conflict = findAliasConflict(raw);
  if (conflict) return { ok: false, error: `'${raw}' already maps to '${conflict}'` };
  ALIASES[canonical].push(raw);
  persistAliases();
  return { ok: true };
}

export function removeAlias(canonical, alias) {
  const list = ALIASES[canonical];
  if (!list) return { ok: false, error: 'Unknown unit' };
  if (!canRemoveAlias(canonical, alias)) return { ok: false, error: 'Cannot remove the last alias or the canonical itself' };
  const idx = list.findIndex((a) => String(a).toLowerCase() === String(alias).toLowerCase());
  if (idx === -1) return { ok: false, error: 'Alias not found' };
  list.splice(idx, 1);
  persistAliases();
  return { ok: true };
}

export function normaliseUnit(unit) {
  if (typeof unit !== 'string') return '';
  const cleaned = unit.trim();
  const lower = cleaned.toLowerCase();
  for (const [canon, list] of Object.entries(ALIASES)) {
    if (list.some((a) => String(a).toLowerCase() === lower)) return canon;
  }
  return cleaned;
}

export const APPROX_UNITS = ['g', 'ml'];
