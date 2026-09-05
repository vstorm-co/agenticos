/**
 * An agent's memory, as the operator management tab reads it.
 *
 * Two facts about a row are read-only and both drive a badge: `origin` marks
 * trust (an operator file is injectable, an agent-written one is not), and
 * `owner_key` names whose memory it is — `null` is the organisation's store,
 * `person:<id>` one person's, `room:<platform>:<chat>` one group chat's. Neither
 * is chosen on this surface — an operator authors trusted files, and the owner is
 * derived server-side from who is listening to the run — so the create shape
 * carries only an optional owner and never an origin.
 */

export type MemoryOrigin = "operator" | "agent";

/** A memory file as the index lists it — without the body. */
export interface MemoryFileSummary {
  id: string;
  name: string;
  description: string | null;
  format: string;
  kind: string;
  origin: MemoryOrigin;
  owner_key: string | null;
  /** A readable name for a person's store (the member's email); null for the
   * organisation's store, a room, or a key that does not resolve. */
  owner_label: string | null;
  size_bytes: number;
}

/** One memory file, body included — what the editor opens. */
export interface MemoryFile {
  id: string;
  agent_id: string;
  name: string;
  description: string | null;
  content: string;
  format: string;
  kind: string;
  origin: MemoryOrigin;
  owner_key: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface MemoryFileList {
  items: MemoryFileSummary[];
  total: number;
}

/**
 * One remembered fact, as an operator reviews it.
 *
 * Facts are recalled semantically at runtime. The agent writes them, but an
 * operator may also seed one, so — like a file — a fact carries an `origin`: it
 * is the trust tier that decides whether the fact may enter the injected brief.
 * There is a create shape but no update: a fact is replaced, not amended. The
 * content is included because a fact is short by nature: the listing is the
 * content.
 */
export interface MemoryFact {
  id: string;
  agent_id: string;
  content: string;
  origin: MemoryOrigin;
  owner_key: string | null;
  /** A readable name for a person's store (the member's email); null for the
   * organisation's store, a room, or a key that does not resolve. */
  owner_label: string | null;
  created_at: string | null;
}

export interface MemoryFactList {
  items: MemoryFact[];
  total: number;
}
