/**
 * What the browser is told about this deployment, read from the server's
 * environment on every request.
 *
 * Runtime rather than `NEXT_PUBLIC_*` because one published image serves every
 * deployment: a `NEXT_PUBLIC_*` value is inlined into the browser bundle when
 * `next build` runs, so the image would carry the URLs of whoever built it and
 * every other deployment would have to rebuild rather than configure (#1544).
 * `RootLayout` calls `readPublicConfig(process.env)` and seeds
 * `PublicConfigProvider`; a client component reads `usePublicConfig()`.
 */

import type { AuthProvider } from "@/lib/auth-glyphs.generated";

export interface PublicConfig {
  /** The API origin the browser calls directly: OAuth login, embed uploads, `/docs`. */
  apiUrl: string;
  /** The WebSocket origin the browser opens for chat and the hosted embed. */
  wsUrl: string;
  /** This app's own canonical origin, for metadata, robots and the sitemap. */
  siteUrl: string;
  /**
   * The chat composer's ceiling, in megabytes.
   *
   * The composer refuses above it before reading the file, so it has to match the
   * backend's `CHAT_MAX_UPLOAD_SIZE_MB` - the chat surface's own limit, not the
   * knowledge base's larger `MAX_UPLOAD_SIZE_MB`. It defaulted to 50 once and the
   * client accepted, read and sent in full a file the server refused at 10 (#498).
   */
  chatMaxUploadSizeMb: number;
  /** The identity providers the sign-in page offers, in the order configured. */
  oauthProviders: readonly AuthProvider[];
}

export const DEFAULT_PUBLIC_CONFIG: PublicConfig = {
  apiUrl: "http://localhost:8000",
  wsUrl: "ws://localhost:8000",
  siteUrl: "http://localhost:3000",
  chatMaxUploadSizeMb: 10,
  oauthProviders: ["google"],
};

const AUTH_PROVIDERS: readonly AuthProvider[] = ["google", "github", "microsoft"];

function isAuthProvider(value: string): value is AuthProvider {
  return (AUTH_PROVIDERS as readonly string[]).includes(value);
}

function origin(value: string | undefined, fallback: string): string {
  const trimmed = value?.trim();
  return trimmed ? trimmed.replace(/\/+$/, "") : fallback;
}

function megabytes(value: string | undefined, fallback: number): number {
  const parsed = Number(value?.trim());
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function providers(
  value: string | undefined,
  fallback: readonly AuthProvider[],
): readonly AuthProvider[] {
  if (value === undefined) return fallback;
  return value
    .split(",")
    .map((name) => name.trim().toLowerCase())
    .filter(isAuthProvider);
}

/**
 * Parse the public configuration out of an environment.
 *
 * Pure, so a test hands it a plain object. An unset variable takes its default;
 * a URL loses any trailing slash so `${url}/path` never doubles it; a size that
 * is not a positive number falls back rather than disabling attachments; and an
 * `OAUTH_PROVIDERS` set to the empty string means no providers, which is how a
 * deployment turns the buttons off.
 */
export function readPublicConfig(env: Readonly<Record<string, string | undefined>>): PublicConfig {
  return {
    apiUrl: origin(env.PUBLIC_API_URL, DEFAULT_PUBLIC_CONFIG.apiUrl),
    wsUrl: origin(env.PUBLIC_WS_URL, DEFAULT_PUBLIC_CONFIG.wsUrl),
    siteUrl: origin(env.PUBLIC_SITE_URL, DEFAULT_PUBLIC_CONFIG.siteUrl),
    chatMaxUploadSizeMb: megabytes(
      env.CHAT_MAX_UPLOAD_SIZE_MB,
      DEFAULT_PUBLIC_CONFIG.chatMaxUploadSizeMb,
    ),
    oauthProviders: providers(env.OAUTH_PROVIDERS, DEFAULT_PUBLIC_CONFIG.oauthProviders),
  };
}
