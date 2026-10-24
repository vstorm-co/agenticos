"use client";

import { useState } from "react";
import { Bot, CalendarClock, Plug } from "lucide-react";
import { useTranslations } from "next-intl";

import { ConnectOwnButton } from "@/components/agents/connect-server-dialog";
import { McpServerIcon } from "@/components/mcp/mcp-server-icon";
import { TriggerFormDialog } from "@/components/triggers/trigger-form-dialog";
import { Button } from "@/components/ui";
import { useMcpConnections } from "@/hooks/use-mcp-connections";
import { useMcpServerEntry } from "@/hooks/use-mcp-servers";
import { pointAt } from "@/lib/assistant-highlight";
import { ROUTES } from "@/lib/constants";
import { useRouter } from "@/lib/locale-navigation";
import { hereForMcpOAuthReturn } from "@/lib/mcp-oauth";
import { ownAccountStatus } from "@/lib/mcp-servers";
import type { SetupKind, SetupProposal } from "@/lib/turn-extras";
import { useArchitectAskStore } from "@/stores/architect-ask-store";
import type { TriggerTemplate } from "@/types/trigger-templates";

/** Weekly on Monday at 8:00 UTC, for a routine proposed without a cadence. */
const WEEKLY = { schedule_kind: "cron", cron_expression: "0 8 * * 1" } as const;

const ICONS: Record<SetupKind, typeof Bot> = {
  agent: Bot,
  routine: CalendarClock,
  connection: Plug,
};

const CARD = "bg-muted/60 flex flex-col gap-2 rounded-2xl p-3";

/**
 * What an agent proposed to set up - at the end of a welcome interview, most
 * often (#2301): each a card acted on in one click. A routine opens the routine
 * dialog filled in on the agent that proposed it, an agent is a question to the
 * Architect, and a connection with a catalog key is that service's own card -
 * its logo and its Connect, back to this conversation once the consent lands.
 * One without a key, or with a key nothing knows, opens the MCP servers page at
 * its add button.
 */
export function SetupProposals({
  proposals,
  agentId,
}: {
  proposals: SetupProposal[];
  agentId: string | null;
}) {
  const t = useTranslations("chat.extras.setup");
  const router = useRouter();
  const ask = useArchitectAskStore((state) => state.ask);
  const [routine, setRoutine] = useState<TriggerTemplate | null>(null);

  const take = (proposal: SetupProposal) => {
    if (proposal.kind === "routine") {
      setRoutine({
        key: proposal.key,
        label: proposal.title,
        description: "",
        prompt: proposal.request,
        trigger_type: "schedule",
        suggested_cadence: proposal.cron
          ? { schedule_kind: "cron", cron_expression: proposal.cron }
          : WEEKLY,
      });
    } else if (proposal.kind === "agent") {
      ask(t("agentAsk", { request: proposal.request }));
    } else {
      router.push(ROUTES.MCP_SERVERS);
      void pointAt("mcp-add");
    }
  };

  return (
    <div className="grid gap-2 sm:grid-cols-3">
      {proposals.map((proposal) =>
        proposal.kind === "connection" && proposal.server !== null ? (
          <ConnectionProposal
            key={proposal.key}
            proposal={proposal}
            server={proposal.server}
            onFallback={() => take(proposal)}
          />
        ) : (
          <ProposalCard key={proposal.key} proposal={proposal} onTake={() => take(proposal)} />
        ),
      )}
      {routine && (
        <TriggerFormDialog
          agentId={agentId}
          open
          onOpenChange={(open) => !open && setRoutine(null)}
          initialTemplate={routine}
        />
      )}
    </div>
  );
}

function ProposalCard({ proposal, onTake }: { proposal: SetupProposal; onTake: () => void }) {
  const t = useTranslations("chat.extras.setup");
  const Icon = ICONS[proposal.kind];
  return (
    <div role="group" aria-label={proposal.title} className={CARD}>
      <span className="bg-card text-foreground shadow-card flex h-8 w-8 items-center justify-center rounded-xl">
        <Icon className="h-4 w-4" aria-hidden />
      </span>
      <p className="text-sm font-medium">{proposal.title}</p>
      <p className="text-muted-foreground flex-1 text-xs">{proposal.why}</p>
      <Button type="button" size="sm" variant="outline" onClick={onTake}>
        {t(`take.${proposal.kind}`)}
      </Button>
    </div>
  );
}

/**
 * A service to connect, as the service: its logo, and the same Connect the MCP
 * servers page has - straight to the provider's sign-in for one that signs in.
 * Once the person's own account is on it the card has done its job and leaves
 * the conversation, rather than standing in it saying so.
 */
function ConnectionProposal({
  proposal,
  server,
  onFallback,
}: {
  proposal: SetupProposal;
  server: string;
  onFallback: () => void;
}) {
  const t = useTranslations("chat.extras.setup");
  const { entry, isLoading } = useMcpServerEntry(server);
  const { connections } = useMcpConnections();
  if (!isLoading && entry === null) {
    return <ProposalCard proposal={proposal} onTake={onFallback} />;
  }
  if (ownAccountStatus(server, connections) === "connected") return null;
  return (
    <div role="group" aria-label={proposal.title} className={CARD}>
      {/* A white tile in both themes, as on the servers page: the logos are drawn for a light ground. */}
      <span className="border-foreground/10 grid size-8 place-items-center rounded-xl border bg-white">
        <McpServerIcon
          icon={entry?.icon ?? null}
          name={entry?.name ?? proposal.request}
          url={entry?.url}
          className="size-5 text-neutral-900"
        />
      </span>
      <p className="text-sm font-medium">{proposal.title}</p>
      <p className="text-muted-foreground flex-1 text-xs">{proposal.why}</p>
      {entry === null ? (
        <Button type="button" size="sm" variant="outline" disabled>
          {t("take.connection")}
        </Button>
      ) : (
        <ConnectOwnButton
          entry={entry}
          label={t("take.connection")}
          // Back to this conversation once the consent lands: the request that
          // needed the service is here.
          returnTo={hereForMcpOAuthReturn()}
        />
      )}
    </div>
  );
}
