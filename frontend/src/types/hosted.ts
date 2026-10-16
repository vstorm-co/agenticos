import type { EmbedDictation } from "@/types/embeds";
import type { RecordingFormat } from "@/types/organization";
import type { VoiceTransport } from "@/types/voice";

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
   * would be one the operator cannot turn off. `server` arrives only while a
   * provider and credential resolve; otherwise the backend sends `off`, so a
   * visitor gets no microphone rather than a broken one.
   */
  dictation: EmbedDictation;
  /** The organization's longest dictation; the recording stops itself there. */
  dictation_max_seconds: number;
  /** What to record in for `server`, from the backend's speech-to-text catalog. */
  dictation_format: RecordingFormat;
  /**
   * Whether the page offers a voice call (#54). True only while a call would
   * start - the embed's switch on, the organization's voice on and the agent's
   * voice resolving - so a visitor gets no call button rather than a broken one.
   */
  voice_conversation: boolean;
  /** How a call carries audio; null whenever no call is offered. */
  voice_transport: VoiceTransport | null;
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
