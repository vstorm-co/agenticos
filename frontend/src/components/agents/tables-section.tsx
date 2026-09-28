"use client";

import Link from "next/link";
import { AlertTriangle, Plus, Table2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { CapabilityDetail } from "@/components/agents/capability-settings";
import { SchemaForm } from "@/components/agents/schema-form";
import { Badge, Checkbox, Label, Skeleton } from "@/components/ui";
import { useTables } from "@/hooks";
import { capabilityConfigErrors } from "@/lib/agent-spec";
import type { FieldProblem } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type { CapabilityBindingSpec, CapabilityCatalogEntry, JsonSchema } from "@/types/agents";

/** What a grant lets the agent do - `TableOperation` on the backend. */
export const TABLE_OPERATIONS = ["read", "create", "update", "delete"] as const;
export type TableOperation = (typeof TABLE_OPERATIONS)[number];

/** One table the agent may use - `TableGrant` on the backend. */
export interface TableGrant {
  table_id: string;
  operations: TableOperation[];
}

const OPERATION_KEYS: Record<TableOperation, string> = {
  read: "tablesOperationRead",
  create: "tablesOperationCreate",
  update: "tablesOperationUpdate",
  delete: "tablesOperationDelete",
};

function isOperation(value: unknown): value is TableOperation {
  return TABLE_OPERATIONS.some((operation) => operation === value);
}

/** The grants stored on the binding, keeping only what reads as one. */
export function grantsOf(config: Record<string, unknown>): TableGrant[] {
  const raw = config.tables;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((entry): TableGrant[] => {
    if (typeof entry !== "object" || entry === null) return [];
    const { table_id: tableId, operations } = entry as Record<string, unknown>;
    if (typeof tableId !== "string") return [];
    const ops = Array.isArray(operations) ? operations.filter(isOperation) : [];
    return [{ table_id: tableId, operations: ops.length > 0 ? ops : ["read"] }];
  });
}

interface TablesSectionProps {
  definition: CapabilityCatalogEntry | undefined;
  binding: CapabilityBindingSpec;
  onChange: (binding: CapabilityBindingSpec) => void;
  onToggleEnabled?: () => void;
  readOnly?: boolean;
  disabled?: boolean;
  configProblems?: readonly FieldProblem[];
}

/**
 * Which tables the agent may use, and what it may do in each.
 *
 * A grant is a table and a set of operations, and the operations are the point:
 * an agent that should look customers up must not be able to delete them, and a
 * generated form would draw a list of UUIDs and a list of strings. So each table
 * is a row with the four operations beside it, reading always on - a grant with
 * nothing readable is a grant of nothing. Everything else the capability offers
 * (creating tables) is the generated form below, as on every other panel.
 */
export function TablesSection({
  definition,
  binding,
  onChange,
  onToggleEnabled,
  readOnly,
  disabled,
  configProblems,
}: TablesSectionProps) {
  const t = useTranslations("agents");
  const { tables, isLoading } = useTables({ limit: 100 });
  const configErrors = capabilityConfigErrors(configProblems ?? [], binding.id);

  if (!definition) return null;

  const grants = grantsOf(binding.config);
  const byTable = new Map(grants.map((grant) => [grant.table_id, grant]));
  const known = new Set(tables.map((table) => table.id));
  // Kept on screen rather than dropped, the collection picker's rule: an id that
  // quietly disappears from the form is still in the spec, and publish is where
  // it would surface.
  const orphaned = grants.filter((grant) => !isLoading && !known.has(grant.table_id));

  const write = (next: TableGrant[]) =>
    onChange({ ...binding, config: { ...binding.config, tables: next } });

  const toggleTable = (tableId: string) =>
    write(
      byTable.has(tableId)
        ? grants.filter((grant) => grant.table_id !== tableId)
        : [...grants, { table_id: tableId, operations: ["read"] }],
    );

  const toggleOperation = (tableId: string, operation: TableOperation) =>
    write(
      grants.map((grant) => {
        if (grant.table_id !== tableId) return grant;
        const has = grant.operations.includes(operation);
        const operations = has
          ? grant.operations.filter((one) => one !== operation)
          : TABLE_OPERATIONS.filter((one) => one === operation || grant.operations.includes(one));
        return { ...grant, operations };
      }),
    );

  const controls = (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <Label>{t("tablesGrantsLabel")}</Label>
        <p className="text-muted-foreground text-xs">{t("tablesGrantsDetail")}</p>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      ) : tables.length === 0 ? (
        <div className="border-border text-muted-foreground rounded-lg border border-dashed p-4 text-sm">
          {t("tablesNone")}
        </div>
      ) : (
        <ul className="divide-border border-border divide-y rounded-lg border">
          {tables.map((table) => {
            const grant = byTable.get(table.id);
            return (
              <li key={table.id} className="flex flex-col gap-3 p-3 sm:flex-row sm:items-center">
                <label className="flex min-w-0 flex-1 cursor-pointer items-start gap-3">
                  <Checkbox
                    checked={grant !== undefined}
                    onCheckedChange={() => toggleTable(table.id)}
                    disabled={disabled}
                    aria-label={t("tablesGrantToggle", { name: table.name })}
                    className="mt-0.5"
                  />
                  <span className="min-w-0">
                    <span className="text-foreground flex items-center gap-2 text-sm font-medium">
                      <Table2 className="text-muted-foreground h-3.5 w-3.5 shrink-0" aria-hidden />
                      <span className="truncate">{table.name}</span>
                    </span>
                    {table.description && (
                      <span className="text-muted-foreground block truncate text-xs">
                        {table.description}
                      </span>
                    )}
                  </span>
                </label>
                {grant !== undefined && (
                  <div
                    className="flex flex-wrap gap-1.5"
                    role="group"
                    aria-label={t("tablesOperationsLabel", { name: table.name })}
                  >
                    {TABLE_OPERATIONS.map((operation) => {
                      const on = grant.operations.includes(operation);
                      // Reading is what every other operation starts from.
                      const fixed = operation === "read";
                      return (
                        <button
                          key={operation}
                          type="button"
                          aria-pressed={on}
                          disabled={disabled || fixed}
                          onClick={() => toggleOperation(table.id, operation)}
                          className={cn(
                            "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
                            on
                              ? "border-primary/40 bg-primary/10 text-foreground"
                              : "border-border text-muted-foreground hover:text-foreground",
                            (disabled || fixed) && "cursor-default",
                          )}
                        >
                          {t(OPERATION_KEYS[operation])}
                        </button>
                      );
                    })}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {orphaned.map((grant) => (
        <p
          key={grant.table_id}
          className="text-foreground/70 flex items-center gap-1.5 text-xs"
          role="status"
        >
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden />
          {t("tablesGrantOrphaned")}
          <Badge variant="outline" className="font-mono">
            {grant.table_id}
          </Badge>
        </p>
      ))}

      <Link
        href={ROUTES.TABLES}
        className="text-muted-foreground inline-flex items-center gap-1.5 text-xs underline underline-offset-4"
      >
        <Plus className="h-3.5 w-3.5" aria-hidden />
        {t("tablesManage")}
      </Link>

      {definition.config_schema && (
        <SchemaForm
          idPrefix={binding.id}
          schema={withoutGrants(definition.config_schema)}
          value={binding.config}
          disabled={disabled}
          errors={configErrors}
          onChange={(config) => onChange({ ...binding, config: { ...config, tables: grants } })}
        />
      )}
    </div>
  );

  return (
    <CapabilityDetail
      binding={binding}
      definition={definition}
      onChange={onChange}
      onToggleEnabled={onToggleEnabled}
      readOnly={readOnly}
      disabled={disabled}
      configProblems={configProblems}
      settingsExtra={controls}
      hideConfigForm
    />
  );
}

/** The schema with the grants taken out: this panel draws them itself. */
function withoutGrants(schema: JsonSchema): JsonSchema {
  const properties = Object.fromEntries(
    Object.entries(schema.properties ?? {}).filter(([name]) => name !== "tables"),
  );
  return { ...schema, properties };
}
