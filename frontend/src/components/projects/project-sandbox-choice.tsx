"use client";

import { useState } from "react";
import { useProject } from "@/hooks/use-projects";
import { useQuery } from "@tanstack/react-query";
import { Cloud, Folder, Server } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  Button,
  ConfirmDialog,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { usePermissions } from "@/hooks/use-permissions";
import { listSandboxConnections } from "@/lib/sandbox-connections-api";
import { qk } from "@/lib/query-keys";
import { Perm } from "@/types/permissions";
import type { Project } from "@/types/projects";

export function ProjectSandboxChoice({
  value,
  onChange,
  enabled,
  error,
  allowAutomatic = true,
}: {
  value: string;
  onChange: (value: string) => void;
  enabled: boolean;
  error?: string;
  allowAutomatic?: boolean;
}) {
  const t = useTranslations("projects.sandbox");
  const { can } = usePermissions();
  const {
    data = [],
    isLoading,
    isError,
  } = useQuery({
    queryKey: qk.sandboxConnections.list(),
    queryFn: listSandboxConnections,
    enabled: enabled && can(Perm.connectionsView),
    retry: false,
  });
  const connections = data.filter((connection) => connection.is_active);
  const preferred = connections.find((connection) => connection.is_default);
  return (
    <div data-tour="project-sandbox" className="space-y-2">
      <FormField label={t("label")} htmlFor="new-project-sandbox" error={error}>
        <Select value={value} onValueChange={onChange}>
          <SelectTrigger id="new-project-sandbox" disabled={isLoading && can(Perm.connectionsView)}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {allowAutomatic && (
              <SelectItem value="auto">
                <span className="flex items-center gap-2">
                  <Server className="h-4 w-4" aria-hidden />
                  {preferred ? t("automaticNamed", { name: preferred.name }) : t("automatic")}
                </span>
              </SelectItem>
            )}
            {connections.map((connection) => (
              <SelectItem key={connection.id} value={connection.id}>
                <span className="flex items-center gap-2">
                  {connection.kind === "daytona" ? (
                    <Cloud className="h-4 w-4" aria-hidden />
                  ) : (
                    <Server className="h-4 w-4" aria-hidden />
                  )}
                  {connection.name}
                </span>
              </SelectItem>
            ))}
            <SelectItem value="state">
              <span className="flex items-center gap-2">
                <Folder className="h-4 w-4" aria-hidden />
                {t("stored")}
              </span>
            </SelectItem>
          </SelectContent>
        </Select>
      </FormField>
      <p className="text-muted-foreground text-xs leading-relaxed">
        {value === "state" ? t("storedHint") : t("sharedHint")}
      </p>
      <ProjectSandboxExplanation />
      {isError && (
        <p role="alert" className="text-destructive text-xs">
          {t("failed")}
        </p>
      )}
    </div>
  );
}

export function ProjectSandboxSummary({ project }: { project: Project }) {
  const t = useTranslations("projects.sandbox");
  const { moveWorkspace } = useProject(project.id);
  const [changing, setChanging] = useState(false);
  const [target, setTarget] = useState(
    project.backend === "state" ? "state" : (project.sandbox_connection_id ?? ""),
  );
  const [confirm, setConfirm] = useState(false);
  const transfer = project.workspace_move;
  const moving = transfer?.status === "queued" || transfer?.status === "running";
  const stored = project.backend === "state";
  const Icon = stored ? Folder : Server;
  return (
    <Card data-tour="project-workspace">
      <CardHeader>
        <CardTitle>{t("label")}</CardTitle>
        <CardDescription>{t("sharedHint")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-start gap-3">
          <span className="bg-muted text-muted-foreground grid h-10 w-10 shrink-0 place-items-center rounded-xl">
            <Icon className="h-5 w-5" strokeWidth={1.6} aria-hidden />
          </span>
          <div className="min-w-0 space-y-1">
            <p className="truncate text-sm font-medium">
              {stored ? t("stored") : (project.sandbox_connection_name ?? t("configured"))}
            </p>
            <p className="text-muted-foreground text-xs leading-relaxed">
              {stored ? t("storedHint") : t("containerHint")}
            </p>
            {!stored && project.runtime && (
              <p className="text-muted-foreground font-mono text-xs">{project.runtime}</p>
            )}
          </div>
        </div>
        <ProjectSandboxExplanation />
        {moving && transfer && (
          <div role="status" className="bg-muted/60 space-y-1 rounded-xl p-3 text-sm">
            <p className="font-medium">{t("moving", { name: transfer.target_name })}</p>
            <p className="text-muted-foreground text-xs">
              {t("progress", { copied: transfer.copied_files, total: transfer.total_files })}
            </p>
            <p className="text-muted-foreground text-xs">{t("paused")}</p>
          </div>
        )}
        {(transfer?.status === "dead" || transfer?.status === "cancelled") && (
          <p role="alert" className="text-destructive text-sm">
            {t("moveFailed")}
          </p>
        )}
        {transfer?.status === "succeeded" && (
          <p role="status" className="text-muted-foreground text-sm">
            {t("moved")}
          </p>
        )}
        {project.can_edit && !moving && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setChanging(!changing)}
            aria-expanded={changing}
          >
            {t("change")}
          </Button>
        )}
        {changing && !moving && (
          <div className="space-y-3 border-t pt-4">
            <ProjectSandboxChoice
              value={target}
              onChange={setTarget}
              enabled
              allowAutomatic={false}
            />
            <p className="text-muted-foreground text-xs leading-relaxed">{t("transferHint")}</p>
            <Button
              variant="outline"
              disabled={
                !target ||
                moveWorkspace.isPending ||
                target === (stored ? "state" : project.sandbox_connection_id)
              }
              onClick={() => setConfirm(true)}
            >
              {t("move")}
            </Button>
          </div>
        )}
        <ConfirmDialog
          open={confirm}
          onOpenChange={setConfirm}
          title={t("move")}
          description={t("transferHint")}
          confirmLabel={t("move")}
          loading={moveWorkspace.isPending}
          onConfirm={async () => {
            try {
              await moveWorkspace.mutateAsync(target);
              setConfirm(false);
              setChanging(false);
            } catch {
              // The mutation reports the API error; keep the target and confirmation available.
            }
          }}
        />
      </CardContent>
    </Card>
  );
}

/** Explain the same storage / execution distinction as the Builder Sandbox tool. */
export function ProjectSandboxExplanation() {
  const t = useTranslations("projects.sandbox");
  return (
    <details className="text-muted-foreground text-xs leading-relaxed">
      <summary className="hover:text-foreground cursor-pointer py-1 font-medium">
        {t("howItWorks")}
      </summary>
      <dl className="bg-muted/40 mt-2 grid gap-3 rounded-xl p-3">
        {(["location", "sharing", "execution"] as const).map((topic) => (
          <div key={topic}>
            <dt className="text-foreground font-medium">{t(`${topic}Title`)}</dt>
            <dd className="mt-1">{t(`${topic}Help`)}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
