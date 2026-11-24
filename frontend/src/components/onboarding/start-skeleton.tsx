"use client";

import { useTranslations } from "next-intl";
import { Skeleton } from "@/components/ui/skeleton";
import { BrandMark } from "@/components/branding/brand-mark";
import { useBranding } from "@/components/branding/branding-provider";
import { StartSkeletonBody } from "./start-skeleton-body";
import layout from "./administration.module.css";
import guided from "./guided-start.module.css";
import styles from "./start-skeleton.module.css";

export type StartLoadingView =
  | "workspace"
  | "identity"
  | "profile"
  | "context"
  | "team"
  | "deployment"
  | "budget"
  | "organization"
  | "tasks"
  | "welcome";

/** Resume metadata selects a placeholder only; it grants no access to a step. */
export function startLoadingView(step: string | null, question: string | null): StartLoadingView {
  if (step === "admin.organization") return question === "advanced" ? "organization" : "budget";
  if (step === "admin.deployment") return "deployment";
  if (step === "admin.identity") return "identity";
  if (step === "admin.team") return "team";
  if (step === "admin.profile" || step === "member.profile") return "profile";
  if (step === "admin.context" || step === "member.context") return "context";
  if (step === "admin.task" || step === "member.task") return "tasks";
  if (step === "member.welcome") return "welcome";
  return "workspace";
}

export function StartSkeleton({
  view = "workspace",
  fullPage = true,
  question,
  workspaceCount,
  steps = 8,
}: {
  view?: StartLoadingView;
  fullPage?: boolean;
  question?: string | null;
  workspaceCount?: number;
  steps?: number;
}) {
  const t = useTranslations("states");
  const { appName } = useBranding();
  const focused = ["budget", "deployment", "organization"].includes(view);
  const body = (
    <>
      {fullPage && !focused && view !== "welcome" && (
        <div className={styles.heading}>
          <Skeleton className="h-16 w-3/4 max-w-2xl sm:h-10" />
          <Skeleton className="mt-4 h-4 w-full max-w-3xl" />
          <Skeleton
            className={`mt-2 h-4 w-2/3 max-w-xl ${view === "workspace" ? "" : "sm:hidden"}`}
          />
        </div>
      )}
      {(fullPage || focused) && (
        <div className={`${guided.guide} ${focused || view === "welcome" ? guided.journey : ""}`}>
          <Skeleton className={`${guided.face} shrink-0`} />
          <div className="min-w-0 flex-1 space-y-3 py-1">
            <Skeleton className="h-3 w-36" />
            <Skeleton className="h-3 w-full max-w-2xl" />
            <Skeleton className="h-3 w-4/5 max-w-xl" />
            <Skeleton className="h-3 w-3/5 sm:hidden" />
          </div>
        </div>
      )}
      <StartSkeletonBody view={view} question={question} workspaceCount={workspaceCount} />
    </>
  );
  return (
    <div
      role="status"
      aria-label={t("loading")}
      aria-busy="true"
      data-onboarding-skeleton={view}
      className={fullPage ? layout.shell : undefined}
    >
      <div
        aria-hidden="true"
        className={`${fullPage ? layout.frame : ""} ${styles.decorative}`}
        data-focused={focused}
      >
        {fullPage && (
          <>
            <div className={layout.topbar}>
              <div className={layout.brand}>
                <BrandMark size={28} />
                {appName}
              </div>
              <div className={layout.topActions}>
                <Skeleton className="size-8 rounded-full" />
                <Skeleton className="h-4 w-24" />
              </div>
            </div>
            <div className={layout.wizardHeader}>
              <div className={layout.wizardMeta}>
                <Skeleton className="h-3 w-48" />
                <Skeleton className="h-3 w-20" />
              </div>
              <div className={layout.progress}>
                {Array.from({ length: steps }, (_, index) => (
                  <Skeleton key={index} className="h-1 flex-1 rounded-full" />
                ))}
              </div>
            </div>
          </>
        )}
        {body}
      </div>
    </div>
  );
}
