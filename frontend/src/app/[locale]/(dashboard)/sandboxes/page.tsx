"use client";

import { useState } from "react";
import { Boxes, Plus } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";
import { ConnectionDialog } from "@/components/sandboxes/connection-dialog";
import { ConnectionsTable } from "@/components/sandboxes/connections-table";
import { PolicyPanel } from "@/components/sandboxes/policy-panel";
import { SessionsPanel } from "@/components/sandboxes/sessions-panel";
import { Button, ListCard, ListCardEmpty, Skeleton } from "@/components/ui";
import { ErrorState } from "@/components/states";
import { usePermissions, useSandboxConnections } from "@/hooks";
import { Perm } from "@/types/permissions";
import type { SandboxConnectionRecord } from "@/lib/sandbox-connections-api";
import { useTranslations } from "next-intl";

/**
 * One sentence, in one place, so the skeleton and the loaded page cannot
 * disagree - a header whose text changes when the data lands is a flicker.
 */
const SANDBOXES_DESCRIPTION = "pageDescription";

/**
 * The operator screen for sandbox connections.
 *
 * Gated on `connections:manage`, the same permission the vault carries and for
 * the same reason: whoever edits these decides which host an agent's shell runs
 * on, and the credential behind one can start containers there.
 */
export default function SandboxesPage() {
  const t = useTranslations("pages.sandboxes");
  const { connections, isLoading, error, create, update, remove } = useSandboxConnections();
  const { can } = usePermissions();
  const canManage = can(Perm.connectionsManage);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<SandboxConnectionRecord | null>(null);
  const [inspecting, setInspecting] = useState<SandboxConnectionRecord | null>(null);
  // The default container connection, which is where an agent that names none
  // runs. Daytona holds no sessions of ours to enumerate.
  const watching =
    connections.find(
      (connection) => connection.is_default && connection.is_active && connection.kind === "docker",
    ) ?? null;

  if (isLoading)
    return (
      <div className="space-y-6">
        <PageHeader title={t("sandboxes")} description={t(SANDBOXES_DESCRIPTION)} />
        <ListCard title={t("sandboxConnections")} counted={null} contentClassName="p-0">
          <div className="space-y-3 p-5">
            {[0, 1].map((row) => (
              <Skeleton key={row} className="h-10 w-full" />
            ))}
          </div>
        </ListCard>
      </div>
    );

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("sandboxes2")}
        description={t(SANDBOXES_DESCRIPTION)}
        actions={
          canManage ? (
            <Button
              onClick={() => {
                setEditing(null);
                setDialogOpen(true);
              }}
            >
              <Plus className="h-4 w-4" />
              {t("addConnection")}
            </Button>
          ) : undefined
        }
      />

      <ListCard
        title={t("sandboxConnections")}
        // With the list refused, "0 connections" would state as fact something
        // the request never answered - the skeleton stays.
        counted={error !== null ? null : t("registeredCount", { count: connections.length })}
        contentClassName="p-0"
      >
        {error !== null ? (
          // An empty table and a failed request are the same pixels, so the
          // refusal is shown where the rows would be rather than dressed as
          // "none registered".
          <ErrorState description={error} className="m-5" />
        ) : connections.length === 0 ? (
          <ListCardEmpty
            icon={Boxes}
            title={t("noSandboxConnectionsYet")}
            description={t("agentsCanStillKeep")}
          />
        ) : (
          <ConnectionsTable
            connections={connections}
            onEdit={(connection) => {
              setEditing(connection);
              setDialogOpen(true);
            }}
            onInspect={setInspecting}
            onDelete={(connection) => void remove(connection.id)}
          />
        )}
      </ListCard>

      {/* Mounted only while it is open, and keyed on the row it is editing. The
          form reads its initial values once; without this, clicking Edit on a
          second host showed the first one's values, which is how somebody
          renames the wrong host. */}
      {dialogOpen && (
        <ConnectionDialog
          key={editing?.id ?? "new"}
          editing={editing}
          onOpenChange={setDialogOpen}
          onSubmit={async (input) => {
            if (editing) await update(editing.id, input);
            else await create(input);
          }}
        />
      )}

      {/* Below the list, for the connection an agent gets by default. What is
          running is the question an operator asks second - after "is this host
          registered at all" - and it is live, so it belongs on the page rather
          than behind a click. */}
      <SessionsPanel connection={watching} />

      <PolicyPanel
        connection={inspecting}
        onOpenChange={(open) => {
          if (!open) setInspecting(null);
        }}
      />
    </div>
  );
}
