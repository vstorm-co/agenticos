"use client";

import { createContext, useContext } from "react";
import { useInChatScope } from "@/stores/chat-scope-context";

export const MainChatContext = createContext(false);
export const ArchitectChatContext = createContext(false);

/** A nested Architect/test conversation does not inherit the page composer. */
export function useMainChat(): boolean {
  const main = useContext(MainChatContext);
  const embedded = useInChatScope();
  return main && !embedded;
}

export function useMinimalComposer(): boolean {
  const main = useMainChat();
  const architect = useContext(ArchitectChatContext);
  return main || architect;
}
