"use client";

import Link from "next/link";
import { Network, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { DelegationModeField } from "@/components/agents/delegation-mode-field";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import type { DelegationMode, ExternalAgentRef } from "@/types/agents";
import type { ExternalAgent } from "@/types/external-agents";

interface RemoteDelegateListProps {
  /** The organization's registered remote agents. */
  registered: readonly ExternalAgent[];
  references: ExternalAgentRef[];
  onChange: (references: ExternalAgentRef[]) => void;
  /** Names claimed by more than one delegate, specialist or remote agent. */
  clashes: ReadonlySet<string>;
  disabled?: boolean;
}

/**
 * Other vendors' agents this one may hand work to over A2A (#2092).
 *
 * Beside the organization's own delegates rather than in a list of its own
 * elsewhere, because to the delegating model they are the same thing - a
 * handle to call with a task. Not pinned: a remote agent's owner changes it on
 * their side, so what a reference names is the registration.
 */
export function RemoteDelegateList({
  registered,
  references,
  onChange,
  clashes,
  disabled,
}: RemoteDelegateListProps) {
  const t = useTranslations("agents");
  const chosen = new Set(references.map((ref) => ref.external_agent_id));
  const offered = registered.filter((agent) => !chosen.has(agent.id));
  const patch = (index: number, changes: Partial<ExternalAgentRef>) =>
    onChange(references.map((ref, at) => (at === index ? { ...ref, ...changes } : ref)));

  return (
    <section className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium">{t("remoteDelegatesHeading")}</p>
          <p className="text-muted-foreground text-xs">{t("remoteDelegatesDetail")}</p>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" disabled={disabled || offered.length === 0}>
              <Plus className="h-3.5 w-3.5" />
              {t("addRemoteDelegate")}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="max-h-72 scrollbar-thin overflow-y-auto">
            {offered.map((agent) => (
              <DropdownMenuItem
                key={agent.id}
                onSelect={() => onChange([...references, { external_agent_id: agent.id }])}
              >
                <Network className="text-muted-foreground size-4" aria-hidden />
                <span className="truncate">{agent.name}</span>
                <span className="text-muted-foreground font-mono text-xs">{agent.slug}</span>
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {references.length === 0 ? (
        <p className="text-muted-foreground border-border rounded-lg border border-dashed px-3 py-4 text-xs">
          {registered.length === 0
            ? t.rich("noRemoteAgentsRegistered", {
                link: (chunks) => (
                  <Link href={ROUTES.REMOTE_AGENTS} className="underline underline-offset-4">
                    {chunks}
                  </Link>
                ),
              })
            : t("noRemoteDelegatesYet")}
        </p>
      ) : (
        <ul className="divide-y rounded-lg border">
          {references.map((reference, index) => {
            const agent = registered.find((entry) => entry.id === reference.external_agent_id);
            return (
              <li
                key={reference.external_agent_id}
                aria-label={agent?.slug ?? reference.external_agent_id}
                className="space-y-2 p-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="bg-foreground/[0.06] flex size-8 shrink-0 items-center justify-center rounded-full">
                      <Network className="text-muted-foreground size-4" aria-hidden />
                    </span>
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">
                        {agent?.name ?? t("remoteDelegateGone")}
                      </p>
                      <p className="text-muted-foreground font-mono text-xs">
                        {agent?.slug ?? reference.external_agent_id}
                      </p>
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    disabled={disabled}
                    aria-label={t("removeDelegate", {
                      name: agent?.name ?? reference.external_agent_id,
                    })}
                    onClick={() => onChange(references.filter((_, at) => at !== index))}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
                {agent === undefined && (
                  <p className="text-destructive text-xs">{t("remoteDelegateGoneDetail")}</p>
                )}
                {agent !== undefined && clashes.has(agent.slug) && (
                  <p className="text-destructive text-xs">
                    {t("delegateNameClash", { name: agent.slug })}
                  </p>
                )}
                <DelegationModeField
                  id={`remote-${reference.external_agent_id}-mode`}
                  value={reference.preferred_mode ?? null}
                  disabled={disabled}
                  onChange={(preferred_mode: DelegationMode | null) =>
                    patch(index, { preferred_mode })
                  }
                />
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
