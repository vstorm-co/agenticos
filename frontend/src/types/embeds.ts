/**
 * Types for embeds - an agent published where the public can reach it.
 *
 * Mirrors `backend/app/schemas/agent_embed.py`. Three surfaces share this shape
 * and the `kind` is what tells them apart, so `config` is a discriminated union
 * rather than three optional objects: a widget's launcher label means nothing on
 * a page, and a page's browser-tab title means nothing in a bubble.
 *
 * The signing secret appears in the create and update shapes and never in the
 * read shape: it is written once and never handed back, like every other
 * credential this platform stores.
 */

export type EmbedAuthMode = "public" | "jwt";

/**
 * Which surface an embed is.
 *
 * Fixed at creation. Every tag already pasted, every client already written and
 * every link already sent names one row, so changing the kind would change what
 * all three do without touching any of them.
 */
export type EmbedKind = "widget" | "socket" | "page";

/** What the bubble in the corner of somebody else's page looks like. */
export interface WidgetConfig {
  kind: "widget";
  title: string;
  subtitle: string;
  greeting: string;
  placeholder: string;
  /** `#rgb` or `#rrggbb`; the backend refuses anything else. */
  accent: string;
  position: "left" | "right";
  launcher_label: string;
}

/**
 * A client of one's own, and so nothing to style.
 *
 * Empty on purpose rather than absent: whoever connects renders the conversation
 * themselves, and what this kind carries is the configuration every embed has -
 * the origin allow-list, the auth mode, the context and the rate limit.
 */
export interface SocketConfig {
  kind: "socket";
}

/** Which image a hosted page shows, chosen from what the platform already stores. */
export type HostedLogo = "agent" | "organization" | "custom" | "none";

/** What a page we serve ourselves is branded with. */
export interface PageConfig {
  kind: "page";
  /** Empty falls back to the agent's name. */
  title: string;
  /** Rendered above the composer before the first question, never sent to the model. */
  welcome: string;
  /** `#rgb` or `#rrggbb`; the backend refuses anything else. */
  accent: string;
  /**
   * Whether the composer offers a microphone.
   *
   * The browser's own speech recognition dictates into the box - no audio
   * reaches this deployment. Off by default because a browser that has one hands
   * the audio to its vendor.
   */
  allow_voice: boolean;
  /** Whether the visitor may start a fresh thread, which mints a new key. */
  allow_new_conversation: boolean;
  /**
   * Whether a visitor may attach a file.
   *
   * The only setting here that lets a stranger store something. Off by default,
   * and the bytes go through the same allowlist and parser a member's upload
   * does, under a smaller cap and a per-visitor limit.
   */
  allow_files: boolean;
  /**
   * What of the agent's work the page is *sent*.
   *
   * Filters on emission rather than on rendering, which is why there is no
   * matching branch in `HostedChat`: a frame the operator did not agree to never
   * leaves the server, because reasoning hidden in CSS is an agent's reasoning
   * sitting in a stranger's devtools.
   */
  show_thinking: boolean;
  show_tool_steps: boolean;
  /** Has no effect while `show_tool_steps` is off - there is no step to open. */
  show_tool_results: boolean;
  logo: HostedLogo;
}

export type EmbedConfig = WidgetConfig | SocketConfig | PageConfig;

export interface Embed {
  id: string;
  agent_id: string;
  name: string;
  kind: EmbedKind;
  config: EmbedConfig;
  /** Public by construction - it lives in a script tag, a client or a link. */
  public_key: string;
  auth_mode: EmbedAuthMode;
  has_jwt_secret: boolean;
  allowed_origins: string[];
  context: string | null;
  /**
   * What the integration must tell this embed about the visitor in front of it.
   *
   * The placement context above is one sentence, the same for everybody. This is
   * the part only the integrator knows - supplied through
   * `window.AgenticOSContext` on a widget and through `?var_…` on a page - and
   * appended to the agent's instructions as a marked block of data, since values
   * arrive from a browser and are never instructions.
   */
  context_variables: EmbedVariable[];
  is_active: boolean;
  rate_limit_per_minute: number;
  /**
   * Whether a picture was uploaded for this page.
   *
   * The stored path stays on the server: it is an internal address, and the
   * route that streams it is what decides a page may hand that one image out
   * without a session. This says only whether there is one to replace.
   */
  has_custom_logo: boolean;
  /**
   * The three integrations, each `null` on the kinds it does not belong to.
   *
   * Assembled server-side so the deployment's public URL is known in one place,
   * and left out per kind rather than filtered here: a script tag shown beside a
   * socket integration is a line somebody would paste.
   */
  snippet: string | null;
  /** Carries no `?token=` - a real one printed in a panel is a working credential. */
  socket_url: string | null;
  /** Off the frontend's own base URL, because the frontend is what serves the page. */
  page_url: string | null;
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
  config: EmbedConfig;
  auth_mode: EmbedAuthMode;
  jwt_secret?: string | null;
  allowed_origins: string[];
  context?: string | null;
  context_variables?: EmbedVariable[];
  rate_limit_per_minute: number;
}

export type EmbedEdit = Partial<Omit<NewEmbed, "agent_id" | "config">> & {
  config?: EmbedConfig;
  is_active?: boolean;
};

/**
 * The look a new widget starts with - the same defaults the backend applies.
 *
 * i18n-exempt: seed values for a form, not copy on this surface. What a widget says
 * is read by the operator's *visitors* and edited per widget, so it must not follow
 * the operator's own dashboard locale - and the backend seeds the same English.
 */
export const DEFAULT_WIDGET_CONFIG: WidgetConfig = {
  kind: "widget",
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

export const DEFAULT_SOCKET_CONFIG: SocketConfig = { kind: "socket" };

export const DEFAULT_PAGE_CONFIG: PageConfig = {
  kind: "page",
  title: "",
  welcome: "",
  accent: "#4f46e5",
  allow_voice: false,
  allow_new_conversation: true,
  allow_files: false,
  show_thinking: false,
  show_tool_steps: true,
  show_tool_results: false,
  logo: "agent",
};

/** The config a freshly picked surface starts from. */
export function defaultConfigFor(kind: EmbedKind): EmbedConfig {
  if (kind === "widget") return DEFAULT_WIDGET_CONFIG;
  if (kind === "socket") return DEFAULT_SOCKET_CONFIG;
  return DEFAULT_PAGE_CONFIG;
}

/** One thing the integration must tell an embed about the visitor. */
export interface EmbedVariable {
  /** The key the page supplies. Lower case, digits and underscores. */
  name: string;
  /**
   * Whether the agent is expected to have it.
   *
   * Documentation and a warning, not a gate: a missing required value omits its
   * line and is logged rather than refusing the turn, because a visitor must not
   * lose an answer over somebody else's deployment mistake.
   */
  required: boolean;
  description: string;
  /**
   * Whether a hosted page may take this value from `?var_<name>=` in its own URL.
   *
   * Off by default and per variable, because a query parameter is
   * visitor-controlled input: `user_tier=premium` typed into the address bar has
   * to be impossible unless somebody decided otherwise for that one variable. It
   * means nothing on a widget or a socket, where the value arrives from an
   * integration the operator controls.
   */
  url_safe: boolean;
}
