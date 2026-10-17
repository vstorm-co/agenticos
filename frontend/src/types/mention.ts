/** What a person can point an agent at with `@` in the composer (#2189). */
export type MentionKind = "mcp" | "agent" | "collection" | "skill" | "context";

/** One mention as a chat frame carries it. */
export interface MentionRef {
  kind: MentionKind;
  id: string;
}

/** Something the composer offers, and what a chip draws. */
export interface Mentionable extends MentionRef {
  name: string;
  /** The MCP tools' prefix, or what an agent does. */
  detail?: string | null;
  /** The catalog's mark, for an MCP server. */
  icon?: string | null;
  /** An agent's handle, for its face. */
  slug?: string | null;
  has_avatar?: boolean;
  avatar_color?: number | null;
  /** For an agent: the chat's agent hands work to it. Otherwise the turn runs on it. */
  delegate?: boolean;
}

export interface MentionableList {
  items: Mentionable[];
  total: number;
}
