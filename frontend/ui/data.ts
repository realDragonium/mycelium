// Fetches the substrate dump from FastAPI at /api/data.
//
// The original design was a static prototype with mock data baked in.
// This loader keeps the same `substrate.data` shape the rest of
// the UI expects, but populates it from the live substrate.

export interface Entity { id: string; name: string; description: string }
export interface Name { id: string; text: string; entity: string }
export interface Statement { id: string; kind: string; text: string; mentions: string[]; title: string }
// A when-clause tree. Leaves are {statement_id}, composites {op, of}; the
// legacy flat-string shape is still tolerated.
export type When = string | { statement_id: string } | { op: string; of: When[] };
export interface Link { from: string; to: string; link_type: string; when?: When }
export interface EntityLink { from: string; to: string; link_type: string }

export interface SubstrateData {
  entities: Entity[];
  names: Name[];
  statements: Statement[];
  links: Link[];
  entity_links?: EntityLink[];
}

// One `byId` slot for any record. `kind` is the *record* kind; a statement's
// own kind (event/state/capability) moves to `claimKind`. Screens read
// whichever fields the record has, so the other kinds' fields are optional
// rather than a union to narrow.
export type IndexedRecord = { id: string; kind: 'entity' | 'statement' | 'name'; claimKind?: string }
  & Partial<Omit<Entity & Statement & Name, 'id' | 'kind'>>;

export interface SubstrateIndex {
  byId: Record<string, IndexedRecord>;
  namesByEntity: Record<string, Name[]>;
  mentionsByEntity: Record<string, Statement[]>;
  outgoing: Record<string, Link[]>;
  incoming: Record<string, Link[]>;
  conditionUses: Record<string, Link[]>;
  entityOutgoing: Record<string, EntityLink[]>;
  entityIncoming: Record<string, EntityLink[]>;
}

// Walk a when-clause tree and yield every leaf statement_id.
function* walkWhenLeaves(when: When | undefined): Generator<string> {
  if (!when) return;
  if (typeof when === 'string') { yield when; return; }
  if ('statement_id' in when) { yield when.statement_id; return; }
  if (when.op && Array.isArray(when.of)) {
    for (const child of when.of) yield* walkWhenLeaves(child);
  }
}

function push<T>(map: Record<string, T[]>, key: string, value: T) {
  (map[key] = map[key] || []).push(value);
}

export function buildIndex(data: SubstrateData): SubstrateIndex {
  const byId: Record<string, IndexedRecord> = {};
  data.entities.forEach(e => byId[e.id] = { ...e, kind: 'entity' });
  data.statements.forEach(b => byId[b.id] = { ...b, kind: 'statement', claimKind: b.kind });
  data.names.forEach(n => byId[n.id] = { ...n, kind: 'name' });

  const namesByEntity: Record<string, Name[]> = {};
  data.names.forEach(n => push(namesByEntity, n.entity, n));

  const mentionsByEntity: Record<string, Statement[]> = {};
  data.statements.forEach(b => {
    (b.mentions || []).forEach(eid => push(mentionsByEntity, eid, b));
  });

  const outgoing: Record<string, Link[]> = {};
  const incoming: Record<string, Link[]> = {};
  // Reverse index for statements used as a `when` condition. A statement
  // can be a leaf inside any number of links' when-trees; this map lets
  // the detail screen surface "this statement gates these edges" without
  // re-walking every link on render.
  const conditionUses: Record<string, Link[]> = {};
  data.links.forEach(l => {
    push(outgoing, l.from, l);
    push(incoming, l.to, l);
    if (l.when) {
      const seen = new Set<string>();
      for (const leafId of walkWhenLeaves(l.when)) {
        if (seen.has(leafId)) continue;
        seen.add(leafId);
        push(conditionUses, leafId, l);
      }
    }
  });

  // Entity↔entity adjacency, held apart from statement-link bookkeeping so
  // the entity detail view can render it without overlap.
  const entityOutgoing: Record<string, EntityLink[]> = {};
  const entityIncoming: Record<string, EntityLink[]> = {};
  (data.entity_links || []).forEach(l => {
    push(entityOutgoing, l.from, l);
    push(entityIncoming, l.to, l);
  });

  return {
    byId, namesByEntity, mentionsByEntity,
    outgoing, incoming, conditionUses,
    entityOutgoing, entityIncoming,
  };
}

const EMPTY: SubstrateData = { entities: [], names: [], statements: [], links: [] };

// The loaded dump and its adjacency index. Screens read these directly; App
// rebuilds `index` whenever `data` is replaced and bumps a version so memos
// notice the swap.
export const substrate: { data: SubstrateData; index: SubstrateIndex } = {
  data: EMPTY,
  index: buildIndex(EMPTY),
};

type RawStatement = Omit<Statement, 'title'>;

export async function loadSubstrate(): Promise<SubstrateData> {
  const response = await fetch('/api/data', { headers: { accept: 'application/json' } });
  if (!response.ok) throw new Error('GET /api/data → ' + response.status);
  const raw = await response.json() as Omit<SubstrateData, 'statements'> & { statements: RawStatement[] };

  // Derive a short title for each statement — first sentence, capped at ~90 chars.
  // (This was inline in the original mock data; preserved here so the UI components
  // don't need to change.)
  const statements = raw.statements.map((b): Statement => {
    const first = b.text.split(/(?<=\.)\s+/)[0];
    return Object.assign(b, { title: first.length > 90 ? first.slice(0, 87) + '…' : first });
  });

  const data: SubstrateData = { ...raw, statements };
  substrate.data = data;
  return data;
}
