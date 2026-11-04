"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Blobatar } from "@blobatar/react";

import { AvatarColorPicker } from "@/components/ui/avatar-color-picker";
import { Input } from "@/components/ui/input";
import { useAgents } from "@/hooks/use-agents";
import { usePermissions } from "@/hooks/use-permissions";
import { BLOBBY_CAST, faceOf, type Face } from "@/lib/desktop/blobby-cast";
import type { BlobbyCharacter } from "@/lib/desktop/commands";
import { cn } from "@/lib/utils";

import "blobatar/motion.css";

/**
 * The ways to pick who blobby is - the cast, one of the person's agents, a face
 * of their own - shared by the Blobby settings tab and the desktop welcome.
 */

export const KINDS = ["cast", "agent", "custom"] as const;
export type Kind = (typeof KINDS)[number];
const SEED_LIMIT = 64;

export function Face({ face, size }: { face: Face; size: number }) {
  return (
    <Blobatar name={face.seed} hue={face.hue} traits={face.traits} size={size} animate="always" />
  );
}

/** A creature to pick, in a grid of them: its face and its name. */
function Pick({
  face,
  label,
  checked,
  onPick,
}: {
  face: Face;
  label: string;
  checked: boolean;
  onPick: () => void;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={checked}
      onClick={onPick}
      className={cn(
        "focus-visible:ring-ring flex flex-col items-center gap-1.5 rounded-lg border p-2.5 outline-none focus-visible:ring-2",
        checked ? "border-foreground bg-accent" : "hover:bg-accent/60 border-transparent",
      )}
    >
      <Face face={face} size={48} />
      <span className="text-foreground w-full truncate text-center text-xs font-medium">
        {label}
      </span>
    </button>
  );
}

export function CastPicker({
  value,
  onChange,
}: {
  value: BlobbyCharacter;
  onChange: (c: BlobbyCharacter) => void;
}) {
  const t = useTranslations("desktop.settings.blobby");
  return (
    <div
      role="radiogroup"
      aria-label={t("kinds.cast")}
      className="grid grid-cols-[repeat(auto-fill,minmax(5.5rem,1fr))] gap-2"
    >
      {BLOBBY_CAST.map((member) => {
        const character: BlobbyCharacter = { kind: "cast", id: member.id };
        return (
          <Pick
            key={member.id}
            face={faceOf(character)}
            label={member.name}
            checked={value.kind === "cast" && value.id === member.id}
            onPick={() => onChange(character)}
          />
        );
      })}
    </div>
  );
}

export function AgentPicker({
  value,
  onChange,
}: {
  value: BlobbyCharacter;
  onChange: (c: BlobbyCharacter) => void;
}) {
  const t = useTranslations("desktop.settings.blobby");
  const { can } = usePermissions();
  const mayList = can("agents:view");
  const { agents, isLoading } = useAgents({ enabled: mayList });
  if (!mayList || (!isLoading && agents.length === 0)) {
    return <p className="text-muted-foreground text-sm">{t("noAgents")}</p>;
  }
  return (
    <div
      role="radiogroup"
      aria-label={t("kinds.agent")}
      className="grid grid-cols-[repeat(auto-fill,minmax(5.5rem,1fr))] gap-2"
    >
      {agents.map((agent) => {
        const character: BlobbyCharacter = {
          kind: "agent",
          agent_id: agent.id,
          slug: agent.slug,
          name: agent.name,
          color_slot: agent.avatar_color ?? null,
        };
        return (
          <Pick
            key={agent.id}
            face={faceOf(character)}
            label={agent.name}
            checked={value.kind === "agent" && value.agent_id === agent.id}
            onPick={() => onChange(character)}
          />
        );
      })}
    </div>
  );
}

export function CustomPicker({
  value,
  onChange,
}: {
  value: BlobbyCharacter;
  onChange: (c: BlobbyCharacter) => void;
}) {
  const t = useTranslations("desktop.settings.blobby");
  const current =
    value.kind === "custom" ? value : { kind: "custom" as const, seed: "", color_slot: null };
  const [seed, setSeed] = useState(current.seed);
  const commit = (next: { seed: string; color_slot: number | null }) => {
    if (next.seed.trim()) onChange({ kind: "custom", ...next });
  };
  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <label htmlFor="blobby-seed" className="text-foreground text-sm font-medium">
          {t("seed")}
        </label>
        <Input
          id="blobby-seed"
          value={seed}
          maxLength={SEED_LIMIT}
          placeholder={t("seedPlaceholder")}
          onChange={(event) => setSeed(event.target.value)}
          onBlur={() => commit({ seed, color_slot: current.color_slot })}
          className="max-w-xs"
        />
        <p className="text-muted-foreground text-xs">{t("seedHint")}</p>
      </div>
      <AvatarColorPicker
        value={current.color_slot}
        onChange={(slot) => commit({ seed, color_slot: slot })}
      />
    </div>
  );
}
