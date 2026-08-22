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

// Units the scaling engine can convert directly (g/ml/count families).
// Anything else relies on the approx_quantity/approx_unit fallback.
const SCALABLE = new Set(['g', 'kg', 'oz', 'ml', 'l', 'tsp', 'tbsp', 'cup', 'each', 'pack']);

export const isScalableUnit = (unit) => SCALABLE.has(normaliseUnit(unit));

const ALIASES = {
  g: ['g', 'gram', 'grams', 'gm', 'gms'],
  kg: ['kg', 'kilogram', 'kilograms', 'kilo', 'kilos'],
  oz: ['oz', 'ounce', 'ounces'],
  ml: ['ml', 'millilitre', 'millilitres', 'milliliter', 'milliliters'],
  l: ['l', 'litre', 'litres', 'liter', 'liters'],
  tsp: ['tsp', 'teaspoon', 'teaspoons'],
  tbsp: ['tbsp', 'tablespoon', 'tablespoons'],
  cup: ['cup', 'cups'],
  each: ['each', 'ea', 'unit', 'units', 'pc', 'pcs', 'piece', 'pieces',
    // One-way semantic alias (mirrors backend UNIT_ALIASES): recipes say
    // "6 eggs" but supermarkets sell eggs as count units ("10 ea", "6 pack").
    // Nothing ever maps "each" back to "egg".
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

const ALIAS_TO_CANONICAL = Object.fromEntries(
  Object.entries(ALIASES).flatMap(([canonical, list]) => list.map((alias) => [alias, canonical]))
);

export function normaliseUnit(unit) {
  if (typeof unit !== 'string') return '';
  const cleaned = unit.trim();
  return ALIAS_TO_CANONICAL[cleaned.toLowerCase()] || cleaned;
}

export const APPROX_UNITS = ['g', 'ml'];
