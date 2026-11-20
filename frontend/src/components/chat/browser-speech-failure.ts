/** What the composer says about a failed browser recognition, by its message under `chat.input.speech`. */
export type BrowserSpeechFailure =
  "micDenied" | "micInsecure" | "micNotFound" | "unavailable" | "network" | "noSpeech" | "generic";

/**
 * The Web Speech API's `error` code, read as the step that fixes it, or `null`
 * for a recognition that was stopped and has nothing to report.
 *
 * `service-not-allowed` means the browser's own speech service will not
 * transcribe here: a browser that ships the API without that service refuses
 * every request. `network` means it could not be reached this time - Chrome
 * sends the audio to a server.
 */
export function browserSpeechFailure(error: string, secure: boolean): BrowserSpeechFailure | null {
  switch (error) {
    case "not-allowed":
      return secure ? "micDenied" : "micInsecure";
    case "audio-capture":
      return "micNotFound";
    case "service-not-allowed":
      return "unavailable";
    case "network":
      return "network";
    case "no-speech":
      return "noSpeech";
    case "aborted":
      return null;
    default:
      return "generic";
  }
}
