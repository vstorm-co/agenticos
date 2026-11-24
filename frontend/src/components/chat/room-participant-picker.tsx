"use client";

import { Command } from "cmdk";
import { UserPlus } from "lucide-react";
import { useTranslations } from "next-intl";

import { EntityAvatar } from "@/components/ui/entity-avatar";
import { roomParticipantIdentitySuffix } from "@/lib/room-participant-labels";
import { cn } from "@/lib/utils";
import type { RoomParticipantRead } from "@/types/room";

interface RoomParticipantPickerProps {
  candidates: RoomParticipantRead[];
  disabled: boolean;
  onAdd: (participant: RoomParticipantRead) => void;
}

/** Search the server-authorized people and agents that can join this room. */
export function RoomParticipantPicker({ candidates, disabled, onAdd }: RoomParticipantPickerProps) {
  const t = useTranslations("chat.roomParticipants");

  return (
    <Command className="border-border rounded-lg border" shouldFilter>
      <div className="border-border border-b px-3 py-2">
        <Command.Input
          placeholder={t("search")}
          className="placeholder:text-muted-foreground w-full bg-transparent text-sm outline-none"
        />
      </div>
      <Command.List className="max-h-56 overflow-y-auto p-1">
        <Command.Empty className="text-muted-foreground px-3 py-6 text-center text-sm">
          {candidates.length === 0 ? t("noCandidates") : t("noMatches")}
        </Command.Empty>
        {(["user", "agent"] as const).map((kind) => {
          const group = candidates.filter((candidate) => candidate.kind === kind);
          if (group.length === 0) return null;
          return (
            <Command.Group
              key={kind}
              heading={t(kind === "agent" ? "agents" : "people")}
              className="text-muted-foreground px-2 py-1.5 text-xs"
            >
              {group.map((candidate) => {
                const suffix = roomParticipantIdentitySuffix(candidate, candidates);
                const label = suffix
                  ? t("duplicateName", { name: candidate.name, id: suffix })
                  : candidate.name;
                const visibleSuffix = suffix ? t("identitySuffix", { id: suffix }) : null;
                const kindLabel = t(candidate.kind === "agent" ? "agents" : "people");
                return (
                  <Command.Item
                    key={`${candidate.kind}:${candidate.id}`}
                    value={`${label} ${candidate.kind} ${candidate.id}`}
                    aria-label={`${label}, ${kindLabel}, ${t("add")}`}
                    disabled={disabled}
                    onSelect={() => onAdd(candidate)}
                    className={cn(
                      "text-foreground data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm outline-none",
                      disabled && "cursor-not-allowed opacity-50",
                    )}
                  >
                    <EntityAvatar
                      seed={candidate.id}
                      name={candidate.name}
                      imageSrc={candidate.avatar_url ?? undefined}
                      size="sm"
                      ariaHidden
                    />
                    <span className="min-w-0 flex-1 truncate">{candidate.name}</span>
                    {visibleSuffix && (
                      <span className="text-muted-foreground shrink-0 text-xs" aria-hidden>
                        {visibleSuffix}
                      </span>
                    )}
                    <span className="text-muted-foreground inline-flex shrink-0 items-center gap-1 text-xs">
                      <UserPlus className="size-3.5" aria-hidden />
                      {t("add")}
                    </span>
                  </Command.Item>
                );
              })}
            </Command.Group>
          );
        })}
      </Command.List>
    </Command>
  );
}
