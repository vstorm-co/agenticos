"use client";

import { useSearchParams } from "next/navigation";

import type { ComposerDraft } from "@/components/chat/chat-input";
import { setUrlParam } from "@/lib/utils";
import { useOrgStore } from "@/stores/org-store";

import { preferredOrg, useOrganizationList } from "./use-organizations";

/**
 * A chat address carrying a prompt to start from — `/chat?new=1&prompt=...`,
 * as the workflows list's "Describe a workflow" sends.
 *
 * The prompt is a composer draft, the same hand-off `?discuss=` uses: the text
 * is written into the composer and never sent. It is offered only once the
 * address no longer asks for a new chat. `useChatWith` starts that chat and
 * then takes `new` off the address, and starting it remounts the composer;
 * a prompt written before that remount is lost with the old composer. Waiting
 * for `new` to go avoids writing into that first composer.
 *
 * The initial organization selection also remounts the composer. Keep the prompt
 * until that selection settles, including a successful list with no selectable
 * organization. A failed lookup leaves the draft available for a later retry.
 *
 * `consume` takes `prompt` off the address once the composer has the text, so
 * a refresh or a later remount does not write it a second time.
 */
export function useChatPrompt(): ComposerDraft | undefined {
  const params = useSearchParams();
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const refusedOrgIds = useOrgStore((state) => state.refusedOrgIds);
  const organizations = useOrganizationList();
  const organizationReady =
    activeOrgId !== null ||
    (organizations.isSuccess && preferredOrg(organizations.data, refusedOrgIds) === null);
  const prompt = params.get("prompt");
  const starting = params.get("new") || params.get("with");
  if (!prompt || starting || !organizationReady) return undefined;
  return { text: prompt, consume: () => setUrlParam("prompt", null) };
}
