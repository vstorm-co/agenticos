"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import {
  AgentPicker,
  CastPicker,
  CustomPicker,
  Face,
  KINDS,
  type Kind,
} from "@/components/desktop/blobby-pickers";
import { DesktopOnly, DesktopSetting } from "@/components/desktop/desktop-only";
import { ChoiceGroup } from "@/components/settings/choice-group";
import { SectionCard } from "@/components/settings/settings-section";
import { Switch } from "@/components/ui/switch";
import { useSetBlobby } from "@/hooks/use-desktop";
import { faceOf } from "@/lib/desktop/blobby-cast";
import { BLOBBY_SIZE, CHATTER, type BlobbySettings } from "@/lib/desktop/commands";

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
                <DesktopSetting id="blobby-size" label={t("size")} hint={t("sizeHint")}>
                  <input
                    type="range"
                    aria-labelledby="blobby-size"
                    min={BLOBBY_SIZE.min}
                    max={BLOBBY_SIZE.max}
                    step={0.05}
                    defaultValue={blobby.size}
                    onPointerUp={(event) => set({ size: Number(event.currentTarget.value) })}
                    onKeyUp={(event) => set({ size: Number(event.currentTarget.value) })}
                    className="accent-foreground w-40"
                  />
                </DesktopSetting>
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
