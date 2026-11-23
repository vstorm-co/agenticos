"use client";

import {
  Building2,
  Users,
  ShieldCheck,
  SlidersHorizontal,
  Fingerprint,
  Globe2,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { AvatarFace } from "@/components/ui/avatar-face";
import { useStartVariant } from "./start-experience";
import experience from "./start-experience.module.css";
import { StartCompanions } from "./start-companions";
import styles from "./administration.module.css";

const STAGES = {
  identity: { icon: Building2, cast: ["nimbus", "sunny", "byte"] },
  team: { icon: Users, cast: ["mochi", "pebble", "sprig"] },
  deployment: { icon: ShieldCheck, cast: ["byte", "nimbus", "sunny"] },
  organization: { icon: SlidersHorizontal, cast: ["sprig", "mochi", "byte"] },
  profile: { icon: Fingerprint, cast: ["pebble", "sunny", "mochi"] },
  context: { icon: Globe2, cast: ["sunny", "byte", "nimbus"] },
} as const;

export function StartStageArtwork({ stage }: { stage: keyof typeof STAGES }) {
  const variant = useStartVariant();
  const names = useTranslations("start.experience");
  const t = useTranslations("start.administration");
  if (variant === "studio") return null;
  const { icon: Icon, cast } = STAGES[stage];
  const copy = stage === "context" ? "profile" : stage === "profile" ? "identityProfile" : stage;
  return (
    <aside
      className={styles.stageArtwork}
      data-start-artwork
      data-stage={stage}
      aria-label={t(`${copy}BenefitTitle`)}
    >
      {variant ? (
        <div className={experience.teammates} aria-hidden>
          <span>
            <span>
              <AvatarFace seed="agenticos" />
            </span>
            {names("agenticosName")}
          </span>
          <span>
            <span>
              <AvatarFace seed="architect" />
            </span>
            {names("architectName")}
          </span>
        </div>
      ) : (
        <div className={styles.stageDrawing} aria-hidden="true">
          <span className={styles.drawingOrbit} />
          <span className={styles.drawingCenter}>
            <Icon size={34} strokeWidth={1.4} />
          </span>
          <StartCompanions members={cast} />
        </div>
      )}
      <div className={styles.artworkCopy}>
        <h3>{t(`${copy}BenefitTitle`)}</h3>
        <p>{t(`${copy}BenefitBody`)}</p>
      </div>
      <p className={styles.artworkFootnote}>{t("changeLater")}</p>
    </aside>
  );
}
