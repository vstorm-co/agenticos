"use client";

import { useState } from "react";

import { Badge, Button, Card, CardContent, ConfirmDialog } from "@/components/ui";
import { EmptyState } from "@/components/states";
import { Database } from "lucide-react";
import { Chip } from "@/components/memory/memory-chip";
import { MemoryFactsPane } from "@/components/memory/memory-facts-pane";
import { MemoryFilesPane } from "@/components/memory/memory-files-pane";
import { useMemoryDangerZone } from "@/hooks/use-memory";
import { useAuthStore } from "@/stores";
import { useTranslations } from "next-intl";

interface MemoryPanelProps {
  agentId: string;
  canEdit: boolean;
  /** How the capability is configured, read from the spec binding. */
  backend: "native" | "mem0";
  enableFiles: boolean;
  enableFacts: boolean;
  /** Off means the agent is shared-only — no per-end-user store. */
  allowPersonal: boolean;
}

type SubTab = "files" | "facts";

/**
 * The Memory tab: the stored memories of one agent, managed by an operator.
 *
 * Memory has three owners — the organisation, one group chat, one person — so the
 * owner control filters both halves at once and "show me the rooms" means one
 * thing across the tab. The Files / Facts switcher appears only when both shapes
 * are enabled, and each pane is mounted keyed by owner so switching the filter
 * gives it a fresh page.
 */
export function MemoryPanel({
  agentId,
  canEdit,
  backend,
  enableFiles,
  enableFacts,
  allowPersonal,
}: MemoryPanelProps) {
  const t = useTranslations("memory");

  // A viewer may not list a whole kind of store, so starting them on "all" 404s the
  // tab; they start on the organisation's and reach their own notes through "mine".
  const ownUserId = useAuthStore((state) => state.user?.id);
  // The key the runtime derives for this person, so "mine" opens the very store the
  // agent reads back when they chat (`person_owner_key`).
  const ownKey = ownUserId ? `person:${ownUserId}` : null;
  const [owner, setOwner] = useState<string>(canEdit ? "all" : "org");
  const [sub, setSub] = useState<SubTab>(enableFiles ? "files" : "facts");

  const showSwitcher = enableFiles && enableFacts;
  const active: SubTab = showSwitcher ? sub : enableFiles ? "files" : "facts";
  // A mem0 agent's facts live in mem0, so every native fact route refuses it. Say so
  // once here rather than mounting a pane whose every request comes back an error,
  // and keep the danger zone out: the combined clear refuses too, so it could only fail.
  const factsAreRemote = backend === "mem0";
  const { clearMemory } = useMemoryDangerZone(agentId);
  const [clearOpen, setClearOpen] = useState(false);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2" data-tour="agent-memory">
          <Badge variant="secondary">{t(allowPersonal ? "cfgPersonalOn" : "cfgNoPersonal")}</Badge>
          <Badge variant="outline">{t(backend === "mem0" ? "cfgMem0" : "cfgNative")}</Badge>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-muted-foreground text-xs">{t("scope")}</span>
          {canEdit ? (
            <>
              <Chip active={owner === "all"} onClick={() => setOwner("all")}>
                {t("scopeAll")}
              </Chip>
              <Chip active={owner === "org"} onClick={() => setOwner("org")}>
                {t("scopeOrg")}
              </Chip>
              <Chip active={owner === "person"} onClick={() => setOwner("person")}>
                {t("scopePeople")}
              </Chip>
              <Chip active={owner === "room"} onClick={() => setOwner("room")}>
                {t("scopeRooms")}
              </Chip>
            </>
          ) : (
            <>
              <Chip active={owner === "org"} onClick={() => setOwner("org")}>
                {t("scopeOrg")}
              </Chip>
              {ownKey !== null && (
                <Chip active={owner === ownKey} onClick={() => setOwner(ownKey)}>
                  {t("scopeMine")}
                </Chip>
              )}
            </>
          )}
        </div>
      </div>

      {showSwitcher && (
        <div className="flex items-center gap-1.5">
          <Chip active={active === "files"} onClick={() => setSub("files")}>
            {t("files")}
          </Chip>
          <Chip active={active === "facts"} onClick={() => setSub("facts")}>
            {t("facts")}
          </Chip>
        </div>
      )}

      {!enableFiles && !enableFacts ? (
        <EmptyState
          icon={Database}
          title={t("nothingEnabled")}
          description={t("nothingEnabledHint")}
        />
      ) : active === "files" ? (
        <MemoryFilesPane key={owner} agentId={agentId} canEdit={canEdit} owner={owner} />
      ) : factsAreRemote ? (
        <EmptyState icon={Database} title={t("factsInMem0")} description={t("factsInMem0Hint")} />
      ) : (
        <MemoryFactsPane key={owner} agentId={agentId} canEdit={canEdit} owner={owner} />
      )}

      {canEdit && !factsAreRemote && (enableFiles || enableFacts) && (
        <Card className="border-destructive/40">
          <CardContent className="flex flex-wrap items-center justify-between gap-3 p-5">
            <div className="min-w-0 space-y-1">
              <p className="text-destructive text-sm font-medium">{t("clearMemory")}</p>
              <p className="text-muted-foreground text-sm">{t("clearMemoryHint")}</p>
            </div>
            <Button variant="destructive" onClick={() => setClearOpen(true)}>
              {t("clearMemory")}
            </Button>
          </CardContent>
        </Card>
      )}

      {clearOpen && (
        <ConfirmDialog
          open
          onOpenChange={() => setClearOpen(false)}
          title={t("clearMemoryConfirm")}
          description={t("clearMemoryHint")}
          confirmLabel={t("clearMemory")}
          destructive
          loading={clearMemory.isPending}
          onConfirm={async () => {
            await clearMemory.mutateAsync();
            setClearOpen(false);
          }}
        />
      )}
    </div>
  );
}
