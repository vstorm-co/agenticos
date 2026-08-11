/**
 * Types for embeds - an agent published as a widget on somebody else's site.
 *
 * Mirrors `backend/app/schemas/agent_embed.py`. The signing secret appears in
 * the create and update shapes and never in the read shape: it is written once
 * and never handed back, like every other credential this platform stores.
 */

export type EmbedAuthMode = "public" | "jwt";

export interface EmbedTheme {
  title: string;
  subtitle: string;
  greeting: string;
  placeholder: string;
  /** `#rgb` or `#rrggbb`; the backend refuses anything else. */
  accent: string;
  position: "left" | "right";
  launcher_label: string;
}

export interface Embed {
  id: string;
  agent_id: string;
  name: string;
  /** Public by construction - it lives in a script tag on a public page. */
  public_key: string;
  auth_mode: EmbedAuthMode;
  has_jwt_secret: boolean;
  allowed_origins: string[];
  theme: EmbedTheme;
  context: string | null;
  /**
   * What the page must tell this widget about the visitor in front of it.
   *
   * The placement context above is one sentence, the same for everybody. This
   * is the part only the integrator knows, supplied through
   * `window.AgenticOSContext` and appended to the agent's instructions as a
   * marked block of data - values arrive from a browser, so they are never
   * instructions.
   */
  context_variables: EmbedVariable[];
  is_active: boolean;
  rate_limit_per_minute: number;
  /** Assembled server-side, so the deployment's public URL is known in one place. */
  snippet: string;
  created_at?: string;
  updated_at?: string | null;
}

export interface EmbedList {
  items: Embed[];
  total: number;
}

export interface NewEmbed {
  agent_id: string;
  name: string;
  auth_mode: EmbedAuthMode;
  jwt_secret?: string | null;
  allowed_origins: string[];
  theme: EmbedTheme;
  context?: string | null;
  context_variables?: EmbedVariable[];
  rate_limit_per_minute: number;
}

export type EmbedEdit = Partial<Omit<NewEmbed, "agent_id">> & { is_active?: boolean };

/**
 * The look a new widget starts with - the same defaults the backend applies.
 *
 * i18n-exempt: seed values for a form, not copy on this surface. What a widget says
 * is read by the operator's *visitors* and edited per widget, so it must not follow
 * the operator's own dashboard locale - and the backend seeds the same English.
 */
export const DEFAULT_EMBED_THEME: EmbedTheme = {
  // i18n-exempt: seed values, not copy on this surface - see above.
  title: "Ask us anything",
  subtitle: "",
  greeting: "Hi - what can I help you with?",
  // i18n-exempt: seed values, not copy on this surface - see above.
  placeholder: "Type your message…",
  accent: "#4f46e5",
  position: "right",
  launcher_label: "Chat",
};

/** One thing the page must tell a widget about the visitor. */
export interface EmbedVariable {
  /** The key the page supplies. Lower case, digits and underscores. */
  name: string;
  /**
   * Whether the agent is expected to have it.
   *
   * Documentation and a warning, not a gate: a missing required value omits its
   * line and is logged rather than refusing the turn, because a visitor must
   * not lose an answer over somebody else's deployment mistake.
   */
  required: boolean;
  description: string;
}
