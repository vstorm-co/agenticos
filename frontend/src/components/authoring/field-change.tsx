"use client";

import { useTranslations } from "next-intl";

import { Badge, Input, Textarea } from "@/components/ui";
import type { FieldValue, Hunk } from "@/types/authoring";
import { AddsAccess } from "./adds-access";
import { TextDiff } from "./text-diff";

type Translate = ReturnType<typeof useTranslations>;

const SETTINGS = ["temperature", "top_p", "max_tokens", "timeout", "parallel_tool_calls"];
const NUMERIC = new Set([
  "max_steps",
  ...SETTINGS.filter((name) => name !== "parallel_tool_calls"),
]);

/** The setting or text a person may reword before accepting, with its kind. */
export function editable(path: string | null | undefined): "number" | "boolean" | "text" | null {
  if (!path) return null;
  const leaf = path.slice(path.lastIndexOf("/") + 1);
  if (path === "description" || path.endsWith("/description")) return "text";
  if (path === "max_steps" || (path.startsWith("model_settings/") && NUMERIC.has(leaf))) {
    return "number";
  }
  if (path === "model_settings/parallel_tool_calls") return "boolean";
  return null;
}

/** What a person typed into an edit, as the value the field holds. */
export function parsed(path: string | null | undefined, text: string): FieldValue {
  const kind = editable(path);
  if (kind === "number") return text.trim() === "" ? null : Number(text);
  if (kind === "boolean") return text === "true";
  return text;
}

function named(value: FieldValue, names: Record<string, string>): string {
  if (value === null) return "";
  if (typeof value === "object" && !Array.isArray(value) && typeof value.id === "string") {
    return names[value.id] ?? value.id;
  }
  if (typeof value === "string") return names[value] ?? value;
  return JSON.stringify(value);
}

/** The field a change is to, in words: "Temperature", "Capability Apps", "MCP tools of CRM". */
export function fieldLabel(hunk: Hunk, t: Translate): string {
  const path = hunk.path ?? "";
  const names = hunk.names;
  const [root = "", key = "", leaf = "", name = ""] = path.split("/");
  const subject = named(hunk.op === "remove" ? hunk.base_value : hunk.new_value, names);
  if (path === "description") return t("description");
  if (path === "model_profile_id") return t("model");
  if (path === "max_steps") return t("maxSteps");
  if (root === "model_settings") return t(`setting.${key}`);
  if (path === "capabilities")
    return t(hunk.op === "remove" ? "capabilityRemove" : "capabilityAdd", { name: subject });
  if (path === "collection_ids")
    return t(hunk.op === "remove" ? "collectionRemove" : "collectionAdd", { name: subject });
  if (path === "context_ids")
    return t(hunk.op === "remove" ? "contextRemove" : "contextAdd", { name: subject });
  if (root === "mcp_servers") return t("mcpTools", { name: names[key] ?? key });
  if (leaf === "inline") return t("specialist", { name });
  if (leaf === "config") return t("capabilityConfig", { name: key });
  if (leaf === "approval") return t("approval", { name: key });
  return t("toolApproval", { name });
}

function shown(value: FieldValue, names: Record<string, string>, t: Translate): string {
  if (value === null) return t("unset");
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return named(value, names);
}

/**
 * What a field change does: the value before and after, or the item it adds or
 * removes - named, never an id the reader cannot read - and what it is expected
 * to do to cost, what it reaches that writes, and why Accept waits when it does.
 */
export function FieldDiff({
  hunk,
  editing,
  onEdit,
  expected = true,
}: { hunk: Hunk; expected?: boolean } & (
  | { editing: null; onEdit?: (text: string) => void }
  | { editing: string; onEdit: (text: string) => void }
)) {
  const t = useTranslations("authoring.field");
  const names = hunk.names;
  const after = hunk.status === "accepted" ? hunk.accepted_value : hunk.new_value;
  const effect = hunk.effect;
  const kind = editable(hunk.path);

  return (
    <div className="space-y-2">
      {editing !== null && kind === "boolean" ? (
        <select
          aria-label={t("editLabel")}
          className="border-input bg-background h-9 rounded-md border px-2 text-sm"
          value={editing}
          onChange={(event) => onEdit(event.target.value)}
        >
          <option value="true">{t("yes")}</option>
          <option value="false">{t("no")}</option>
        </select>
      ) : editing !== null && kind === "number" ? (
        <Input
          aria-label={t("editLabel")}
          type="number"
          value={editing}
          onChange={(event) => onEdit(event.target.value)}
        />
      ) : editing !== null ? (
        <Textarea
          aria-label={t("editLabel")}
          value={editing}
          rows={3}
          onChange={(event) => onEdit(event.target.value)}
        />
      ) : hunk.op === "set" ? (
        <TextDiff before={shown(hunk.base_value, names, t)} after={shown(after, names, t)} />
      ) : (
        <Badge variant={hunk.op === "remove" ? "outline" : "secondary"}>
          {hunk.op === "remove" ? t("removes") : t("adds")}{" "}
          {named(hunk.op === "remove" ? hunk.base_value : after, names)}
        </Badge>
      )}
      {effect?.runs !== undefined && (
        <p className="text-muted-foreground text-xs">
          {effect.cost_per_run_before && effect.cost_per_run_after
            ? t("cost", {
                before: effect.cost_per_run_before,
                after: effect.cost_per_run_after,
                runs: effect.runs,
              })
            : t("unpriced")}
          {effect.rough ? ` ${t("rough", { runs: effect.runs })}` : ""}
        </p>
      )}
      {effect?.writes && effect.writes.length > 0 && (
        <p className="text-muted-foreground text-xs">
          {t("writes", { tools: effect.writes.join(", ") })}
        </p>
      )}
      {effect?.adds && effect.adds.length > 0 && <AddsAccess adds={effect.adds} names={names} />}
      {expected && hunk.expected_effect && (
        <p className="text-sm">{t("expects", { effect: hunk.expected_effect })}</p>
      )}
      {hunk.blocked && hunk.status === "pending" && (
        <p role="note" className="text-sm text-amber-700 dark:text-amber-400">
          {t(`blocked.${hunk.blocked}`)}
        </p>
      )}
    </div>
  );
}
