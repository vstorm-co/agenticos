"use client";

import { createContext, useContext, type ReactNode } from "react";

import { BUILT_IN_BRANDING, type Branding } from "@/lib/branding";

/**
 * This deployment's identity, resolved once on the server and read everywhere.
 *
 * A context rather than a query, and that is deliberate. The name and mark are on
 * screen in the first paint of every page - the sidebar's brand link, the sign-in
 * header, the browser tab - so fetching them from the client means every visitor
 * sees `agenticos` for one frame and then the real name, on every navigation that
 * remounts. The root layout reads the row on the server and seeds this instead.
 *
 * The default is `BUILT_IN_BRANDING` rather than a throw. A component rendered
 * outside the provider - a test mounting one leaf, a surface added later - should
 * draw the product as it ships, not crash a page over its own title.
 */
const BrandingContext = createContext<Branding>(BUILT_IN_BRANDING);

export function BrandingProvider({
  branding,
  children,
}: {
  branding: Branding;
  children: ReactNode;
}) {
  return <BrandingContext.Provider value={branding}>{children}</BrandingContext.Provider>;
}

/** What this deployment calls itself. Never null, never loading. */
export function useBranding(): Branding {
  return useContext(BrandingContext);
}
