"use client";

import { useEffect, useMemo } from "react";
import { useQueries, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { useWorkflowTables } from "./use-workflow-tables";
import { qk } from "@/lib/query-keys";
import { getTable, listSchemaVersions } from "@/lib/tables-api";
import {
  graphTableRefs,
  liveColumns,
  nodeTableColumns,
  orphanValueBindings,
  rebindRef,
  recordWriterTables,
  safeToRebind,
  type BindingAt,
  type TableDrift,
  type TableRefSite,
} from "@/lib/workflows/table-drift";
import type { TableIORef } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

interface Plan {
  rebound: { site: TableRefSite; ref: TableIORef }[];
  drift: TableDrift[];
  orphans: BindingAt[];
}

/**
 * Read the organization's tables and their schemas again, so the editor judges
 * its references against what the server holds now: when the editor opens,
 * after a run or a publish was refused over a table, and when the person comes
 * back to the tab.
 */
function refreshWorkflowTables(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: qk.workflows.tables() });
  void queryClient.invalidateQueries({
    predicate: (query) => query.queryKey[0] === "tables" && query.queryKey[2] === "schema-versions",
  });
}

/**
 * Keeps the draft's table references on their tables' current schemas.
 *
 * A reference whose table's schema moved on is refused by every run and publish.
 * When every column it reads is still there with the same type, the draft is
 * updated in place - autosave writes it like any edit. Otherwise the reference is
 * left alone and recorded in the editor store as `tableDrift`, which the editor
 * shows as a problem on its step.
 *
 * A record-writing step on the current schema also loses its value bindings to
 * columns the table no longer has: its form no longer shows them, and every run
 * would fail on them with `UNKNOWN_COLUMN`.
 *
 * Nothing is decided on a cached table older than the list: such a copy is read
 * again first, so a reference is never "moved" onto the version it already names.
 */
