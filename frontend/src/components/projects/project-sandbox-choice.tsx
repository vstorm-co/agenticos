"use client";

import { useQuery } from "@tanstack/react-query";
import { Cloud, Folder, Server } from "lucide-react";
import { useTranslations } from "next-intl";
import {
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
}: {
  value: string;
  onChange: (value: string) => void;
  enabled: boolean;
  error?: string;
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
            <SelectItem value="auto">
              <span className="flex items-center gap-2">
                <Server className="h-4 w-4" aria-hidden />
                {preferred ? t("automaticNamed", { name: preferred.name }) : t("automatic")}
              </span>
            </SelectItem>
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
      {isError && (
        <p role="alert" className="text-destructive text-xs">
          {t("failed")}
        </p>
      )}
    </div>
  );
}

export function ProjectSandboxSummary({
  project,
}: {
  project: Pick<Project, "backend" | "runtime" | "sandbox_connection_name">;
}) {
  const t = useTranslations("projects.sandbox");
  const stored = project.backend === "state";
  const Icon = stored ? Folder : Server;
  return (
    <Card data-tour="project-workspace">
      <CardHeader>
        <CardTitle>{t("label")}</CardTitle>
        <CardDescription>{t("sharedHint")}</CardDescription>
      </CardHeader>
      <CardContent>
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
      </CardContent>
    </Card>
  );
}
