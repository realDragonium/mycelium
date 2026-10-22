// Fetches the substrate dump from FastAPI at /api/data.
//
// The original design was a static prototype with mock data baked in.
// This loader keeps the same `window.MYCELIUM_DATA` shape the rest of
// the UI expects, but populates it from the live substrate.

window.MYCELIUM_DATA = { entities: [], names: [], statements: [], links: [] };

window.MyceliumLoadData = async function () {
  const response = await fetch('/api/data', { headers: { accept: 'application/json' } });
  if (!response.ok) throw new Error('GET /api/data → ' + response.status);
  const data = await response.json();

  // Derive a short title for each statement — first sentence, capped at ~90 chars.
  // (This was inline in the original mock data; preserved here so the UI components
  // don't need to change.)
  data.statements.forEach((b) => {
    const first = b.text.split(/(?<=\.)\s+/)[0];
    b.title = first.length > 90 ? first.slice(0, 87) + '…' : first;
  });

  window.MYCELIUM_DATA = data;
  return data;
};
