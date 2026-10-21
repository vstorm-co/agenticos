"use client";

import { useState } from "react";
import { Boxes, Plus } from "lucide-react";
import { toast } from "sonner";

import { PageHeader } from "@/components/dashboard/page-header";
import { ConnectionDialog } from "@/components/sandboxes/connection-dialog";
import { ConnectionsTable } from "@/components/sandboxes/connections-table";
import { PolicyPanel } from "@/components/sandboxes/policy-panel";
import { SessionsPanel } from "@/components/sandboxes/sessions-panel";
import {
  Button,
  ConfirmDialog,
  ListCard,
  ListCardEmpty,
  Skeleton,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";
import { ErrorState } from "@/components/states";
import { usePermissions, useSandboxConnections, useUrlState } from "@/hooks";
import { Perm } from "@/types/permissions";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { holdsSessions, watchableConnections } from "@/lib/dashboard/sandbox";
import type { SandboxConnectionRecord } from "@/lib/sandbox-connections-api";
import { useTranslations } from "next-intl";

/**
 * The operator screen for sandboxes, in two tabs on two clocks: connections
 * are configuration and change when somebody registers a host; what is running
 * is live and refetches every ten seconds. Stacked, the live half sat below a
 * table of unknown height (#140) — split, the sessions query only exists while
 * its tab is on screen, so a page nobody is looking at polls nothing.
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
  // A delete refused because sandboxes on the connection are still on the
  // provider: the person is asked whether they removed them there (#2250).
  const [stranded, setStranded] = useState<{
    connection: SandboxConnectionRecord;
    pending: number;
  } | null>(null);
  const [forgetting, setForgetting] = useState(false);
  const tErrors = useTranslations("errors");
  // In the URL so a pasted link lands on the tab it was sent from. The default
  // keeps the parameter off, so `/sandboxes` stays the connections screen.
  const [tabParam, setTabParam] = useUrlState("tab");
  const tab = tabParam === "running" ? "running" : "connections";

  const watchable = watchableConnections(connections).filter(holdsSessions);

  const deleteConnection = async (connection: SandboxConnectionRecord) => {
    try {
      await remove(connection.id);
    } catch (err) {
      const pending = err instanceof ApiError ? err.details?.pending_destroys : undefined;
      if (typeof pending === "number") setStranded({ connection, pending });
      else toast.error(getErrorMessage(err, tErrors, t("deleteFailed")));
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("sandboxes2")}
        description={t("pageDescription")}
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

      <Tabs
        value={tab}
        onValueChange={(value) => setTabParam(value === "connections" ? null : value)}
      >
        <TabsList>
          <TabsTrigger value="connections">{t("tabConnections")}</TabsTrigger>
          <TabsTrigger value="running">{t("tabRunning")}</TabsTrigger>
        </TabsList>

        <TabsContent value="connections">
          <ListCard
            data-tour="sandboxes-connections"
            title={t("sandboxConnections")}
            // With the list refused or still loading, "0 connections" would
            // state as fact something no answer has said - the skeleton stays.
            counted={
              isLoading || error !== null
                ? null
                : t("registeredCount", { count: connections.length })
            }
            contentClassName="p-0"
          >
            {isLoading ? (
              <div className="space-y-3 p-5">
                {[0, 1].map((row) => (
                  <Skeleton key={row} className="h-10 w-full" />
                ))}
              </div>
            ) : error !== null ? (
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
                onDelete={(connection) => void deleteConnection(connection)}
              />
            )}
          </ListCard>
        </TabsContent>

        <TabsContent value="running">
          {isLoading ? (
            <div className="space-y-3 p-5">
              {[0, 1].map((row) => (
                <Skeleton key={row} className="h-10 w-full" />
              ))}
            </div>
          ) : error !== null ? (
            // With the list refused, "no container connection registered" would
            // state as fact something the request never answered.
            <ErrorState description={error} className="m-5" />
          ) : (
            <SessionsPanel connections={watchable} />
          )}
        </TabsContent>
      </Tabs>

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

      {stranded && (
        <ConfirmDialog
          open
          onOpenChange={(open) => {
            if (!open) setStranded(null);
          }}
          title={t("strandedTitle", { count: stranded.pending })}
          description={t("strandedBody", {
            count: stranded.pending,
            name: stranded.connection.name,
          })}
          confirmLabel={t("strandedConfirm")}
          destructive
          loading={forgetting}
          onConfirm={async () => {
            setForgetting(true);
            try {
              await remove(stranded.connection.id, { forgetPendingDestroys: true });
              setStranded(null);
            } catch (err) {
              toast.error(getErrorMessage(err, tErrors, t("deleteFailed")));
            } finally {
              setForgetting(false);
            }
          }}
        />
      )}

      <PolicyPanel
        connection={inspecting}
        onOpenChange={(open) => {
          if (!open) setInspecting(null);
        }}
      />
    </div>
  );
}
