"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { ArrowLeft, ExternalLink, FlaskConical } from "lucide-react";
import { Button } from "@/components/ui";
import { LoadingState, ErrorState } from "@/components/states";
import { FormSurface } from "@/components/workflows/form-surface";
import { PublicForm } from "@/components/workflows/public-form";
import { formPageOf } from "@/components/workflows/form-page-config";
import { useWorkflow, useWorkflowRuns } from "@/hooks";
import { FORM_TRIGGER } from "@/lib/workflows/triggers";

/** Authenticated, saved-draft form test. It never creates a public draft link. */
export default function DraftFormPreview({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const query = useSearchParams();
  const t = useTranslations("workflows.formPage");
  const { workflow, isLoading, error } = useWorkflow(id);
  const { start } = useWorkflowRuns(id);
  const [runId, setRunId] = useState<string | null>(null);
  const graph = workflow?.draft_graph;
  const node = graph?.nodes.find(
    (candidate) =>
      candidate.definition_id === FORM_TRIGGER &&
      (query.get("entry") === null || candidate.id === query.get("entry")),
  );
  if (isLoading) return <LoadingState />;
  if (error || !node) return <ErrorState title={t("unavailable")} />;
  const page = formPageOf(node.config, {
    title: t("title.placeholder"),
    submit: t("submit_label.placeholder"),
  });
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button asChild variant="ghost">
          <Link href={`/workflows/${id}`}>
            <ArrowLeft className="size-4" />
            {t("back")}
          </Link>
        </Button>
        <span className="text-muted-foreground inline-flex items-center gap-2 text-sm">
          <FlaskConical className="size-4" />
          {t("testForm")}
        </span>
      </div>
      <p className="text-muted-foreground mx-auto max-w-xl text-center text-sm">{t("testHint")}</p>
      <FormSurface appearance={page.appearance}>
        {workflow?.can_edit === true ? (
          <PublicForm
            key={`${node.id}:${workflow?.draft_revision}`}
            page={page}
            onSubmitValues={async (input) => {
              const run = await start.mutateAsync({
                workflow_id: id,
                mode: "test",
                entry_node_id: node.id,
                input,
              });
              setRunId(run.id);
              return t("testStarted");
            }}
          />
        ) : (
          <PublicForm page={page} preview />
        )}
        {runId && (
          <Button asChild variant="outline" className="mt-6 w-full">
            <Link href={`/workflows/${id}/runs/${runId}`}>
              <ExternalLink className="size-4" />
              {t("openRun")}
            </Link>
          </Button>
        )}
      </FormSurface>
    </div>
  );
}
