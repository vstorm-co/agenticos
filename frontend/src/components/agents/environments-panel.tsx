"use client";

import { useState } from "react";
import { Check, Pencil, Plus, Trash2, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAgentEnvironments, useAgentVersions } from "@/hooks";
import { VERSION_HISTORY_LIMIT } from "@/lib/agent-spec";
import type { AgentEnvironment, AgentVersion } from "@/types/agents";
import { useTranslations } from "next-intl";

/** The backend's slug rule, checked before the request leaves. */
const NAME_PATTERN = /^[a-z0-9][a-z0-9-]{0,63}$/;

/**
 * The environment's own version control - "dev should serve v3", answered on
 * the row that states what dev serves. The same promote as "Promote to…" on a
 * version row, approached from the other end.
 *
 * A pinned version that is gone from the history still has to render as
 * something: a disabled item carrying the stored number keeps the trigger
 * legible instead of empty, and says why the agent is not answering. Absent
 * is not gone, though - an unread history and one truncated at the backend's
 * fifty carry the number without the verdict, the same reading `pinStatus`
 * settled on.
 */
function VersionPin({
  environment,
  versions,
  onPromote,
  promoting,
}: {
  environment: AgentEnvironment;
  versions: AgentVersion[];
  onPromote: (versionId: string) => void;
  promoting: boolean;
}) {
  const t = useTranslations("agents");
  const pinListed = versions.some((version) => version.id === environment.version_id);
  const pinGone = !pinListed && versions.length > 0 && versions.length < VERSION_HISTORY_LIMIT;
  return (
    <Select value={environment.version_id} disabled={promoting} onValueChange={onPromote}>
      <SelectTrigger className="w-32" aria-label={t("pinVersionFor", { name: environment.name })}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {!pinListed && (
          <SelectItem value={environment.version_id} disabled>
            {pinGone ? (
              t("removedVersion", { version: environment.version })
            ) : (
              <>v{environment.version}</>
            )}
          </SelectItem>
        )}
        {versions.map((version) => (
          <SelectItem key={version.id} value={version.id}>
            v{version.version}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/**
 * Which version of this agent answers under which name.
 *
 * Publish moves only the default; every other row is pinned until somebody
 * promotes a version onto it - from its own row's version control here, or
 * from the version list below, where the thing being promoted is visible.
 * This panel also owns the names: creating `dev` for a bot to bind to,
 * renaming it, removing an environment a client no longer has. The default
 * keeps its name - it is part of the publish contract.
 */
export function EnvironmentsPanel({ agentId, canManage }: { agentId: string; canManage: boolean }) {
  const t = useTranslations("agents");
  const tc = useTranslations("common");
  const { environments, isLoading, create, promote, rename, remove } =
    useAgentEnvironments(agentId);
  const { versions } = useAgentVersions(agentId);
  const [name, setName] = useState("");
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);

  if (isLoading || environments.length === 0) {
    // An unpublished agent has no environments and nothing to manage; the
    // first publish mints `production` and the panel appears with it.
    return null;
  }

  const nameOk = NAME_PATTERN.test(name.trim());
  const renameOk = renaming !== null && NAME_PATTERN.test(renaming.name.trim());

  async function add() {
    await create.mutateAsync({ name: name.trim() });
    setName("");
  }

  async function saveRename(environment: AgentEnvironment, next: string) {
    // An unchanged name is a dismissal, not a request: sending it would write
    // the row and mint an `agent.environment_renamed` audit entry for nothing.
    const trimmed = next.trim();
    if (trimmed !== environment.name) {
      await rename.mutateAsync({ environmentId: environment.id, name: trimmed });
    }
    setRenaming(null);
  }

  return (
    <div className="space-y-3">
      <div className="space-y-2">
        {environments.map((environment) => (
          <div key={environment.id} className="flex items-center gap-3 rounded-md border p-3">
            <div className="min-w-0 flex-1">
              {renaming?.id === environment.id ? (
                <div className="flex items-center gap-2">
                  <Input
                    value={renaming.name}
                    aria-label={tc("renameNamed", { name: environment.name })}
                    maxLength={64}
                    ref={(node) => node?.focus()}
                    className="h-8 font-mono text-sm"
                    onChange={(event) =>
                      setRenaming({ id: environment.id, name: event.target.value })
                    }
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && renameOk) {
                        void saveRename(environment, renaming.name);
                      }
                      if (event.key === "Escape") setRenaming(null);
                    }}
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={tc("save")}
                    disabled={!renameOk || rename.isPending}
                    onClick={() => void saveRename(environment, renaming.name)}
                  >
                    <Check className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={tc("cancel")}
                    onClick={() => setRenaming(null)}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              ) : (
                <p className="truncate font-mono text-sm">{environment.name}</p>
              )}
              <p className="text-muted-foreground text-xs">
                {t("servesVersion", {
                  version: environment.version,
                  isDefault: String(environment.is_default),
                })}
              </p>
            </div>
            {canManage && (
              <VersionPin
                environment={environment}
                versions={versions}
                promoting={promote.isPending}
                onPromote={(versionId) =>
                  promote.mutate({ environmentId: environment.id, versionId })
                }
              />
            )}
            {environment.is_default && <Badge variant="secondary">{t("default2")}</Badge>}
            {canManage && !environment.is_default && renaming?.id !== environment.id && (
              <Button
                variant="ghost"
                size="sm"
                disabled={rename.isPending}
                aria-label={tc("renameNamed", { name: environment.name })}
                onClick={() => setRenaming({ id: environment.id, name: environment.name })}
              >
                <Pencil className="h-4 w-4" />
              </Button>
            )}
            {canManage && !environment.is_default && (
              <Button
                variant="ghost"
                size="sm"
                disabled={remove.isPending}
                aria-label={tc("removeNamed", { name: environment.name })}
                onClick={() => remove.mutate(environment.id)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            )}
          </div>
        ))}
      </div>

      {canManage && (
        <div className="flex items-end gap-3">
          <div className="flex-1 space-y-1">
            <Label htmlFor="env-name">{t("newEnvironment")}</Label>
            <Input
              id="env-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t("devStagingClientS")}
              maxLength={64}
            />
          </div>
          <Button onClick={add} disabled={!nameOk || create.isPending}>
            <Plus className="h-4 w-4" />
            {t("add")}
          </Button>
        </div>
      )}
    </div>
  );
}
