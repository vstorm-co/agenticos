/**
 * What this deployment calls itself, and where the built-in answer lives.
 *
 * The API answers **overrides, not effective values** - a null crosses the wire
 * as a null, and each renderer resolves it against its own built-in. That is why
 * this module exists rather than the backend sending a finished string: one
 * default per renderer, in the place that renders it, instead of an effective
 * value computed on the server and a second copy of the same constant here for
 * when the request fails.
 *
 * The two built-ins are `APP_NAME` and `SITE`, which is where they already were.
 * `backend/tests/test_deployment_settings.py` pins `APP_NAME` equal to the
 * backend's own `PROJECT_NAME` default, because two constants for one product
 * name can drift and only a test stops them - the same bargain
 * `TestFrontendToolCatalog` takes with the tool catalog.
 */

import { APP_NAME } from "@/lib/constants";
import { SITE } from "@/lib/seo";

/** Who may create an account on this deployment. */
export type SignupMode = "open" | "invite_only" | "closed";

/** Which of three styles the announcement banner draws. */
export type NoticeLevel = "info" | "warning" | "critical";

/** `GET /api/branding`, verbatim: every identity field is an override or null. */
export interface BrandingResponse {
  app_name: string | null;
  tagline: string | null;
  description: string | null;
  logo_version: number | null;
  favicon_version: number | null;
  footer_text: string | null;
  terms_url: string | null;
  privacy_url: string | null;
  signup_mode: SignupMode;
  allowed_email_domains: string[];
  maintenance_mode: boolean;
  maintenance_message: string | null;
}

/**
 * `GET /api/branding/notice` - what an open page keeps asking, behind a session.
 *
 * The banner, and the maintenance verdict. The latter is in `BrandingResponse`
 * too, but that one is resolved once by the root server layout and never changes
 * for the life of the page - so a window opened afterwards left every open tab on
 * a dashboard whose requests had begun answering 503, and closing one left a tab
 * stuck on the maintenance screen until somebody reloaded it.
 */
export interface NoticeResponse {
  message: string | null;
  level: NoticeLevel;
  maintenance_mode: boolean;
  maintenance_message: string | null;
}

/** The resolved answer every surface reads: no nulls where a built-in exists. */
export interface Branding {
  appName: string;
  tagline: string;
  description: string;
  /** Null means "draw the built-in mark", which is the ordinary state. */
  logoUrl: string | null;
  faviconUrl: string | null;
  footerText: string | null;
  /** Null keeps the built-in `/legal/*` pages; set, and the links go outward. */
  termsUrl: string | null;
  privacyUrl: string | null;
  signupMode: SignupMode;
  allowedEmailDomains: string[];
  maintenanceMode: boolean;
  maintenanceMessage: string | null;
}

/**
 * The deployment as it ships, before an administrator changes anything.
 *
 * Also what a surface renders when the branding request fails. A sign-in page
 * that cannot reach the API must still say something rather than nothing: the
 * name is not the reason somebody is on that page.
 */
export const BUILT_IN_BRANDING: Branding = {
  appName: APP_NAME,
  tagline: SITE.tagline,
  description: SITE.description,
  logoUrl: null,
  faviconUrl: null,
  footerText: null,
  termsUrl: null,
  privacyUrl: null,
  signupMode: "open",
  allowedEmailDomains: [],
  maintenanceMode: false,
  maintenanceMessage: null,
};

/**
 * Where the browser fetches a branding image.
 *
 * Composed here rather than answered by the API, and the reason is not style: in
 * any deployment worth the name the API is not on this origin and may not be
 * reachable from a browser at all, so an address it minted would be one this app
 * had to rewrite. What the API answers is the version - whether there is an image
 * and when it last changed - and this turns that into a request the proxy serves.
 *
 * `?v=` is the whole of why it appears at all. The path is constant and the bytes
 * are served `immutable` for a year, so a browser holding the previous logo has no
 * reason to ask again unless the address changes.
 */
export function brandingImageUrl(kind: "logo" | "favicon", version: number | null): string | null {
  return version === null ? null : `/api/branding/mark/${kind}?v=${version}`;
}

/**
 * Fold what the administrator overrode onto what this build ships with.
 *
 * An empty string is treated as absent, defensively: the backend already turns a
 * cleared input into `null`, and a name that renders as nothing is worse on a
 * sign-in page than a name that is merely not theirs.
 */
export function resolveBranding(overrides: BrandingResponse | null | undefined): Branding {
  if (!overrides) return BUILT_IN_BRANDING;
  return {
    appName: overrides.app_name || BUILT_IN_BRANDING.appName,
    tagline: overrides.tagline || BUILT_IN_BRANDING.tagline,
    description: overrides.description || BUILT_IN_BRANDING.description,
    logoUrl: brandingImageUrl("logo", overrides.logo_version),
    faviconUrl: brandingImageUrl("favicon", overrides.favicon_version),
    footerText: overrides.footer_text || null,
    termsUrl: overrides.terms_url || null,
    privacyUrl: overrides.privacy_url || null,
    signupMode: overrides.signup_mode,
    allowedEmailDomains: overrides.allowed_email_domains,
    maintenanceMode: overrides.maintenance_mode,
    maintenanceMessage: overrides.maintenance_message || null,
  };
}
