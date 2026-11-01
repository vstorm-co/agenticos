"use client";

import { Bot, Cog, KeyRound, Workflow } from "lucide-react";
import { EntityAvatar } from "@/components/ui";
import { AgentAvatar } from "@/components/agents/agent-avatar";
import { useAuthStore } from "@/stores/auth-store";
import type { RecordSource } from "@/types/tables";

/** Origin is server metadata. Older records retain their authorizing member. */
export function RecordSourceBadge({
  source,
  principalId,
  fallback,
}: {
  source?: RecordSource | null;
  principalId?: string | null;
  fallback?: string;
}) {
  const user = useAuthStore((state) => state.user);
  const kind = source?.kind ?? (principalId ? "user" : "system");
  const id = source?.id ?? principalId;
  const name = source?.name ?? (id === user?.id ? user?.full_name || user?.email : id) ?? fallback;
  if (!name) return <span className="text-muted-foreground">—</span>;
  const Icon =
    kind === "api" ? KeyRound : kind === "workflow" ? Workflow : kind === "agent" ? Bot : Cog;
  return (
    <span className="inline-flex max-w-full min-w-0 items-center gap-2 align-middle" title={name}>
      {kind === "user" && id ? (
        <EntityAvatar
          size="xs"
          seed={id}
          name={name}
          imageSrc={`/api/users/avatar/${id}`}
          ariaHidden
        />
      ) : kind === "agent" && source?.id && source.slug ? (
        <AgentAvatar
          agentId={source.id}
          slug={source.slug}
          hasAvatar={source.has_avatar}
          colorSlot={source.avatar_color}
          size="sm"
        />
      ) : (
        <span className="bg-muted text-muted-foreground flex size-6 shrink-0 items-center justify-center rounded-full">
          <Icon className="size-3.5" aria-hidden />
        </span>
      )}
      <span className="min-w-0 truncate">{name}</span>
    </span>
  );
}
