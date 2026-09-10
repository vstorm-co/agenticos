"use client";

import { createContext, useContext, type ReactNode } from "react";

import { DEFAULT_PUBLIC_CONFIG, type PublicConfig } from "@/lib/public-config";

/**
 * The URLs and limits the browser needs, resolved on the server per request.
 *
 * A context seeded by the root layout rather than `NEXT_PUBLIC_*` constants,
 * because those are inlined at build time and one published image has to serve
 * every deployment (#1544). The default is `DEFAULT_PUBLIC_CONFIG` rather than a
 * throw: a component mounted alone - a test rendering one leaf - talks to
 * localhost instead of crashing over its own configuration.
 */
const PublicConfigContext = createContext<PublicConfig>(DEFAULT_PUBLIC_CONFIG);

export function PublicConfigProvider({
  config,
  children,
}: {
  config: PublicConfig;
  children: ReactNode;
}) {
  return <PublicConfigContext.Provider value={config}>{children}</PublicConfigContext.Provider>;
}

/** What the browser is told about this deployment. Never null, never loading. */
export function usePublicConfig(): PublicConfig {
  return useContext(PublicConfigContext);
}
