/** The frontend build, compiled into both the old tab and the live server. */
export function getAppBuildId(): string | null {
  // Keep this a direct reference: Next replaces it at build time.
  return process.env.NEXT_PUBLIC_APP_BUILD_ID || null;
}

export interface AppVersion {
  buildId: string | null;
}
