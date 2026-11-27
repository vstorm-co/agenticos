"use client";

import { createContext, useContext } from "react";

/** Menus and dialogs opened from a top-layer workspace must stay in that layer. */
export const PortalContainerContext = createContext<HTMLElement | undefined>(undefined);

export function usePortalContainer(): HTMLElement | undefined {
  return useContext(PortalContainerContext);
}
