"use client";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import {
  chatControlScope,
  DEFAULT_CHAT_CONTROLS,
  useChatControlsStore,
} from "@/stores/chat-controls-store";
export function useSavedChatControls(mayWaive?: boolean) {
  const user = useAuthStore((s) => s.user?.id);
  const org = useOrgStore((s) => s.activeOrgId);
  const scope = chatControlScope(user, org);
  const prefs = useChatControlsStore((s) => s.byScope[scope] ?? DEFAULT_CHAT_CONTROLS);
  const update = useChatControlsStore((s) => s.update);
  return {
    ...prefs,
    approvalMode:
      prefs.approvalMode === "approve_all" && mayWaive === false
        ? ("follow_agent" as const)
        : prefs.approvalMode,
    update: (patch: Parameters<typeof update>[1]) => update(scope, patch),
  };
}