export function useWorkflowTableDrift(enabled: boolean): void {
  const graph = useWorkflowEditorStore((state) => state.graph);
  const rebindTables = useWorkflowEditorStore((state) => state.rebindTables);
  const dropBindings = useWorkflowEditorStore((state) => state.dropBindings);
  const setTableDrift = useWorkflowEditorStore((state) => state.setTableDrift);
  const tablesStale = useWorkflowEditorStore((state) => state.tablesStale);
  const queryClient = useQueryClient();
  const refs = useMemo(() => (graph === null ? [] : graphTableRefs(graph)), [graph]);
  const writers = useMemo(() => (graph === null ? [] : recordWriterTables(graph)), [graph]);
  const { tables } = useWorkflowTables(enabled && refs.length > 0);
  const listedVersion = (id: string) => tables.find((entry) => entry.id === id)?.schema_version;

  const stale = refs.filter(({ ref }) => {
    const version = listedVersion(ref.table_id);
    return version !== undefined && version !== ref.schema_version;
  });
  const staleIds = [...new Set(stale.map(({ ref }) => ref.table_id))];
  // Writers already on the current schema: their tables' live columns are needed too.
  const writerIds = [
    ...new Set(
      writers
        .filter(({ tableId, version }) => listedVersion(tableId) === version)
        .map(({ tableId }) => tableId),
    ),
  ];
  const detailIds = [...new Set([...staleIds, ...writerIds])];

  const details = useQueries({
    queries: detailIds.map((id) => ({
      queryKey: qk.workflows.table(id),
      queryFn: () => getTable(id),
      enabled,
    })),
  });
  const histories = useQueries({
    queries: staleIds.map((id) => {
      const versions = [
        ...new Set([
          ...stale.filter(({ ref }) => ref.table_id === id).map(({ ref }) => ref.schema_version),
          listedVersion(id)!,
        ]),
      ].sort((a, b) => a - b);
      return {
        queryKey: [...qk.tables.schemaVersions(id), versions],
        queryFn: async () => ({
          items: (
            await Promise.all(versions.map((version) => listSchemaVersions(id, version)))
          ).flatMap((result) => result.items),
        }),
        enabled,
      };
    }),
  });
  const detail = (id: string) => details[detailIds.indexOf(id)]?.data;
  const history = (id: string) => histories[staleIds.indexOf(id)]?.data;
  const detailCurrent = (id: string) => detail(id)?.schema_version === listedVersion(id);
  const historyCurrent = (id: string) =>
    history(id)?.items.some((version) => version.version === listedVersion(id)) === true;

  // A cached copy older than the list: fetch it again.
  const behind = detailIds
    .filter((id) => !detailCurrent(id) || (staleIds.includes(id) && !historyCurrent(id)))
    .join(",");
  useEffect(() => {
    if (!enabled || behind === "") return;
    // The list too: a detail newer than the list means the list is the old one.
    void queryClient.invalidateQueries({ queryKey: qk.workflows.tables(), exact: true });
    for (const id of behind.split(",")) {
      void queryClient.invalidateQueries({ queryKey: qk.workflows.table(id), exact: true });
      void queryClient.invalidateQueries({ queryKey: qk.tables.schemaVersions(id) });
    }
  }, [enabled, behind, queryClient]);

  // Worked out only once every table it needs is in hand and current.
  let plan: string | null = null;
  if (graph !== null && behind === "") {
    const result: Plan = { rebound: [], drift: [], orphans: [] };
    for (const { site, ref } of stale) {
      const table = detail(ref.table_id)!;
      const next = rebindRef(ref, table.schema_version, liveColumns(table));
      const versions = history(ref.table_id)!.items;
      const dependencies = nodeTableColumns(graph, site, {
        before: versions.find((version) => version.version === ref.schema_version)?.columns ?? [],
        after: liveColumns(table),
      });
      if (safeToRebind(ref, table, versions, dependencies)) {
        result.rebound.push({ site, ref: next });
      } else {
        const field = site.binding === null ? null : graph.bindings[site.binding]!.target_field;
        const requiresReview = !safeToRebind(
          { ...ref, column_ids: [] },
          table,
          versions,
          dependencies,
        );
        result.drift.push({
          nodeId: site.nodeId,
          field,
          site,
          rebound: next,
          ...(requiresReview ? { requiresReview: true } : {}),
        });
      }
    }
    const live = new Map(
      writerIds.map((id) => [
        id,
        {
          version: detail(id)!.schema_version,
          columns: liveColumns(detail(id)!),
        },
      ]),
    );
    result.orphans = orphanValueBindings(graph, live);
    // A string, so the effect below runs when the outcome changes, not every render.
    plan = JSON.stringify(result);
  }

  // The list may be minutes old when the editor opens - a column added on the
  // table's own page just before: start from what the server holds.
  useEffect(() => {
    if (enabled) refreshWorkflowTables(queryClient);
  }, [enabled, queryClient]);

  // A run or a publish was refused over a table.
  useEffect(() => {
    if (enabled && tablesStale > 0) refreshWorkflowTables(queryClient);
  }, [enabled, tablesStale, queryClient]);

  // The query layer keeps tables for minutes and never refetches on focus, so a
  // schema changed in another tab would otherwise go unseen until a reload.
  useEffect(() => {
    if (!enabled) return;
    const refresh = () => {
      if (document.visibilityState === "visible") refreshWorkflowTables(queryClient);
    };
    document.addEventListener("visibilitychange", refresh);
    return () => document.removeEventListener("visibilitychange", refresh);
  }, [enabled, queryClient]);

  useEffect(() => {
    if (!enabled || plan === null) return;
    const { rebound, drift, orphans } = JSON.parse(plan) as Plan;
    setTableDrift(drift);
    rebindTables(rebound);
    dropBindings(orphans);
  }, [enabled, plan, rebindTables, dropBindings, setTableDrift]);
}
