/**
 * Reading this deployment's identity on the server.
 *
 * Separate from `branding.ts` because it reaches the backend directly rather than
 * through this app's proxy, and so must never be pulled into a client bundle -
 * `BACKEND_URL` is a server address and often not one a browser could resolve.
 * Enforced by convention rather than by `server-only`, which is what `server-api.ts`
 * beside it does; the package is not a declared dependency and `lint:deps` is right
 * to say so.
 *
 * The read happens above `[locale]`, in the root layout and in the metadata that
 * layout generates. That is what gives every client component the answer
 * synchronously, with no second request and no flash of the built-in name before
 * the real one arrives.
 *
 * It never throws. A deployment whose API is down still has to render a sign-in
 * page, and the name is not why anybody is on it - so a failure resolves to what
 * this build ships with, and says so in the log rather than in the page.
 */

import { cache } from "react";

import {
  BUILT_IN_BRANDING,
  resolveBranding,
  type Branding,
  type BrandingResponse,
} from "@/lib/branding";
import { backendFetch } from "@/lib/server-api";

/** The data-cache tag the branding read is kept under; a settings save expires it. */
export const BRANDING_TAG = "branding";

/** How long a cached read may stand when nothing expired it. */
const BRANDING_REVALIDATE_SECONDS = 300;

/**
 * Memoized per request by `React.cache`, which is what makes it safe to call from
 * wherever the answer is needed. The root layout already asks twice - once for its
 * metadata and once for the body it wraps - and every page's `generateMetadata`
 * asks again for the title template's brand. Without this that is a request per
 * caller.
 */
export const readBranding = cache(async (): Promise<Branding> => {
  try {
    const data = await backendFetch<BrandingResponse>("/api/v1/branding", {
      // Kept in Next's data cache rather than read on every render: it is the
      // same answer for every visitor, and asking for it put a backend round trip
      // - 2.3 s at p95 on a contended host - in front of every page (#2219). An
      // administrator's save through `/api/admin/settings` expires the tag, so a
      // rename still shows on the next page load; the time bound covers a change
      // made some other way, through the API or on another frontend instance.
      next: { revalidate: BRANDING_REVALIDATE_SECONDS, tags: [BRANDING_TAG] },
    });
    return resolveBranding(data);
  } catch (error) {
    console.warn("branding_read_failed", error);
    return BUILT_IN_BRANDING;
  }
});
