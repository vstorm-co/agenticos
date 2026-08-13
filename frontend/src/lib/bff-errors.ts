/**
 * The codes a BFF route handler refuses with, and the messages they map to.
 *
 * A route handler under `src/app/api/**` sits outside the `[locale]` segment, so
 * it has no translator to write a refusal with - and for years it wrote English
 * instead (`{ detail: "Not authenticated" }`), which `parseErrorMessage` read
 * verbatim and every toast rendered as-is under every locale (#603). The client
 * is the only side that knows the locale, so the contract is: the handler writes
 * `{ code }`, and whatever renders the refusal resolves the code against the
 * `errors` namespace with the translator it already holds.
 *
 * One table, shared by both sides: the handlers take `BffErrorCode` so a typo
 * dies at compile time, and `bffErrorKey` is how `getErrorMessage` finds the
 * message. A code from anywhere else - the backend's envelope codes like
 * `ALREADY_EXISTS` - has no row here and needs none: the envelope carries its
 * own message.
 */

export const BFF_ERROR_KEYS = {
  AUTHORIZATION_FAILED: "authorizationFailed",
  AVATAR_NOT_AVAILABLE: "avatarNotAvailable",
  BACKEND_UNAVAILABLE: "backendUnavailable",
  FAILED_TO_GET_USER: "failedToGetUser",
  FILE_NOT_FOUND: "fileNotFound",
  FORBIDDEN: "forbidden",
  INTERNAL_SERVER_ERROR: "internalServerError",
  LOGIN_FAILED: "loginFailed",
  MISSING_AUTHORIZATION_CODE: "missingAuthorizationCode",
  MISSING_TOKENS: "missingTokens",
  NOT_AUTHENTICATED: "notAuthenticated",
  NO_REFRESH_TOKEN: "noRefreshToken",
  REGISTRATION_FAILED: "registrationFailed",
  SESSION_EXPIRED: "sessionExpired",
  UPLOAD_FAILED: "uploadFailed",
} as const;

export type BffErrorCode = keyof typeof BFF_ERROR_KEYS;

/** The `errors` key for a BFF refusal code, or null for a code that is not one. */
export function bffErrorKey(code: string): string | null {
  return Object.hasOwn(BFF_ERROR_KEYS, code) ? BFF_ERROR_KEYS[code as BffErrorCode] : null;
}
