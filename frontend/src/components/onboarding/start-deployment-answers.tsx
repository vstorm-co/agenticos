"use client";

import Link from "next/link";
import {
  Globe2,
  Mail,
  LockKeyhole,
  Building2,
  Smartphone,
  Mic,
  ShieldCheck,
  Palette,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { FormField, Switch, Textarea, Button } from "@/components/ui";
import type {
  DefaultOrganizationRole,
  DeploymentSettingsPatch,
} from "@/hooks/use-deployment-settings";
import type { NoticeLevel, SignupMode } from "@/lib/branding";
import type { Organization } from "@/types";
import styles from "./guided-start.module.css";

export function DeploymentAccess({
  value,
  pending,
  onChange,
}: {
  value: SignupMode;
  pending: boolean;
  onChange: (mode: SignupMode) => void;
}) {
  const t = useTranslations("start.guided");
  return (
    <>
      <div className={styles.choices}>
        {(
          [
            ["invite_only", Mail, "invite"],
            ["open", Globe2, "open"],
            ["closed", LockKeyhole, "closed"],
          ] as const
        ).map(([mode, Icon, label]) => (
          <button
            key={mode}
            type="button"
            className={styles.choice}
            aria-pressed={value === mode}
            disabled={pending}
            onClick={() => onChange(mode)}
          >
            <Icon size={24} aria-hidden />
            <strong>{t(`${label}Title`)}</strong>
            <span>{t(`${label}Body`)}</span>
          </button>
        ))}
      </div>
      <div className="mt-5 space-y-2">
        <p className={styles.hint}>{t("domainsPreserved")}</p>
        <Link
          href="/admin/settings?section=access"
          target="_blank"
          rel="noopener noreferrer"
          className="text-muted-foreground text-xs underline underline-offset-4"
        >
          {t("advancedAccess")}
        </Link>
      </div>
    </>
  );
}

export function DeploymentDestination({
  org,
  defaultOrg,
  role,
  personal,
  pending,
  onChange,
}: {
  org: Organization;
  defaultOrg: string | null;
  role: DefaultOrganizationRole;
  personal: boolean;
  pending: boolean;
  onChange: (
    patch: Pick<DeploymentSettingsPatch, "default_organization_id" | "personal_organizations">,
  ) => void;
}) {
  const t = useTranslations("start.guided");
  return (
    <div className={styles.stack}>
      <button
        type="button"
        className={styles.choice}
        aria-pressed={defaultOrg === org.id}
        disabled={pending}
        onClick={() => onChange({ default_organization_id: org.id })}
      >
        <Building2 size={26} aria-hidden />
        <strong>{org.name}</strong>
        <span>{t("destinationBody", { role })}</span>
      </button>
      <p className={styles.hint}>
        {defaultOrg && defaultOrg !== org.id ? t("otherDestination") : t("destinationHint")}
      </p>
      <label className={styles.switchRow}>
        <span>
          <strong>{t("personalTitle")}</strong>
          <p>{t("personalBody")}</p>
        </span>
        <Switch
          checked={personal}
          disabled={pending}
          onCheckedChange={(value) => onChange({ personal_organizations: value })}
          aria-label={t("personalTitle")}
        />
      </label>
    </div>
  );
}

export function DeploymentAnnouncement({
  value,
  level,
  pending,
  onChange,
}: {
  value: string | null;
  level: NoticeLevel;
  pending: boolean;
  onChange: (patch: Pick<DeploymentSettingsPatch, "announcement" | "announcement_level">) => void;
}) {
  const t = useTranslations("start.guided");
  return (
    <div className={styles.announcementLayout}>
      <div>
        <FormField label={t("welcomeMessage")} htmlFor="start-announcement">
          <Textarea
            id="start-announcement"
            rows={3}
            maxLength={4000}
            value={value ?? ""}
            disabled={pending}
            onChange={(event) => onChange({ announcement: event.target.value || null })}
          />
        </FormField>
        <div className={styles.presets}>
          {(["info", "warning", "critical"] as const).map((option) => (
            <Button
              key={option}
              variant={level === option ? "secondary" : "outline"}
              aria-pressed={level === option}
              disabled={pending}
              onClick={() => onChange({ announcement_level: option })}
            >
              {t(option)}
            </Button>
          ))}
        </div>
      </div>
      <div
        className={styles.preview}
        role="region"
        aria-label={t("livePreview")}
        data-level={level}
      >
        <strong>{t("livePreview")}</strong>
        <p>{value || t("announcementEmpty")}</p>
      </div>
    </div>
  );
}

export function DeploymentExtras({ maintenance }: { maintenance: boolean }) {
  const t = useTranslations("start.guided");
  return (
    <div className={styles.extras}>
      {(
        [
          [Palette, "branding", "identity"],
          [Mic, "voice", "services"],
          [Smartphone, "mobile", "services"],
          [ShieldCheck, "maintenance", "operations"],
        ] as const
      ).map(([Icon, name, section]) => (
        <article className={styles.extra} key={name}>
          <div className={styles.extraHeader}>
            <Icon aria-hidden />
            <h3>{t(`${name}Title`)}</h3>
          </div>
          <p>{t(`${name}Body`)}</p>
          <Link
            href={`/admin/settings?section=${section}`}
            target="_blank"
            rel="noopener noreferrer"
          >
            {t("openSettings")}
          </Link>
        </article>
      ))}
      {maintenance && (
        <p role="status" className={styles.hint}>
          {t("maintenanceActive")}
        </p>
      )}
    </div>
  );
}
