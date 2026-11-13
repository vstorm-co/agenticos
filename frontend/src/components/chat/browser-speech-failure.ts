/** What the composer says about a failed browser recognition, by its message under `chat.input.speech`. */
export type BrowserSpeechFailure =
  "micDenied" | "micInsecure" | "micNotFound" | "unavailable" | "noSpeech" | "generic";

/**
 * The Web Speech API's `error` code, read as the step that fixes it, or `null`
 * for a recognition that was stopped and has nothing to report.
 *
 * `network` and `service-not-allowed` both mean the browser's own speech service
 * would not transcribe: Chrome sends the audio to a server, and a browser that
 * ships the API without that server refuses every request.
 */
export function browserSpeechFailure(error: string, secure: boolean): BrowserSpeechFailure | null {
  switch (error) {
    case "not-allowed":
      return secure ? "micDenied" : "micInsecure";
    case "audio-capture":
      return "micNotFound";
    case "service-not-allowed":
    case "network":
      return "unavailable";
    case "no-speech":
      return "noSpeech";
    case "aborted":
      return null;
    default:
      return "generic";
  }
}
