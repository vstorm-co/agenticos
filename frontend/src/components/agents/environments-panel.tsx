"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAgentEnvironments } from "@/hooks";
import { useTranslations } from "next-intl";

/** The backend's slug rule, checked before the request leaves. */
const NAME_PATTERN = /^[a-z0-9][a-z0-9-]{0,63}$/;

/**
 * Which version of this agent answers under which name.
 *
 * Publish moves only the default; every other row is pinned until somebody
 * promotes a version onto it - from the version list below, where the thing
 * being promoted is visible. This panel owns the names: creating `dev` for a
 * bot to bind to, removing an environment a client no longer has.
 */
export function EnvironmentsPanel({ agentId, canManage }: { agentId: string; canManage: boolean }) {
  const t = useTranslations("agents");
  const { environments, isLoading, create, remove } = useAgentEnvironments(agentId);
  const [name, setName] = useState("");

  if (isLoading || environments.length === 0) {
    // An unpublished agent has no environments and nothing to manage; the
    // first publish mints `production` and the panel appears with it.
    return null;
  }

  const nameOk = NAME_PATTERN.test(name.trim());

  async function add() {
    await create.mutateAsync({ name: name.trim() });
    setName("");
  }

  return (
    <div className="space-y-3">
      <div className="space-y-2">
        {environments.map((environment) => (
          <div key={environment.id} className="flex items-center gap-3 rounded-md border p-3">
            <div className="min-w-0 flex-1">
              <p className="truncate font-mono text-sm">{environment.name}</p>
              <p className="text-muted-foreground text-xs">
                serves v{environment.version}
                {environment.is_default && " - what publish repoints"}
              </p>
            </div>
            {environment.is_default && <Badge variant="secondary">{t("default2")}</Badge>}
            {canManage && !environment.is_default && (
              <Button
                variant="ghost"
                size="sm"
                disabled={remove.isPending}
                aria-label={`Remove ${environment.name}`}
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
            Add
          </Button>
        </div>
      )}
    </div>
  );
}
