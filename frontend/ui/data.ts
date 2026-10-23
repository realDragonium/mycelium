// The substrate as the app holds it: the /api/data dump in its wire shape,
// the adjacency index built from it, and the vocabularies.
//
// Every screen that still reads the whole dump goes through here, and loads
// it on first use with `ensureSubstrate`; screens that have their own
// endpoint (Home, Find, drafts, gaps, settings, activity) fetch through
// api.ts instead.

import { getJSON, postJSON } from './api';

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

// Statement kinds split into two layers: descriptive facts and prescriptive
// how-to. The wire vocabulary carries no layer, so it is mapped here; a kind
// this table does not know counts as descriptive.
export type KindLayer = 'descriptive' | 'prescriptive';
const PRESCRIPTIVE_KINDS = new Set(['procedure', 'action', 'check', 'cause']);
export const layerOf = (kind: string): KindLayer => PRESCRIPTIVE_KINDS.has(kind) ? 'prescriptive' : 'descriptive';

export interface StatementKind { name: string; layer: KindLayer; gloss: string }
export interface Vocabulary { statementKinds: StatementKind[] }

// One `byId` slot for any record. `kind` is the *record* kind; a statement's
// own kind (event/state/capability) moves to `claimKind`. The graphs read
// whichever fields the record has; new code uses the typed maps below.
export type IndexedRecord = { id: string; kind: 'entity' | 'statement' | 'name'; claimKind?: string }
  & Partial<Omit<Entity & Statement & Name, 'id' | 'kind'>>;

export interface SubstrateIndex {
  byId: Record<string, IndexedRecord>;
  statements: Record<string, Statement>;
  entities: Record<string, Entity>;
  namesByEntity: Record<string, Name[]>;
  mentionsByEntity: Record<string, Statement[]>;
  outgoing: Record<string, Link[]>;
  incoming: Record<string, Link[]>;
  conditionUses: Record<string, Link[]>;
  entityOutgoing: Record<string, EntityLink[]>;
  entityIncoming: Record<string, EntityLink[]>;
}

// Walk a when-clause tree and yield every leaf statement_id.
export function* walkWhenLeaves(when: When | undefined): Generator<string> {
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
  const statements: Record<string, Statement> = {};
  const entities: Record<string, Entity> = {};
  data.entities.forEach(e => { byId[e.id] = { ...e, kind: 'entity' }; entities[e.id] = e; });
  data.statements.forEach(b => { byId[b.id] = { ...b, kind: 'statement', claimKind: b.kind }; statements[b.id] = b; });
  data.names.forEach(n => { byId[n.id] = { ...n, kind: 'name' }; });

  const namesByEntity: Record<string, Name[]> = {};
  data.names.forEach(n => push(namesByEntity, n.entity, n));

  const mentionsByEntity: Record<string, Statement[]> = {};
  data.statements.forEach(b => {
    (b.mentions || []).forEach(eid => push(mentionsByEntity, eid, b));
  });

  const outgoing: Record<string, Link[]> = {};
  const incoming: Record<string, Link[]> = {};
  // Reverse index for statements used as a `when` condition, so the detail
  // screen can show "this statement gates these edges" without re-walking
  // every link on render.
  const conditionUses: Record<string, Link[]> = {};
  data.links.forEach(l => {
    push(outgoing, l.from, l);
    push(incoming, l.to, l);
    if (l.when) {
      for (const leafId of new Set(walkWhenLeaves(l.when))) push(conditionUses, leafId, l);
    }
  });

  const entityOutgoing: Record<string, EntityLink[]> = {};
  const entityIncoming: Record<string, EntityLink[]> = {};
  (data.entity_links || []).forEach(l => {
    push(entityOutgoing, l.from, l);
    push(entityIncoming, l.to, l);
  });

  return {
    byId, statements, entities, namesByEntity, mentionsByEntity,
    outgoing, incoming, conditionUses,
    entityOutgoing, entityIncoming,
  };
}

const EMPTY: SubstrateData = { entities: [], names: [], statements: [], links: [], entity_links: [] };

