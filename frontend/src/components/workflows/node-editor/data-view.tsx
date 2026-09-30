"use client";

import { type DragEvent, useState } from "react";
import {
  Asterisk,
  Braces,
  Calendar,
  Circle,
  Fingerprint,
  Hash,
  List,
  type LucideIcon,
  ToggleLeft,
  Type,
} from "lucide-react";
import { useTranslations } from "next-intl";

import { JsonView } from "@/components/ui/json-view";
import { outputFieldPaths } from "@/components/workflows/property-panel/bindings";
import { resolveFieldType, schemaTypeToken } from "@/components/workflows/validation/schema";
import { type DraggedField, startFieldDrag } from "@/lib/workflows/field-drag";
import { type PlainType, plainType } from "@/lib/workflows/plain-types";
import { SHOWN_ROWS, cellText, schemaOf, tableOf, typeOf } from "@/lib/workflows/step-data";
import type { NodeDefinition, Uuid } from "@/lib/workflows/types";
import { cn } from "@/lib/utils";

type View = "table" | "json" | "schema";
const VIEWS: View[] = ["table", "json", "schema"];

/**
 * One step's data, three ways: as rows (a list of records as a table, anything
 * else as one row), as the JSON itself, and as its fields with their types - the
 * paths a later step reads.
 *
 * Given the step it came from (`source`), a column or a field can be dragged
 * onto a setting, which then reads it from that step.
 */
export function DataView({ value, source }: { value: Record<string, unknown>; source?: Uuid }) {
  const t = useTranslations("workflows");
  const [view, setView] = useState<View>("table");

  return (
    <div className="space-y-2">
      <div
        role="group"
        aria-label={t("dataViews")}
        className="bg-muted inline-flex rounded-md p-0.5"
      >
        {VIEWS.map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={view === option}
            onClick={() => setView(option)}
            className={cn(
              "rounded px-2 py-0.5 text-xs",
              view === option
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t(`dataView.${option}`)}
          </button>
        ))}
      </div>
      {view === "json" && <JsonView value={value} />}
      {view === "table" && <TableView value={value} source={source} />}
      {view === "schema" && <SchemaView value={value} source={source} />}
    </div>
  );
}

const DRAGGABLE = "cursor-grab active:cursor-grabbing hover:text-foreground";

