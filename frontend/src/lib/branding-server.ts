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

import {
  BUILT_IN_BRANDING,
  resolveBranding,
  type Branding,
  type BrandingResponse,
} from "@/lib/branding";
import { backendFetch } from "@/lib/server-api";

export async function readBranding(): Promise<Branding> {
  try {
    const data = await backendFetch<BrandingResponse>("/api/v1/branding", {
      // Never cached: an administrator renaming the deployment expects the next
      // page load to show it, and Next would otherwise reuse this for the whole
      // lifetime of the build.
      cache: "no-store",
    });
    return resolveBranding(data);
  } catch (error) {
    console.warn("branding_read_failed", error);
    return BUILT_IN_BRANDING;
  }
}