// The loaded dump, its adjacency index and the vocabularies. Screens read
// these directly; the shell bumps a version after `loadSubstrate` replaces
// them so memos notice the swap.
export const substrate: { data: SubstrateData; index: SubstrateIndex; vocab: Vocabulary } = {
  data: EMPTY,
  index: buildIndex(EMPTY),
  vocab: { statementKinds: [] },
};

// Backend records have no title; the first sentence is the human handle.
export function titleOf(text: string): string {
  const first = String(text || '').split(/(?<=\.)\s+/)[0];
  return first.length > 96 ? first.slice(0, 93) + '…' : first;
}

interface RawStatementKind { kind: string; description?: string | null; when_to_use?: string | null }
type RawDump = Omit<SubstrateData, 'statements'> & { statements: Omit<Statement, 'title'>[] };

function fromWire(raw: RawDump): SubstrateData {
  const statements = raw.statements.map((s): Statement => ({ ...s, mentions: s.mentions || [], title: titleOf(s.text) }));
  return { ...raw, statements, entity_links: raw.entity_links || [] };
}

// The part of the dump around one entity or statement, for a graph that
// opens on it without loading everything.
export async function loadNeighbourhood(focus: string): Promise<{ data: SubstrateData; index: SubstrateIndex }> {
  const data = fromWire(await getJSON<RawDump>(`/api/graph/neighbourhood?focus=${encodeURIComponent(focus)}`));
  return { data, index: buildIndex(data) };
}

export interface ConceptDegree { id: string; name: string; statements: number; links: number }
export const loadGraphConcepts = () => getJSON<{ concepts: ConceptDegree[]; statements: number }>('/api/graph/concepts');

export async function loadSubstrate(): Promise<SubstrateData> {
  const [raw, kinds] = await Promise.all([
    getJSON<RawDump>('/api/data'),
    postJSON<RawStatementKind[]>('/list-statement-kinds', {}).catch((): RawStatementKind[] => []),
  ]);
  const data = fromWire(raw);
  const { statements } = data;

  // Every kind a statement uses gets a vocabulary entry, so tag and layer
  // lookups never fall through.
  const statementKinds: StatementKind[] = kinds.map(k => ({ name: k.kind, layer: layerOf(k.kind), gloss: k.description || k.when_to_use || '' }));
  const known = new Set(statementKinds.map(k => k.name));
  for (const s of statements) {
    if (s.kind && !known.has(s.kind)) { known.add(s.kind); statementKinds.push({ name: s.kind, layer: layerOf(s.kind), gloss: '' }); }
  }

  substrate.data = data;
  substrate.index = buildIndex(data);
  substrate.vocab = { statementKinds };
  loaded = true;
  return data;
}

let loaded = false;
let first: Promise<SubstrateData> | null = null;

export const substrateLoaded = () => loaded;

// The first load, shared by every screen that needs the dump. A failed load
// is forgotten so the next caller retries it.
export function ensureSubstrate(): Promise<SubstrateData> {
  first ??= loadSubstrate().catch((error: unknown) => { first = null; throw error; });
  return first;
}

// After a live edit, patch the cached statement so open views reflect it
// without reloading the whole dump.
interface RawHydratedStatement { id: string; kind: string; text: string; mentions?: { entity_id?: string }[] }
export async function refreshStatement(id: string): Promise<Statement | null> {
  const res = await postJSON<{ statements?: RawHydratedStatement[] }>('/get-statements', { ids: [id] });
  const rec = (res.statements || []).find(s => s.id === id);
  if (!rec) return null;
  const mentions = [...new Set((rec.mentions || []).map(m => m.entity_id).filter((x): x is string => !!x))];
  const next: Statement = { id, kind: rec.kind, text: rec.text, title: titleOf(rec.text), mentions };
  substrate.data = { ...substrate.data, statements: substrate.data.statements.map(s => s.id === id ? next : s) };
  substrate.index = buildIndex(substrate.data);
  return next;
}
