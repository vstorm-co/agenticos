/**
 * An agent's memory, as the operator management tab reads it.
 *
 * Two facts about a row are read-only and both drive a badge: `origin` marks
 * trust (an operator file is injectable, an agent-written one is not), and
 * `end_user_scope_key` names the partition (`null` is the shared store; a
 * `user:<id>`/`chan:<id>` key is one end-user's private one). Neither is chosen
 * on this surface — an operator authors trusted files, and the partition is
 * derived server-side from the run — so the create shape carries only an
 * optional partition and never an origin.
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
  end_user_scope_key: string | null;
  /** A readable name for a per-user partition (the member's email); null when the
   * store is shared or the key does not resolve. */
  partition_label: string | null;
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
  end_user_scope_key: string | null;
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
 * Facts are agent-written and recalled semantically at runtime; an operator
 * never authors or edits one (a query an operator typed would embed off the
 * run's ledger), so there is no create or update shape — only review and delete.
 * The content is included because a fact is short by nature: the listing is the
 * content.
 */
export interface MemoryFact {
  id: string;
  agent_id: string;
  content: string;
  end_user_scope_key: string | null;
  /** A readable name for a per-user partition (the member's email); null when the
   * store is shared or the key does not resolve. */
  partition_label: string | null;
  created_at: string | null;
}

export interface MemoryFactList {
  items: MemoryFact[];
  total: number;
}
