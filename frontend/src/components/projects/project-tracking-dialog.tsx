"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useAgents } from "@/hooks/use-agents";
import { useProjectTrackingReview } from "@/hooks/use-project-tracking";
import type { ProjectTrackingCreate } from "@/lib/project-tracking-api";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_FORM, DIALOG_COLUMN } from "@/lib/dialog-sizes";
import type { Project } from "@/types/projects";
import { ErrorState } from "@/components/states/error-state";
import { AgentAvatar } from "@/components/agents/agent-avatar";
import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Spinner,
} from "@/components/ui";

export function ProjectTrackingDialog({
  project,
  pending,
  onCreate,
  onClose,
}: {
  project: Project;
  pending: boolean;
  onCreate: (data: ProjectTrackingCreate, onSuccess: () => void) => void;
  onClose: () => void;
}) {
  const t = useTranslations("projects.tracking");
  const errors = useTranslations("errors");
  const { agents, error: agentsError, isLoading, refetch } = useAgents();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [agentName, setAgentName] = useState(
    t("agentDefault", { name: project.name }).slice(0, 100),
  );
  const [tableName, setTableName] = useState(
    t("tableDefault", { name: project.name }).slice(0, 64),
  );
  const [interval, setInterval] = useState("86400");
  const [confirmedReview, setConfirmedReview] = useState<string | null>(null);
  const selected = agents.find(
    (agent) =>
      agent.id === selectedId &&
      agent.can_run &&
      agent.current_version_id !== null &&
      agent.status === "published" &&
      !agent.workflow_id,
  );
  const review = useProjectTrackingReview(
    project.id,
    selected?.id ?? null,
    selected?.current_version_id ?? null,
  );
  const current = review.data;
  const ready =
    !!selected &&
    !!current &&
    !review.isFetching &&
    !review.error &&
    current.unavailable_sources.length === 0 &&
    confirmedReview === current.review_token &&
    agentName.trim().length > 0 &&
    tableName.trim().length > 0 &&
    !agentsError;
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !pending) onClose();
      }}
    >
      <DialogContent className={`${DIALOG_FORM} ${DIALOG_COLUMN}`}>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto">
          <p className="text-muted-foreground text-sm">{t("audience")}</p>
          {isLoading ? (
            <Spinner />
          ) : agentsError ? (
            <ErrorState
              description={getErrorMessage(agentsError, errors)}
              cta={{ label: t("retry"), onClick: () => void refetch() }}
            />
          ) : (
            <FormField label={t("baseAgent")} htmlFor="tracking-base">
              <Select value={selectedId ?? ""} onValueChange={setSelectedId} disabled={pending}>
                <SelectTrigger id="tracking-base">
                  <SelectValue placeholder={t("chooseAgent")} />
                </SelectTrigger>
                <SelectContent>
                  {agents
                    .filter(
                      (agent) =>
                        agent.can_run &&
                        agent.current_version_id !== null &&
                        agent.status === "published" &&
                        !agent.workflow_id,
                    )
                    .map((agent) => (
                      <SelectItem key={agent.id} value={agent.id} textValue={agent.name}>
                        <span className="flex min-w-0 items-center gap-2">
                          <AgentAvatar
                            agentId={agent.id}
                            slug={agent.slug}
                            hasAvatar={agent.has_avatar}
                            colorSlot={agent.avatar_color}
                            size="sm"
                          />
                          <span className="truncate">{agent.name}</span>
                        </span>
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </FormField>
          )}
          <FormField label={t("agentName")} htmlFor="tracking-agent-name">
            <Input
              id="tracking-agent-name"
              value={agentName}
              onChange={(event) => setAgentName(event.target.value)}
              maxLength={100}
              disabled={pending}
            />
          </FormField>
          <FormField label={t("tableName")} htmlFor="tracking-table-name">
            <Input
              id="tracking-table-name"
              value={tableName}
              onChange={(event) => setTableName(event.target.value)}
              maxLength={64}
              disabled={pending}
            />
          </FormField>
          <FormField label={t("cadence")} htmlFor="tracking-cadence">
            <Select value={interval} onValueChange={setInterval} disabled={pending}>
              <SelectTrigger id="tracking-cadence">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="3600">{t("hourly")}</SelectItem>
                <SelectItem value="86400">{t("daily")}</SelectItem>
                <SelectItem value="604800">{t("weekly")}</SelectItem>
              </SelectContent>
            </Select>
          </FormField>
          <p className="text-muted-foreground text-sm">{t("scopeHint")}</p>
          {review.isFetching ? (
            <Spinner />
          ) : review.error ? (
            <ErrorState
              description={getErrorMessage(review.error, errors)}
              cta={{ label: t("retry"), onClick: () => void review.refetch() }}
            />
          ) : (
            current && (
              <section className="space-y-2 rounded-lg border p-3" aria-label={t("sources")}>
                <h3 className="text-sm font-medium">{t("sources")}</h3>
                <ul className="max-h-36 space-y-1 overflow-y-auto text-xs break-all">
                  {[...current.resources, ...current.accounts].map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
                <p className="text-muted-foreground text-xs">{t("tableRights")}</p>
                {current.unavailable_sources.length > 0 && (
                  <p role="status" className="text-sm">
                    {t("unavailable", { names: current.unavailable_sources.join(", ") })}
                  </p>
                )}
                <div className="flex items-start gap-2">
                  <Checkbox
                    id="tracking-confirm"
                    checked={confirmedReview === current.review_token}
                    disabled={pending || current.unavailable_sources.length > 0}
                    onCheckedChange={(checked) =>
                      setConfirmedReview(checked === true ? current.review_token : null)
                    }
                  />
                  <Label htmlFor="tracking-confirm">{t("confirm")}</Label>
                </div>
              </section>
            )
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={pending}>
            {t("cancel")}
          </Button>
          <Button
            disabled={!ready || pending}
            onClick={() => {
              if (ready && current && selected && selected.current_version_id !== null)
                onCreate(
                  {
                    base_agent_id: selected.id,
                    base_version_id: selected.current_version_id,
                    source_review_token: current.review_token,
                    publish_and_start: true,
                    agent_name: agentName.trim(),
                    table_name: tableName.trim(),
                    table_visibility: "private",
                    interval_seconds: Number(interval),
                  },
                  onClose,
                );
            }}
          >
            {pending && <Spinner />}
            {t("publish")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
