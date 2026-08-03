"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { Boxes, Plus } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";
import { ConnectionDialog } from "@/components/sandboxes/connection-dialog";
import { ConnectionsTable } from "@/components/sandboxes/connections-table";
import { PolicyPanel } from "@/components/sandboxes/policy-panel";
import { SessionsPanel } from "@/components/sandboxes/sessions-panel";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Skeleton,
} from "@/components/ui";
import { usePermissions, useSandboxConnections } from "@/hooks";
import { Perm } from "@/types/permissions";
import type { SandboxConnectionRecord } from "@/lib/sandbox-connections-api";
import { useTranslations } from "next-intl";

/**
 * One sentence, in one place, so the skeleton and the loaded page cannot
 * disagree - a header whose text changes when the data lands is a flicker.
 */
const SANDBOXES_DESCRIPTION =
  "Where this organization's agents run shell commands and keep files. An agent names a " +
  "connection by id, so moving to another host is one edit here rather than a republish of " +
  "every agent. The token stays in the vault; nothing on this page can read it back. The files " +
  "themselves are on Workspaces, which is not an operator screen — everybody sees their own.";

function registeredCount(count: number): string {
  return count === 1 ? "1 connection" : `${count} connections`;
}

function ConnectionsCard({ count, children }: { count: number | null; children: ReactNode }) {
  const t = useTranslations("pages.sandboxes");
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 border-b px-5 py-4">
        <div className="space-y-1">
          <CardTitle className="text-sm">{t("sandboxConnections")}</CardTitle>
          <CardDescription className="text-xs">
            {count === null ? <Skeleton className="h-3 w-24" /> : registeredCount(count)}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="p-0">{children}</CardContent>
    </Card>
  );
}

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
        <PageHeader title={t("sandboxes")} description={SANDBOXES_DESCRIPTION} />
        <ConnectionsCard count={null}>
          <div className="space-y-3 p-5">
            {[0, 1].map((row) => (
              <Skeleton key={row} className="h-10 w-full" />
            ))}
          </div>
        </ConnectionsCard>
      </div>
    );

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("sandboxes2")}
        description={SANDBOXES_DESCRIPTION}
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

      {/* An empty table and a failed request are the same pixels, so the reason
          is said out loud rather than left to look like "none registered". */}
      {error !== null && <p className="text-destructive text-sm">{error}</p>}

      <ConnectionsCard count={connections.length}>
        {connections.length === 0 ? (
          <div className="px-6 py-16 text-center">
            <div className="bg-muted text-muted-foreground mx-auto flex h-11 w-11 items-center justify-center rounded-xl">
              <Boxes className="h-5 w-5" />
            </div>
            <p className="text-foreground mt-4 text-sm font-medium">
              {t("noSandboxConnectionsYet")}
            </p>
            <p className="text-muted-foreground mx-auto mt-1 max-w-md text-sm">
              {t("agentsCanStillKeep")}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto px-5 pb-2">
            <ConnectionsTable
              connections={connections}
              onEdit={(connection) => {
                setEditing(connection);
                setDialogOpen(true);
              }}
              onInspect={setInspecting}
              onDelete={(connection) => void remove(connection.id)}
            />
          </div>
        )}
      </ConnectionsCard>

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
