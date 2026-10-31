"use client";

import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { ChoiceGroup } from "@/components/settings/choice-group";
import { LookPicker } from "@/components/settings/look-picker";
import { SectionCard } from "@/components/settings/settings-section";
import { useMounted } from "@/hooks/use-mounted";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
import { useResolvedTheme } from "@/hooks/use-resolved-theme";
import { useMotionStore, type MotionPreference } from "@/stores/motion-store";
import { useThemeStore, type Theme } from "@/stores/theme-store";
import { useVoiceGlowStore, type VoiceGlowStyle } from "@/stores/voice-glow-store";
import { useWorkflowNodeStyleStore, type NodeStyle } from "@/stores/workflow-node-style-store";

const THEMES: readonly Theme[] = ["light", "dark", "system"];
const GLOW_STYLES: readonly VoiceGlowStyle[] = ["vivid", "subtle", "off"];
const MOTIONS: readonly MotionPreference[] = ["system", "reduce", "full"];
const NODE_STYLES: readonly NodeStyle[] = ["colour", "simple"];

/** One labelled choice in the card: a name, the group, and what it means. */
function Setting({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  return (
    <div>
      <p id={id} className="text-foreground mb-2 text-sm font-medium">
        {label}
      </p>
      {children}
    </div>
  );
}

/**
 * How the console looks and moves for this person: the theme, the style, the
 * voice glow, Motion preference and how workflow steps are drawn, side by side.
 *
 * All four are kept in this browser rather than on the account, like the
 * theme always was, so each applies the moment it is picked and there is
 * nothing to save. Gated on `useMounted` for the reason the account menu's
 * Appearance submenu is: the stored values are unknown on the server, so
 * before hydration nothing is shown as checked.
 *
 * Under reduced motion the glow is not drawn at all, so its choice shows Off,
 * offers nothing to pick, and says why - while the stored style survives for
 * when motion comes back.
 */
export function AppearanceSettings() {
  const t = useTranslations("appearance");
  const tTheme = useTranslations("theme");
  const tGlow = useTranslations("voiceGlow");
  const mounted = useMounted();
  const { theme, setTheme, look, setLook } = useThemeStore();
  const resolved = useResolvedTheme();
  const { style, setStyle } = useVoiceGlowStore();
  const { motion, setMotion } = useMotionStore();
  const { style: nodeStyle, setStyle: setNodeStyle } = useWorkflowNodeStyleStore();
  const reduced = useReducedMotion();
  const glow: VoiceGlowStyle = reduced ? "off" : style;

  return (
    <div data-tour="settings-appearance">
      <SectionCard title={tTheme("appearance")} description={t("description")}>
        <div className="space-y-5">
          <Setting id="appearance-theme" label={t("theme")}>
            <ChoiceGroup
              labelledBy="appearance-theme"
              value={mounted ? theme : undefined}
              options={THEMES.map((value) => ({ value, label: tTheme(value) }))}
              onChange={setTheme}
            />
          </Setting>
          <Setting id="appearance-look" label={t("look")}>
            <LookPicker
              labelledBy="appearance-look"
              value={mounted ? look : undefined}
              dark={resolved === "dark"}
              onChange={setLook}
            />
            <p className="text-muted-foreground mt-1.5 text-xs">{t("lookHint")}</p>
          </Setting>
          <Setting id="appearance-voice-glow" label={tGlow("title")}>
            <ChoiceGroup
              labelledBy="appearance-voice-glow"
              value={mounted ? glow : undefined}
              options={GLOW_STYLES.map((value) => ({ value, label: tGlow(value) }))}
              onChange={setStyle}
              disabled={reduced}
            />
            <p className="text-muted-foreground mt-1.5 text-xs">
              {reduced ? tGlow("reducedMotion") : t("voiceGlowHint")}
            </p>
          </Setting>
          <Setting id="appearance-motion" label={t("motion")}>
            <ChoiceGroup
              labelledBy="appearance-motion"
              value={mounted ? motion : undefined}
              options={MOTIONS.map((value) => ({ value, label: t(value) }))}
              onChange={setMotion}
            />
            <p className="text-muted-foreground mt-1.5 text-xs">{t("motionHint")}</p>
          </Setting>
          <Setting id="appearance-workflow-nodes" label={t("workflowNodes")}>
            <ChoiceGroup
              labelledBy="appearance-workflow-nodes"
              value={mounted ? nodeStyle : undefined}
              options={NODE_STYLES.map((value) => ({ value, label: t(value) }))}
              onChange={setNodeStyle}
            />
            <p className="text-muted-foreground mt-1.5 text-xs">{t("workflowNodesHint")}</p>
          </Setting>
        </div>
      </SectionCard>
    </div>
  );
}
