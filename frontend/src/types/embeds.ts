/**
 * Types for embeds — an agent published as a widget on somebody else's site.
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
  /** Public by construction — it lives in a script tag on a public page. */
  public_key: string;
  auth_mode: EmbedAuthMode;
  has_jwt_secret: boolean;
  allowed_origins: string[];
  theme: EmbedTheme;
  context: string | null;
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
  rate_limit_per_minute: number;
}

export type EmbedEdit = Partial<Omit<NewEmbed, "agent_id">> & { is_active?: boolean };

/** The look a new widget starts with — the same defaults the backend applies. */
export const DEFAULT_EMBED_THEME: EmbedTheme = {
  title: "Ask us anything",
  subtitle: "",
  greeting: "Hi — what can I help you with?",
  placeholder: "Type your message…",
  accent: "#4f46e5",
  position: "right",
  launcher_label: "Chat",
};
