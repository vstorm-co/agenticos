"use client";
import { Building2, Users, ShieldCheck, SlidersHorizontal } from "lucide-react";
import { useTranslations } from "next-intl";
import { Face } from "@/components/desktop/blobby-pickers";
import { faceOf } from "@/lib/desktop/blobby-cast";
import styles from "./administration.module.css";

export function StartStageArtwork({
  stage,
}: {
  stage: "team" | "deployment" | "organization" | "profile" | "identity";
}) {
  const t = useTranslations("start.administration");
  const Icon = {
    identity: Building2,
    team: Users,
    deployment: Building2,
    organization: ShieldCheck,
    profile: SlidersHorizontal,
  }[stage];
  return (
    <aside className={styles.stageArtwork} aria-label={t(`${stage}BenefitTitle`)}>
      <div className={styles.stageDrawing} aria-hidden="true">
        <span className={styles.drawingOrbit} />
        <span className={styles.drawingCenter}>
          <Icon size={38} strokeWidth={1.4} />
        </span>
        <span className={styles.drawingFace}>
          <Face face={faceOf({ kind: "cast", id: "nimbus" })} size={56} />
        </span>
        <span className={styles.drawingSatellite}>
          <Users size={23} />
        </span>
      </div>
      <h3>{t(`${stage}BenefitTitle`)}</h3>
      <p>{t(`${stage}BenefitBody`)}</p>
      <p className={styles.artworkFootnote}>{t("changeLater")}</p>
    </aside>
  );
}
