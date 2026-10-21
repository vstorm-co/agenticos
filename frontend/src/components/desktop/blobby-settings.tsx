"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Blobatar } from "@blobatar/react";

import { DesktopOnly, DesktopSetting } from "@/components/desktop/desktop-only";
import { ChoiceGroup } from "@/components/settings/choice-group";
import { SectionCard } from "@/components/settings/settings-section";
import { AvatarColorPicker } from "@/components/ui/avatar-color-picker";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useAgents } from "@/hooks/use-agents";
import { useSetBlobby } from "@/hooks/use-desktop";
import { usePermissions } from "@/hooks/use-permissions";
import { BLOBBY_CAST, faceOf, type Face } from "@/lib/desktop/blobby-cast";
import { CHATTER, type BlobbyCharacter, type BlobbySettings } from "@/lib/desktop/commands";
import { cn } from "@/lib/utils";

import "blobatar/motion.css";

const KINDS = ["cast", "agent", "custom"] as const;
type Kind = (typeof KINDS)[number];
const SEED_LIMIT = 64;

function Face({ face, size }: { face: Face; size: number }) {
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

function CastPicker({
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

function AgentPicker({
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

function CustomPicker({
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

/**
 * Blobby, configured: whether it is on the desktop, who it is - one of the cast,
 * one of your agents' faces, or a face of your own - and how it behaves. Each
 * change goes to the desktop app at once, and blobby changes on the desktop
 * while the page is still open.
 */
export function BlobbySettingsPanel() {
  const t = useTranslations("desktop.settings.blobby");
  const tChatter = useTranslations("desktop.settings.blobby.chatter");
  const change = useSetBlobby();
  const [kind, setKind] = useState<Kind | null>(null);

  return (
    <DesktopOnly>
      {({ blobby }) => {
        const set = (next: Partial<BlobbySettings>) => change.mutate({ ...blobby, ...next });
        const shownKind = kind ?? blobby.character.kind;
        const pickers = {
          cast: CastPicker,
          agent: AgentPicker,
          custom: CustomPicker,
        } satisfies Record<Kind, unknown>;
        const Picker = pickers[shownKind];
        return (
          <div className="space-y-6">
            <SectionCard title={t("title")} description={t("description")}>
              <div className="flex items-center gap-6">
                <div className="bg-muted flex size-28 shrink-0 items-center justify-center rounded-2xl">
                  <Face face={faceOf(blobby.character)} size={88} />
                </div>
                <div className="min-w-0 flex-1">
                  <DesktopSetting id="blobby-shown" label={t("shown")} hint={t("shownHint")}>
                    <Switch
                      aria-labelledby="blobby-shown"
                      checked={blobby.enabled}
                      onCheckedChange={(enabled) => set({ enabled })}
                    />
                  </DesktopSetting>
                </div>
              </div>
            </SectionCard>
            <SectionCard title={t("who")} description={t("whoHint")}>
              <div className="space-y-4">
                <ChoiceGroup
                  labelledBy="blobby-kind"
                  value={shownKind}
                  options={KINDS.map((value) => ({ value, label: t(`kinds.${value}`) }))}
                  onChange={setKind}
                />
                <span id="blobby-kind" className="sr-only">
                  {t("who")}
                </span>
                <Picker
                  value={blobby.character}
                  onChange={(character) => set({ character, enabled: true })}
                />
              </div>
            </SectionCard>
            <SectionCard title={t("behaviour")}>
              <div className="space-y-5">
                <DesktopSetting id="blobby-chatter" label={t("talk")} hint={t("talkHint")}>
                  <ChoiceGroup
                    labelledBy="blobby-chatter"
                    value={blobby.chatter}
                    options={CHATTER.map((value) => ({ value, label: tChatter(value) }))}
                    onChange={(chatter) => set({ chatter })}
                  />
                </DesktopSetting>
                <DesktopSetting id="blobby-activity" label={t("activity")} hint={t("activityHint")}>
                  <Switch
                    aria-labelledby="blobby-activity"
                    checked={blobby.activity}
                    onCheckedChange={(activity) => set({ activity })}
                  />
                </DesktopSetting>
                <DesktopSetting id="blobby-roams" label={t("roams")} hint={t("roamsHint")}>
                  <Switch
                    aria-labelledby="blobby-roams"
                    checked={blobby.roams}
                    onCheckedChange={(roams) => set({ roams })}
                  />
                </DesktopSetting>
              </div>
            </SectionCard>
          </div>
        );
      }}
    </DesktopOnly>
  );
}
