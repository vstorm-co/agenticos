"use client";

import { Skeleton } from "@/components/ui/skeleton";
import type { StartLoadingView } from "./start-skeleton";
import { StartWorkspacePreview } from "./start-workspace-preview";
import { StartStageArtwork } from "./start-stage-artwork";
import layout from "./administration.module.css";
import guided from "./guided-start.module.css";
import workbench from "./workbench.module.css";
import styles from "./start-skeleton.module.css";

function Lines() {
  return (
    <div className="space-y-3">
      <Skeleton className="h-3 w-full" />
      <Skeleton className="h-3 w-4/5" />
    </div>
  );
}
function Field({ tall = false }: { tall?: boolean }) {
  return (
    <div className="space-y-2">
      <Skeleton className="h-3 w-28" />
      <Skeleton className={tall ? "h-24 w-full" : "h-10 w-full"} />
    </div>
  );
}
function Actions() {
  return (
    <div className={guided.actions}>
      <Skeleton className="h-10 w-40" />
      <Skeleton className="ml-auto h-10 w-44" />
    </div>
  );
}

export function StartSkeletonBody({
  view,
  question,
  workspaceCount,
}: {
  view: StartLoadingView;
  question?: string | null;
  workspaceCount?: number;
}) {
  if (view === "workspace") return <WorkspaceSkeleton workspaceCount={workspaceCount} />;
  if (["identity", "profile", "context", "team"].includes(view))
    return <ProfileSkeleton view={view} />;
  if (view === "tasks") return <TasksSkeleton />;
  if (view === "welcome") return <WelcomeSkeleton />;
  return <QuestionSkeleton view={view} question={question} />;
}

function WorkspaceSkeleton({ workspaceCount }: { workspaceCount?: number }) {
  return (
    <div className={layout.workspaceChoice}>
      <div className={layout.workspaceStudio}>
        <div className={`${layout.createWorkspace} ${styles.workspaceCard}`}>
          <Skeleton className="mb-5 size-6" />
          <Skeleton className="mb-4 h-5 w-56 max-w-full" />
          <Lines />
          <div className="my-6 grid gap-3">
            {workspaceCount === 0 ? (
              <Field />
            ) : (
              Array.from({ length: Math.min(workspaceCount ?? 3, 6) }, (_, index) => (
                <div key={index} className={styles.workspaceRow}>
                  <Skeleton className="size-8 rounded-lg" />
                  <Skeleton className="h-4 w-1/2" />
                  <Skeleton className="ml-auto size-4" />
                </div>
              ))
            )}
          </div>
          <Skeleton className="mt-auto h-10 w-40" />
        </div>
        <StartWorkspacePreview name="" />
      </div>
      <Skeleton className="mt-2 h-4 w-64 max-w-full" />
    </div>
  );
}

function ProfileSkeleton({ view }: { view: StartLoadingView }) {
  const stage =
    view === "identity"
      ? "identity"
      : view === "context"
        ? "context"
        : view === "team"
          ? "team"
          : "profile";
  return (
    <div className={layout.stageStudio}>
      <div className={`${layout.profileCard} ${styles.profileCard}`}>
        {view === "profile" || view === "identity" ? (
          <>
            <Skeleton className="mx-auto size-24 rounded-full" />
            <Skeleton className="mx-auto h-9 w-48" />
            <div className="my-2 flex flex-wrap justify-center gap-2">
              {Array.from({ length: 11 }, (_, i) => (
                <Skeleton key={i} className="size-7 rounded-full" />
              ))}
            </div>
            <Field />
            {view === "profile" && <Field />}
          </>
        ) : (
          <>
            <Skeleton className="h-5 w-2/3" />
            <Lines />
            <Field />
            <Field tall />
            <Field />
          </>
        )}
        <div className="mt-auto flex flex-wrap items-center gap-3">
          <Skeleton className="h-10 w-44" />
          <Skeleton className="h-10 w-32" />
        </div>
      </div>
      <StartStageArtwork stage={stage} />
    </div>
  );
}

