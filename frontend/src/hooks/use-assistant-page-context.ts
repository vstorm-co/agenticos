"use client";

import { useCallback, useEffect, useId, useLayoutEffect, useState } from "react";
import { usePathname } from "next/navigation";

import {
  assistantPagePath,
  assistantPageSnapshot,
  sanitizeAssistantPageDetails,
  type AssistantPageDetails,
} from "@/lib/assistant-page-context";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { useAssistantPageContextStore } from "@/stores/assistant-page-context-store";

const currentScope = () =>
  JSON.stringify([useAuthStore.getState().user?.id ?? null, useOrgStore.getState().activeOrgId]);

function usePageScope(): string {
  const account = useAuthStore((state) => state.user?.id ?? null);
  const organization = useOrgStore((state) => state.activeOrgId);
  return JSON.stringify([account, organization]);
}

/**
 * A mounted page registers the details it can intentionally share. Mount its
 * provider with a key for the data's account/document scope when that changes.
 */
export function useRegisterAssistantPageContext(
  details: AssistantPageDetails | null,
  enabled = true,
): void {
  const owner = useId();
  const pathname = usePathname();
  const scope = usePageScope();
  // A provider belongs to the account that mounted it. Reusing old props after
  // a scope switch must not relabel those details as another account's data.
  const [ownerScope] = useState(scope);
  // A plain value also avoids a loop if a caller builds equivalent details inline.
  const serialized = JSON.stringify(sanitizeAssistantPageDetails(details));
  const active = enabled && details !== null && scope === ownerScope;
  useLayoutEffect(() => {
    if (!active) return;
    useAssistantPageContextStore.getState().register({
      owner,
      scope,
      path: assistantPagePath(pathname),
      details: JSON.parse(serialized) as AssistantPageDetails,
    });
    return () => useAssistantPageContextStore.getState().remove(owner);
  }, [owner, scope, pathname, active, serialized]);
}

/** Route/title fallback plus the current page's explicit, account-scoped details. */
export function useAssistantPageContext(pathname: string) {
  const scope = usePageScope();
  const registrations = useAssistantPageContextStore((state) => state.registrations);
  const [title, setTitle] = useState("");
  useEffect(() => {
    const readTitle = () => setTitle(document.title);
    readTitle();
    const observer = new MutationObserver(readTitle);
    observer.observe(document.head, { childList: true, subtree: true, characterData: true });
    return () => observer.disconnect();
  }, [pathname, scope]);

  const path = assistantPagePath(pathname);
  const registered = registrations.findLast(
    (entry) => entry.path === path && entry.scope === scope,
  );
  const page = assistantPageSnapshot(path, title, registered?.details);
  const getSnapshot = useCallback(() => {
    // Read the browser route and current stores again: a callback held across
    // navigation or an account switch must not carry the previous registration.
    const nowPath = assistantPagePath(window.location.pathname);
    const nowScope = currentScope();
    const current = useAssistantPageContextStore
      .getState()
      .registrations.findLast((entry) => entry.path === nowPath && entry.scope === nowScope);
    return assistantPageSnapshot(nowPath, document.title, current?.details);
  }, []);
  return { page, getSnapshot };
}
