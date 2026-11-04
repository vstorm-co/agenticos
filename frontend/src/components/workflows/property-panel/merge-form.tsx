"use client";

import { useTranslations } from "next-intl";

import { Input, Label } from "@/components/ui";
import { resolveDefinitions } from "@/components/workflows/validation";
import {
  type NodeCatalog,
  type NodeInstance,
  type Uuid,
  type WorkflowGraph,
  nodeDisplayName,
} from "@/lib/workflows/types";

import { mergeBranches } from "./merge-config";

interface MergeFormProps {
  node: NodeInstance;
  graph: WorkflowGraph;
  catalog: NodeCatalog;
  disabled?: boolean;
  updateNodeConfig: (nodeId: Uuid, config: Record<string, unknown>) => void;
}

/**
 * A Merge's settings: whether it waits for the branch that ran or for every branch,
 * and under "all branches" the name each branch goes by where later steps read it.
 *
 * A merge that has not been wired shows "the branch that ran", as its empty config
 * means. A branch whose name the config does not hold - a pasted merge's, or one wired
 * since - shows its default, and writing any name stores them all.
 */
export function MergeForm({ node, graph, catalog, disabled, updateNodeConfig }: MergeFormProps) {
  const t = useTranslations("workflows");
  const definitions = resolveDefinitions(graph, catalog);
  const all = node.config.wait_for === "all";
  const branches = mergeBranches(graph, definitions, node);
  const nameOf = (source: NodeInstance, port: string) => {
    const base = nodeDisplayName(
      definitions.get(source.id)?.name ?? source.definition_id,
      source.id,
      true,
      source.label,
    );
    return source.definition_id === "logic.split" ? `${base} · ${port}` : base;
  };
  const sources = new Map(graph.nodes.map((candidate) => [candidate.id, candidate]));

  const setMode = (mode: "one" | "all") =>
    updateNodeConfig(node.id, {
      ...node.config,
      wait_for: mode,
      ...(mode === "all" ? { branch_keys: branches } : {}),
    });
  const rename = (index: number, key: string) =>
    updateNodeConfig(node.id, {
      ...node.config,
      branch_keys: branches.map((branch, at) => (at === index ? { ...branch, key } : branch)),
    });

  return (
    <section className="space-y-4">
      <fieldset className="space-y-2" disabled={disabled}>
        <legend className="text-sm font-medium">{t("waitFor")}</legend>
        {(["one", "all"] as const).map((mode) => (
          <label key={mode} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name={`merge-wait-${node.id}`}
              checked={all === (mode === "all")}
              onChange={() => setMode(mode)}
            />
            {mode === "one" ? t("waitForOne") : t("waitForAll")}
          </label>
        ))}
      </fieldset>
      {all && (
        <div className="space-y-3">
          {branches.map((branch, index) => {
            const source = sources.get(branch.source_node_id) as NodeInstance;
            const id = `merge-key-${node.id}-${index}`;
            return (
              <div key={`${branch.source_node_id}/${branch.source_port}`} className="space-y-1.5">
                <Label htmlFor={id}>
                  {t("branchKey")} · {nameOf(source, branch.source_port)}
                </Label>
                <Input
                  id={id}
                  value={branch.key}
                  disabled={disabled}
                  onChange={(event) => rename(index, event.target.value)}
                />
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
