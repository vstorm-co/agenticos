"use client";

import { useState } from "react";
import { CalendarClock, Plug, Webhook } from "lucide-react";
import { useTranslations } from "next-intl";

import { LoadingState } from "@/components/states";
import { Button } from "@/components/ui";
import { useWorkflowExposures } from "@/hooks";
import { usePublicConfig } from "@/components/public-config/public-config-provider";
import type {
  ExposureAdapter,
  WorkflowDetail,
  WorkflowExposureCreated,
  WorkflowExposureRead,
} from "@/lib/workflows/types";

import { CopyableValue } from "./copyable-value";
import { ExposureDialog } from "./exposure-dialog";
import { ExposureRow } from "./exposure-row";
import { WebhookSecretDialog } from "./webhook-secret-dialog";

type Editing = { adapter: ExposureAdapter; exposure?: WorkflowExposureRead } | null;

/**
 * Every way in to one workflow, in the editor's Triggers sheet.
 *
 * Two kinds of door. A caller who is present - the HTTP API, a WebSocket, the
 * chat - needs nothing set up: anyone who may run the workflow can start it,
 * as themselves, so the panel only shows how. A door nobody is standing at - a
 * signed webhook, a schedule - is a row here, pinned to one published version
 * and run as the member who made it. Those need a version to pin, so a
 * workflow never published offers none yet.
 */
export function ExposuresPanel({
  workflow,
  canEdit,
}: {
  workflow: WorkflowDetail;
  canEdit: boolean;
}) {
  const t = useTranslations("pages.workflows");
  const { apiUrl } = usePublicConfig();
  const { exposures, isLoading, create, update, remove, rotate } = useWorkflowExposures(
    workflow.id,
  );
  const [editing, setEditing] = useState<Editing>(null);
  const [revealed, setRevealed] = useState<WorkflowExposureCreated | null>(null);
  const published = workflow.current_version_id !== null;
  const busy = create.isPending || update.isPending || remove.isPending || rotate.isPending;

  const reveal = (created: WorkflowExposureCreated) => {
    if (created.reveal_secret && created.webhook_url) setRevealed(created);
  };

  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <Plug aria-hidden="true" className="text-muted-foreground size-4" />
          <h3 className="text-sm font-medium">{t("exposureCallTitle")}</h3>
        </div>
        <p className="text-muted-foreground text-xs">{t("exposureCallDescription")}</p>
        <CopyableValue
          id="workflow-api-url"
          label={t("exposureApiLabel")}
          value={`POST ${apiUrl}/api/v1/workflow-runs`}
        />
        <CopyableValue
          id="workflow-api-body"
          label={t("exposureApiBody")}
          value={JSON.stringify({ workflow_id: workflow.id, input: {} })}
        />
        <p className="text-muted-foreground text-xs">{t("exposureSocketNote")}</p>
      </section>

      <section className="space-y-3">
        <div>
          <h3 className="text-sm font-medium">{t("exposureUnattendedTitle")}</h3>
          <p className="text-muted-foreground text-xs">{t("exposureUnattendedDescription")}</p>
        </div>
        {isLoading ? (
          <LoadingState variant="skeleton-panel" rows={2} />
        ) : exposures.length === 0 ? (
          <p className="text-muted-foreground rounded-lg border border-dashed p-4 text-center text-sm">
            {published ? t("exposureEmpty") : t("exposureNeedsPublish")}
          </p>
        ) : (
          <ul className="space-y-2">
            {exposures.map((exposure) => (
              <ExposureRow
                key={exposure.id}
                exposure={exposure}
                currentVersionId={workflow.current_version_id}
                canEdit={canEdit}
                busy={busy}
                onEdit={() => setEditing({ adapter: exposure.adapter, exposure })}
                onSetActive={(active) =>
                  update.mutate({ id: exposure.id, body: { is_active: active } })
                }
                onRepin={() =>
                  update.mutate({ id: exposure.id, body: { pin_current_version: true } })
                }
                onRotate={() => rotate.mutate(exposure.id, { onSuccess: reveal })}
                onDelete={() => remove.mutate(exposure.id)}
              />
            ))}
          </ul>
        )}
        {canEdit && published && (
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => setEditing({ adapter: "webhook" })}>
              <Webhook className="h-4 w-4" />
              {t("exposureNewWebhook")}
            </Button>
            <Button variant="outline" size="sm" onClick={() => setEditing({ adapter: "schedule" })}>
              <CalendarClock className="h-4 w-4" />
              {t("exposureNewSchedule")}
            </Button>
          </div>
        )}
      </section>

      {editing && (
        <ExposureDialog
          adapter={editing.adapter}
          exposure={editing.exposure}
          busy={busy}
          onOpenChange={(open) => !open && setEditing(null)}
          onSubmit={(body) => {
            const done = () => setEditing(null);
            if (editing.exposure) {
              const { adapter: _adapter, ...changes } = body;
              update.mutate({ id: editing.exposure.id, body: changes }, { onSuccess: done });
            } else {
              create.mutate(body, {
                onSuccess: (created) => {
                  done();
                  reveal(created);
                },
              });
            }
          }}
        />
      )}
      {revealed?.reveal_secret && revealed.webhook_url && (
        <WebhookSecretDialog
          url={revealed.webhook_url}
          secret={revealed.reveal_secret}
          onClose={() => setRevealed(null)}
        />
      )}
    </div>
  );
}
