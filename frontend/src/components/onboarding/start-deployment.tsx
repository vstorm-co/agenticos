"use client";

import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import { rememberStartQuestion } from "./start-position";
import {
  useDeploymentSettings,
  type DeploymentSettingsPatch,
} from "@/hooks/use-deployment-settings";
import { ErrorState } from "@/components/states";
import type { Organization } from "@/types";
import { StartSkeleton } from "./start-skeleton";
import { StartQuestion } from "./start-question";
import {
  DeploymentAccess,
  DeploymentDestination,
  DeploymentAnnouncement,
  DeploymentExtras,
} from "./start-deployment-answers";

const QUESTIONS = ["access", "destination", "announcement", "extras"] as const;

/** First-run decisions only. Operational credentials stay in the administrator's panel. */
export function StartDeployment({
  org,
  onContinue,
  active = true,
}: {
  org: Organization;
  onContinue: () => void;
  active?: boolean;
}) {
  const t = useTranslations("start.guided");
  const { settings, isLoading, error, refetch, save } = useDeploymentSettings();
  const router = useRouter();
  const search = useSearchParams();
  const requested =
    search.get("workspace") === org.id && search.get("start-step") === "admin.deployment"
      ? QUESTIONS.find((item) => item === search.get("question"))
      : undefined;
  const [question, setQuestion] = useState<(typeof QUESTIONS)[number]>(requested ?? "access");
  const index = QUESTIONS.indexOf(question);
  useEffect(() => {
    if (active) rememberStartQuestion("admin.deployment", org.id, question);
  }, [active, question, org.id]);
  const [edits, setEdits] = useState<DeploymentSettingsPatch>({});
  const [failed, setFailed] = useState(false);
  if (isLoading) return <StartSkeleton view="deployment" question={question} fullPage={false} />;
  if (error || !settings)
    return (
      <ErrorState
        title={t("loadFailed")}
        cta={{ label: t("retry"), onClick: () => void refetch() }}
      />
    );
  const changes: DeploymentSettingsPatch = {
    ...(question === "announcement" && !settings.announcement
      ? { announcement: t("announcementPlaceholder") }
      : {}),
    ...edits,
  };
  const draft = { ...settings, ...changes };
  const set = (patch: DeploymentSettingsPatch) => {
    setFailed(false);
    setEdits((previous) => ({ ...previous, ...patch }));
  };
  const next = () => {
    setEdits({});
    setFailed(false);
    const following = QUESTIONS[index + 1];
    if (following) setQuestion(following);
    else onContinue();
  };
  const submit = async () => {
    if (!Object.keys(changes).length) {
      next();
      return;
    }
    try {
      await save.mutateAsync(changes);
    } catch {
      setFailed(true);
      return;
    }
    router.refresh();
    next();
  };
  return (
    <StartQuestion
      index={index}
      total={QUESTIONS.length}
      title={t(`${question}Title`)}
      message={t(`${question}Guide`)}
      pending={save.isPending}
      onBack={
        index > 0
          ? () => {
              setEdits({});
              setFailed(false);
              const previous = QUESTIONS[index - 1];
              if (previous) setQuestion(previous);
            }
          : undefined
      }
      onContinue={() => void submit()}
      onSkip={index < QUESTIONS.length - 1 ? next : undefined}
    >
      {question === "access" && (
        <DeploymentAccess
          value={draft.signup_mode}
          pending={save.isPending}
          onChange={(mode) => set({ signup_mode: mode })}
        />
      )}
      {question === "destination" && (
        <DeploymentDestination
          org={org}
          defaultOrg={draft.default_organization_id}
          role={draft.default_organization_role}
          personal={draft.personal_organizations}
          pending={save.isPending}
          onChange={set}
        />
      )}
      {question === "announcement" && (
        <DeploymentAnnouncement
          value={draft.announcement}
          level={draft.announcement_level}
          pending={save.isPending}
          onChange={set}
        />
      )}
      {question === "extras" && <DeploymentExtras maintenance={settings.maintenance_mode} />}
      {failed && (
        <p role="alert" className="text-destructive-ink mt-4 text-sm">
          {t("saveFailed")}
        </p>
      )}
    </StartQuestion>
  );
}
