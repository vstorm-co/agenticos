"use client";

import { createContext, useContext } from "react";
import { useInChatScope } from "@/stores/chat-scope-context";

export const MainChatContext = createContext(false);

/** A nested Architect/test conversation does not inherit the page composer. */
export function useMainChat(): boolean {
  const main = useContext(MainChatContext);
  const embedded = useInChatScope();
  return main && !embedded;
}