function TableView({ value, source }: { value: Record<string, unknown>; source?: Uuid }) {
  const t = useTranslations("workflows");
  const [everyRow, setEveryRow] = useState(false);
  const { columns, rows, paths } = tableOf(value);
  const shown = everyRow ? rows : rows.slice(0, SHOWN_ROWS);
  if (columns.length === 0)
    return <p className="text-muted-foreground text-xs">{t("dataEmpty")}</p>;
  return (
    <div className="space-y-1">
      <div className="border-border overflow-x-auto rounded-md border">
        <table className="w-full text-xs">
          <thead className="bg-muted/50 text-muted-foreground">
            <tr>
              {columns.map((column) => {
                const path = paths?.[column];
                const field =
                  source !== undefined && path !== undefined
                    ? { nodeId: source, path, type: typeOf(rows[0]?.[column]) }
                    : null;
                return (
                  <th
                    key={column}
                    draggable={field !== null}
                    title={field === null ? undefined : t("dataDragHint")}
                    onDragStart={
                      field === null ? undefined : (event) => startFieldDrag(event, field)
                    }
                    className={cn(
                      "px-2 py-1 text-left font-medium whitespace-nowrap",
                      field !== null && DRAGGABLE,
                    )}
                  >
                    {column}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="divide-border divide-y">
            {shown.map((row, index) => (
              <tr key={index}>
                {columns.map((column) => (
                  // Cut to the column's width; the whole value is its tooltip.
                  <td
                    key={column}
                    title={cellText(row[column])}
                    className="max-w-60 truncate px-2 py-1 align-top"
                  >
                    {cellText(row[column])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > SHOWN_ROWS && (
        <button
          type="button"
          className="text-muted-foreground hover:text-foreground text-xs underline-offset-2 hover:underline"
          onClick={() => setEveryRow(!everyRow)}
        >
          {everyRow ? t("dataFewerRows") : t("dataMoreRows", { count: rows.length - SHOWN_ROWS })}
        </button>
      )}
    </div>
  );
}

function SchemaView({ value, source }: { value: Record<string, unknown>; source?: Uuid }) {
  const t = useTranslations("workflows");
  const fields = schemaOf(value);
  if (fields.length === 0) return <p className="text-muted-foreground text-xs">{t("dataEmpty")}</p>;
  return (
    <ul className="space-y-px">
      {fields.map((field) => (
        <FieldRow
          key={field.path}
          name={field.path}
          token={field.type}
          dragged={
            source !== undefined && field.segments !== null
              ? { nodeId: source, path: field.segments, type: field.type }
              : null
          }
        />
      ))}
    </ul>
  );
}

const TYPE_ICON: Record<PlainType, LucideIcon> = {
  text: Type,
  number: Hash,
  yesNo: ToggleLeft,
  date: Calendar,
  id: Fingerprint,
  list: List,
  object: Braces,
  empty: Circle,
  any: Asterisk,
};

/**
 * One field a step hands on: an icon and a word for what it holds, and - where
 * it can be read from - a handle to drag it onto a parameter by.
 */
function FieldRow({
  name,
  token,
  dragged,
}: {
  name: string;
  /** The field's type token, or an observed value's type. */
  token: string;
  dragged: DraggedField | null;
}) {
  const t = useTranslations("workflows");
  const kind = plainType(token);
  const Icon = TYPE_ICON[kind];
  return (
    // Dragging is the pointer's shortcut; the parameter's source picker offers
    // the same fields to a keyboard.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <li
      draggable={dragged !== null}
      title={dragged === null ? undefined : t("dataDragHint")}
      onDragStart={
        dragged === null ? undefined : (event: DragEvent) => startFieldDrag(event, dragged)
      }
      className={cn(
        "flex items-center gap-2 rounded-md px-1.5 py-1",
        dragged !== null && "hover:bg-accent cursor-grab active:cursor-grabbing",
      )}
    >
      <Icon aria-hidden="true" className="text-muted-foreground size-3.5 shrink-0" />
      <span className="truncate font-mono text-[11.5px]">{name}</span>
      <span className="text-muted-foreground ml-auto shrink-0 text-xs">
        {t(`dataType.${kind}`)}
      </span>
    </li>
  );
}

/**
 * The fields a step declares it hands on, from the catalog - what a later step
 * can bind to before any run has shown real data. A port is named only when the
 * step has more than one that carries fields. `fallback` when it declares none.
 */
export function DeclaredOutput({
  definition,
  source,
  intro,
  fallback,
}: {
  definition: NodeDefinition | null;
  source?: Uuid;
  /** What the list is, above it: a step not run yet, or one not tested yet. */
  intro: string;
  fallback: React.ReactNode;
}) {
  const ports = (definition?.ports ?? [])
    .filter((port) => port.kind === "output")
    .map((port) => ({
      port,
      paths: definition === null ? [] : outputFieldPaths(definition, port.id),
    }))
    .filter((entry) => entry.paths.length > 0);
  if (definition === null || ports.length === 0) return fallback;
  return (
    <div className="space-y-1.5">
      <p className="text-muted-foreground text-xs">{intro}</p>
      <ul className="space-y-px">
        {ports.flatMap(({ port, paths }) =>
          paths.map((path) => {
            const type = schemaTypeToken(resolveFieldType(definition, port.id, path));
            const name = path.join(".");
            return (
              <FieldRow
                key={`${port.id}:${name}`}
                name={ports.length > 1 ? `${port.label} · ${name}` : name}
                token={type}
                dragged={source === undefined ? null : { nodeId: source, path, type }}
              />
            );
          }),
        )}
      </ul>
    </div>
  );
}
