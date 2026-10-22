// The cockpit's view of the substrate: the shapes api.ts adapts /api/data into,
// and the adjacency index built from them.

export interface Entity { id: string; name: string; description: string }
export interface Name { id: string; text: string; entity: string }
export interface Statement { id: string; kind: string; text: string; mentions: string[]; title: string }
// Dump links use `link_type`; the cockpit reads `type`. `when` passes through
// from the dump untouched.
export interface Link { from: string; to: string; type: string; when?: unknown }
export interface EntityLink { from: string; to: string; type: string }
export interface StatementKind { name: string; layer: string; gloss: string; usageCount?: number }
export interface LinkType { name: string; gloss: string }

export interface CockpitData {
  entities: Entity[];
  names: Name[];
  statements: Statement[];
  links: Link[];
  entityLinks: EntityLink[];
  annotations: unknown[];
  statementKinds: StatementKind[];
  linkTypes: LinkType[];
  entityLinkTypes: LinkType[];
}

// `_kind` is the record kind; a statement keeps its own `kind` (event/state/…).
// Screens read whichever fields the record has, so the other kinds' fields are
// optional rather than a union to narrow.
export type IndexedRecord = { id: string; _kind: 'entity' | 'statement' | 'name' }
  & Partial<Omit<Entity & Statement & Name, 'id'>>;

export interface CockpitIndex {
  byId: Record<string, IndexedRecord>;
  outgoing: Record<string, Link[]>;
  incoming: Record<string, Link[]>;
  namesByEntity: Record<string, Name[]>;
  mentionsByEntity: Record<string, Statement[]>;
  kindLayer: Record<string, StatementKind>;
}

export function buildIndex(data: CockpitData): CockpitIndex {
  const byId: Record<string, IndexedRecord> = {};
  data.entities.forEach(e => { byId[e.id] = { ...e, _kind: 'entity' }; });
  data.statements.forEach(s => { byId[s.id] = { ...s, _kind: 'statement' }; });
  data.names.forEach(n => { byId[n.id] = { ...n, _kind: 'name' }; });

  const outgoing: Record<string, Link[]> = {}, incoming: Record<string, Link[]> = {};
  data.links.forEach(l => {
    (outgoing[l.from] = outgoing[l.from] || []).push(l);
    (incoming[l.to] = incoming[l.to] || []).push(l);
  });

  const namesByEntity: Record<string, Name[]> = {};
  data.names.forEach(n => { (namesByEntity[n.entity] = namesByEntity[n.entity] || []).push(n); });

  const mentionsByEntity: Record<string, Statement[]> = {};
  data.statements.forEach(s => (s.mentions || []).forEach(eid => {
    (mentionsByEntity[eid] = mentionsByEntity[eid] || []).push(s);
  }));

  const kindLayer: Record<string, StatementKind> = {};
  data.statementKinds.forEach(k => { kindLayer[k.name] = k; });

  return { byId, outgoing, incoming, namesByEntity, mentionsByEntity, kindLayer };
}

const EMPTY: CockpitData = {
  entities: [], names: [], statements: [], links: [], entityLinks: [],
  annotations: [], statementKinds: [], linkTypes: [], entityLinkTypes: [],
};

// The loaded substrate and its index. api.ts replaces `data` on load; App
// rebuilds `index` from it.
export const substrate: { data: CockpitData; index: CockpitIndex } = {
  data: EMPTY,
  index: buildIndex(EMPTY),
};
