/**
 * What a person can point an agent at with `@` in the composer (#2189). A
 * `project` is the composer's alone - picking one starts the chat in it - and
 * never goes out as a mention.
 */
export type MentionKind =
  "mcp" | "capability" | "agent" | "collection" | "skill" | "context" | "project";

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
  /** The catalog's mark for an MCP server; for a capability, the tool whose icon draws it. */
  icon?: string | null;
  /** An agent's handle, for its face. */
  slug?: string | null;
  has_avatar?: boolean;
  avatar_color?: number | null;
}

export interface MentionableList {
  items: Mentionable[];
  total: number;
}
