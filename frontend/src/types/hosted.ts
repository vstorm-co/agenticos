/**
 * What a hosted page is told about itself before anybody says anything.
 *
 * Mirrors `PublicHostedConfig` in `backend/app/schemas/agent_embed.py`, plus the
 * public key - which the page knows from its own URL and passes down so the chat
 * has one place to read it from.
 *
 * Deliberately thin, and the omissions are the point: no agent id, no
 * organization, no counts. It is served to whoever has the link.
 */
export interface HostedPageConfig {
  public_key: string;
  title: string;
  /** Rendered before the first question. Never sent to the model. */
  welcome: string;
  accent: string;
  /**
   * Whether the page has a logo, and the API's own address for it.
   *
   * The page does not load *this* URL: it fetches `/api/embed/<key>/logo` on its
   * own origin, because the CSP excludes an API on plain `http`. What this field
   * answers is whether there is one at all - `none` chosen, `custom` with nothing
   * uploaded, or an avatar whose file has gone are all `null`, and all of them are
   * the backend's to decide.
   */
  logo_url: string | null;
  agent_name: string;
  /**
   * The declared variables a visitor's own URL may fill, via `?var_<name>=`.
   *
   * Only the URL-safe ones reach here. The server drops anything else whatever
   * the page sends, so this list saves a round trip rather than enforcing
   * anything.
   */
  variables: string[];
  /**
   * What the page may offer, as the operator set it.
   *
   * Sent rather than decided here: a capability the page turned on for itself
   * would be one the operator cannot turn off.
   */
  allow_voice: boolean;
  allow_new_conversation: boolean;
  /**
   * Whether the composer offers to attach a file.
   *
   * The only capability here that lets a visitor *store* something, so the page
   * offers no picker unless the operator ticked it - and the upload route refuses
   * one anyway, because a control the client decided to draw is not permission.
   */
  allow_files: boolean;
}
