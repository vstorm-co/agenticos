"use client";

import { useRef, useState } from "react";
import { ArrowUpRight, ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
  Sheet,
  SheetClose,
  SheetContent,
  SheetTitle,
} from "@/components/ui";

import { useAgentVersion, useCapabilityCatalog, useMcpCatalog, useMcpConnections } from "@/hooks";
import { useCapabilityGuide } from "@/hooks/use-capability-guide";
import { useNarrowScreen } from "@/hooks/use-narrow-screen";
import { capabilityRows, connectedAppNames } from "@/lib/agent-capabilities";
import type { Agent } from "@/types/agents";

/**
 * What the selected agent can do, in the empty chat, before anyone types.
 *
 * Generated from the agent's own bindings, never hand-written per agent: the
 * published version's enabled capabilities, in the plain words the capability
 * guide gives each one, with the guide's first example as something to try;
 * and the apps its published version is bound to, by name. Bound is all the page's
 * data can say: it does not know whether the reader has connected a personal
 * app or whether an organization connection is enabled, so the line makes no
 * claim that either is usable. It sits
 * in the empty state rather than the Builder because that is where the
 * question "which agent do I talk to?" is asked - a person choosing an agent
 * should not have to open the Builder to learn what one does.
 *
 * An agent with no bindings says so plainly, so the panel never invents a
 * capability. It says nothing at all while any list it reads from is still
 * loading, or where a lookup failed (catalog or version) and left it with no rows for an
 * agent that may be bound to something: a "no tools" line drawn on a failed catalog
 * would be a lie about a capable agent.
 *
 * It is a compact control, closed by default: the lists open in a popover, or a
 * sheet on a phone, so the panel never takes height from the column the
 * composer sits in. The content is unmounted while it is closed.
 */
export function AgentCapabilitiesPanel({
  agent,
  onPick,
}: {
  agent: Agent | undefined;
  onPick: (prompt: string) => void;
}) {
  const t = useTranslations("chat.empty");
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const phone = useNarrowScreen();
  const { capabilities, isLoading: catalogLoading } = useCapabilityCatalog();
  const guide = useCapabilityGuide();
  const {
    version,
    isLoading: versionLoading,
    error: versionError,
  } = useAgentVersion(agent?.id ?? null, agent?.current_version_id ?? null);
  const { connections, isLoading: connectionsLoading } = useMcpConnections();
  const { servers, isLoading: serversLoading } = useMcpCatalog();

  if (!agent || catalogLoading || versionLoading || connectionsLoading || serversLoading) {
    return null;
  }
  const rows = capabilityRows(agent.published_capabilities, capabilities, guide);
  const apps = connectedAppNames(version?.spec.mcp_servers, connections, servers);
  if (rows.length === 0 && apps.length === 0) {
    const bound =
      (agent.published_capabilities ?? []).length > 0 ||
      (version?.spec.mcp_servers ?? []).length > 0 ||
      versionError !== null;
    if (bound) return null;
  }

  const content = (
    <CapabilitiesContent
      rows={rows}
      apps={apps}
      onPick={(prompt) => {
        setOpen(false);
        onPick(prompt);
      }}
    />
  );
  const button = (
    <button
      ref={trigger}
      type="button"
      aria-haspopup="dialog"
      aria-expanded={open}
      onClick={phone ? () => setOpen(true) : undefined}
      className="bg-foreground/[0.06] hover:bg-foreground/[0.1] data-[state=open]:bg-foreground/[0.12] text-muted-foreground hover:text-foreground focus-visible:ring-ring touch:min-h-11 inline-flex touch-manipulation items-center gap-1.5 rounded-lg px-2.5 py-1 text-[13px] transition-colors outline-none focus-visible:ring-2"
    >
      {t("panelTitle")}
      <ChevronDown aria-hidden className="h-3 w-3 shrink-0" />
    </button>
  );

  if (phone) {
    return (
      <>
        {button}
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetContent
            side="bottom"
            onCloseAutoFocus={(event) => {
              event.preventDefault();
              trigger.current?.focus({ preventScroll: true });
            }}
          >
            <div className="flex items-center justify-between gap-2 border-b px-4 py-2">
              <SheetTitle className="text-base">{t("panelTitle")}</SheetTitle>
              <SheetClose onClick={() => setOpen(false)} />
            </div>
            <div className="p-4">{content}</div>
          </SheetContent>
        </Sheet>
      </>
    );
  }
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>{button}</PopoverTrigger>
      <PopoverContent
        align="end"
        collisionPadding={12}
        aria-label={t("panelTitle")}
        className="bg-popover max-h-[min(28rem,70dvh)] w-[min(26rem,calc(100vw-1.5rem))] overflow-y-auto p-4"
      >
        {content}
      </PopoverContent>
    </Popover>
  );
}

function CapabilitiesContent({
  rows,
  apps,
  onPick,
}: {
  rows: ReturnType<typeof capabilityRows>;
  apps: string[];
  onPick: (prompt: string) => void;
}) {
  const t = useTranslations("chat.empty");
  if (rows.length === 0 && apps.length === 0) {
    return <p className="text-muted-foreground text-sm leading-relaxed">{t("panelEmpty")}</p>;
  }
  return (
    <>
      <ul className="space-y-4">
        {rows.map((row) => {
          const example = row.example;
          return (
            <li key={row.id}>
              <p className="text-sm leading-relaxed">
                <span className="text-foreground font-medium">{row.name}</span>
                <span className="text-muted-foreground"> — {row.does}</span>
              </p>
              {example !== null && (
                <button
                  type="button"
                  onClick={() => onPick(example)}
                  className="hover:bg-muted focus-visible:ring-ring bg-muted/60 text-foreground/80 mt-1.5 inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-left text-[13px] transition-colors outline-none focus-visible:ring-2"
                >
                  <ArrowUpRight className="h-3.5 w-3.5 shrink-0" aria-hidden />
                  {example}
                </button>
              )}
            </li>
          );
        })}
      </ul>
      {apps.length > 0 && (
        <p className="text-muted-foreground mt-4 text-sm leading-relaxed">
          {t("panelApps", { apps: apps.join(" · ") })}
        </p>
      )}
    </>
  );
}