function TasksSkeleton() {
  return (
    <div className={workbench.workbench}>
      <div className="space-y-3">
        <Skeleton className="mb-5 h-4 w-40" />
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex min-h-24 gap-3 rounded-xl p-3">
            <Skeleton className="size-5 shrink-0" />
            <div className="flex-1 space-y-3">
              <Skeleton className="h-4 w-4/5" />
              <Lines />
            </div>
          </div>
        ))}
      </div>
      <div className={styles.taskCanvas}>
        <div className="mb-8 flex gap-4">
          <Skeleton className="h-8 w-32" />
          <Skeleton className="h-8 w-28" />
        </div>
        <Skeleton className="mb-6 h-7 w-3/4" />
        <Field tall />
        <div className="mt-8 space-y-6">
          <Lines />
          <Lines />
        </div>
        <Actions />
      </div>
    </div>
  );
}

function WelcomeSkeleton() {
  return (
    <div className={guided.journey}>
      <div className={`${guided.question} ${styles.welcome}`}>
        <Skeleton className="h-32 w-full rounded-3xl" />
        <Skeleton className="mx-auto mt-8 h-10 w-4/5" />
        <div className="mx-auto my-6 w-4/5">
          <Lines />
        </div>
        <Skeleton className="mx-auto h-10 w-40" />
      </div>
    </div>
  );
}

function QuestionAnswers({ view, question }: { view: StartLoadingView; question?: string | null }) {
  if (view === "budget")
    return (
      <div className={guided.budgetLayout}>
        <Skeleton className="h-36 w-full rounded-3xl" />
        <div className="relative mt-6">
          <Skeleton className="h-3 w-full rounded-full" />
          <Skeleton className="absolute -top-1 left-1/5 size-5 rounded-full" />
        </div>
        <div className="my-6 flex flex-wrap justify-center gap-3">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-10 w-24" />
          ))}
        </div>
        <Lines />
      </div>
    );
  if (view === "organization")
    return (
      <>
        <div className={guided.preview}>
          <Skeleton className="mb-4 h-4 w-40" />
          <Lines />
        </div>
        <Skeleton className="my-6 h-3 w-4/5" />
        <div className={guided.stack}>
          {[0, 1, 2].map((i) => (
            <div key={i} className={guided.details}>
              <Skeleton className="h-4 w-2/3" />
            </div>
          ))}
        </div>
      </>
    );
  if (question === "announcement")
    return (
      <div className={guided.announcementLayout}>
        <div className="space-y-4">
          <Field tall />
          <div className="flex gap-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-9 w-24" />
            ))}
          </div>
        </div>
        <Skeleton className="min-h-40 w-full rounded-2xl" />
      </div>
    );
  if (question === "extras")
    return (
      <div className={guided.extras}>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className={guided.extra}>
            <div className={guided.extraHeader}>
              <Skeleton className="size-9 shrink-0 rounded-xl" />
              <Skeleton className="h-4 w-2/3" />
            </div>
            <div className="mt-4">
              <Lines />
            </div>
            <Skeleton className="mt-4 h-4 w-48 max-w-full" />
          </div>
        ))}
      </div>
    );
  return (
    <>
      <div className={guided.choices}>
        {Array.from({ length: question === "destination" ? 2 : 3 }, (_, i) => (
          <div key={i} className={guided.choice}>
            <Skeleton className="size-10 rounded-xl" />
            <Skeleton className="h-4 w-3/4" />
            <Lines />
          </div>
        ))}
      </div>
      {question === "destination" && <Skeleton className="mt-5 h-20 w-full rounded-2xl" />}
    </>
  );
}
function QuestionSkeleton({
  view,
  question,
}: {
  view: StartLoadingView;
  question?: string | null;
}) {
  return (
    <div className={guided.journey}>
      <div className={`${guided.question} ${styles.still}`}>
        <div className={guided.questionMeta}>
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-3 w-36" />
        </div>
        <Skeleton className="h-14 w-4/5 sm:h-9" />
        <div className={guided.answer}>
          <QuestionAnswers view={view} question={question} />
        </div>
        <Actions />
      </div>
    </div>
  );
}
