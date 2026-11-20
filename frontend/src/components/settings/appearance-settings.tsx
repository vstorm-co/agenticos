"use client";

import { useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";

import { ContextHelp } from "@/components/ui/context-help";
import { ChoiceGroup } from "@/components/settings/choice-group";
import { LookPicker } from "@/components/settings/look-picker";
import { LOOK_PREVIEW } from "@/components/settings/look-preview";
import { SectionCard } from "@/components/settings/settings-section";
import { Button } from "@/components/ui/button";
import { useUserAppearance } from "@/hooks/use-user-appearance";
import { useResolvedTheme } from "@/hooks/use-resolved-theme";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import { getErrorMessage } from "@/lib/api-error";
import {
  ACCENTS,
  ACCENT_HUES,
  APPEARANCE_RADII,
  RADII,
  TEXT_SIZES,
  type UserAppearance,
} from "@/lib/user-appearance";

const THEMES = ["light", "dark", "system"] as const;
const GLOW_STYLES = ["vivid", "subtle", "off"] as const;
const MOTIONS = ["system", "reduce", "full"] as const;
const NODE_STYLES = ["colour", "simple"] as const;

/** One labelled choice in the card: a name, the group, and what it means. */
function Setting({
  id,
  label,
  hint,
  children,
}: {
  id: string;
  label: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-1">
        <p id={id} className="text-foreground text-sm font-medium">
          {label}
        </p>
        {hint && <ContextHelp>{hint}</ContextHelp>}
      </div>
      {children}
    </div>
  );
}

/** Preview is confined to a sample; only an acknowledged save changes the console. */
function AppearanceEditor({
  saved,
  account,
}: {
  saved: UserAppearance;
  account: ReturnType<typeof useUserAppearance>;
}) {
  const t = useTranslations("appearance");
  const tTheme = useTranslations("theme");
  const tGlow = useTranslations("voiceGlow");
  const tErrors = useTranslations("errors");
  const [changes, setChanges] = useState<Partial<UserAppearance>>({});
  const draft = { ...saved, ...changes };
  const resolved = useResolvedTheme(draft.theme);
  const dark = resolved === "dark";
  const [column, page, ink] = LOOK_PREVIEW[draft.look][dark ? "dark" : "light"];
  const dirty = Object.entries(changes).some(
    ([key, value]) => saved[key as keyof UserAppearance] !== value,
  );
  const choose = <K extends keyof UserAppearance>(key: K, value: UserAppearance[K]) =>
    setChanges((previous) => ({ ...previous, [key]: value }));
  const discard = () => setChanges({});
  const save = async () => {
    try {
      await account.save(changes);
      setChanges({});
      toast.success(t("saved"));
      return true;
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors));
      return false;
    }
  };
  const reset = async () => {
    try {
      await account.reset();
      setChanges({});
      toast.success(t("resetDone"));
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors));
    }
  };
  useUnsavedChanges("account-appearance", { dirty, save, discard });

  return (
    <div className="space-y-5">
      <fieldset disabled={account.pending} className="space-y-5 disabled:opacity-70">
        <Setting id="appearance-theme" label={t("theme")}>
          <ChoiceGroup
            labelledBy="appearance-theme"
            value={draft.theme}
            options={THEMES.map((value) => ({ value, label: tTheme(value) }))}
            onChange={(value) => choose("theme", value)}
          />
        </Setting>
        <Setting id="appearance-look" label={t("look")} hint={t("lookHint")}>
          <LookPicker
            labelledBy="appearance-look"
            value={draft.look}
            dark={dark}
            onChange={(value) => choose("look", value)}
          />
        </Setting>
        <Setting id="appearance-accent" label={t("accent")}>
          <ChoiceGroup
            labelledBy="appearance-accent"
            value={draft.accent}
            options={ACCENTS.map((value) => ({ value, label: t(`accents.${value}`) }))}
            onChange={(value) => choose("accent", value)}
          />
        </Setting>
        <Setting id="appearance-radius" label={t("radius")}>
          <ChoiceGroup
            labelledBy="appearance-radius"
            value={draft.radius}
            options={RADII.map((value) => ({ value, label: t(`radii.${value}`) }))}
            onChange={(value) => choose("radius", value)}
          />
        </Setting>
        <Setting id="appearance-text-size" label={t("textSize")}>
          <ChoiceGroup
            labelledBy="appearance-text-size"
            value={draft.text_size}
            options={TEXT_SIZES.map((value) => ({ value, label: t(`textSizes.${value}`) }))}
            onChange={(value) => choose("text_size", value)}
          />
        </Setting>
        <Setting id="appearance-voice-glow" label={tGlow("title")} hint={t("voiceGlowHint")}>
          <ChoiceGroup
            labelledBy="appearance-voice-glow"
            value={draft.voice_glow}
            options={GLOW_STYLES.map((value) => ({ value, label: tGlow(value) }))}
            onChange={(value) => choose("voice_glow", value)}
          />
          <p className="text-muted-foreground mt-1.5 text-xs">{tGlow("reducedMotion")}</p>
        </Setting>
        <Setting id="appearance-motion" label={t("motion")} hint={t("motionHint")}>
          <ChoiceGroup
            labelledBy="appearance-motion"
            value={draft.motion}
            options={MOTIONS.map((value) => ({ value, label: t(value) }))}
            onChange={(value) => choose("motion", value)}
          />
        </Setting>
        <Setting
          id="appearance-workflow-nodes"
          label={t("workflowNodes")}
          hint={t("workflowNodesHint")}
        >
          <ChoiceGroup
            labelledBy="appearance-workflow-nodes"
            value={draft.workflow_nodes}
            options={NODE_STYLES.map((value) => ({ value, label: t(value) }))}
            onChange={(value) => choose("workflow_nodes", value)}
          />
        </Setting>
      </fieldset>

      <section
        aria-label={t("preview")}
        className="overflow-hidden border"
        style={{
          borderRadius: APPEARANCE_RADII[draft.radius],
          background: page,
          color: ink,
          fontSize: draft.text_size === "large" ? "1.125rem" : "1rem",
        }}
      >
        <div className="px-4 py-3" style={{ background: column }}>
          {t("preview")}
        </div>
        <div className="space-y-3 p-4">
          <p className="font-semibold">{t("previewTitle")}</p>
          <p>{t("previewText")}</p>
          <span
            className="inline-block px-4 py-2"
            style={{
              borderRadius: APPEARANCE_RADII[draft.radius],
              // i18n-exempt: CSS colour coordinates for the preview.
              background: `oklch(48% ${draft.accent === "default" ? 0 : 0.16} ${ACCENT_HUES[draft.accent]})`,
              color: "white",
            }}
          >
            {t("previewAction")}
          </span>
        </div>
      </section>
      <p className="text-muted-foreground text-xs" role="status">
        {t("previewHint")}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button disabled={!dirty || account.pending} onClick={() => void save()}>
          {t("apply")}
        </Button>
        <Button variant="outline" disabled={!dirty || account.pending} onClick={discard}>
          {t("discard")}
        </Button>
        <Button variant="ghost" disabled={account.pending} onClick={() => void reset()}>
          {t("reset")}
        </Button>
      </div>
    </div>
  );
}

export function AppearanceSettings() {
  const t = useTranslations("appearance");
  const tTheme = useTranslations("theme");
  const account = useUserAppearance();
  return (
    <div data-tour="settings-appearance">
      <SectionCard title={tTheme("appearance")} description={t("description")}>
        {account.preferences ? (
          <AppearanceEditor key={account.owner} saved={account.preferences} account={account} />
        ) : account.error ? (
          <div role="alert" className="space-y-3">
            <p>{t("loadError")}</p>
            <Button variant="outline" onClick={() => void account.refetch()}>
              {t("retry")}
            </Button>
          </div>
        ) : (
          <div className="min-h-60 space-y-4" aria-busy="true">
            <p role="status">{t("loading")}</p>
            <div className="bg-muted h-9 w-56 animate-pulse rounded-md" />
            <div className="bg-muted h-24 animate-pulse rounded-md" />
          </div>
        )}
      </SectionCard>
    </div>
  );
}
