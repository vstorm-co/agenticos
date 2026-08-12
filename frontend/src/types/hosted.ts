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
}
