// Pure helpers shared by the dashboard pages for reading OptimisationResult.

export function winnerKeyOf(result) {
  const costs = result?.store_costs || [];
  if (!costs.length) return '';
  const best = costs.find((s) => s.complete !== false) || costs[0];
  return `${best.company}-${best.store}`;
}

export function storesOf(result, previewStores) {
  if (result) return (result.store_costs || []).filter(hasStoreCoords);
  return previewStores;
}

function hasStoreCoords(s) {
  return s.lat !== null && s.lon !== null && s.lat !== undefined && s.lon !== undefined;
}
