"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useTableRowPolicy } from "@/hooks/use-record-access";
import type { RowPolicy, TableRead } from "@/types/tables";

export function TableRowAccess({ table }: { table: TableRead }) {
  const t = useTranslations("tables.access");
  const current = table.row_policy;
  const [rule, setRule] = useState<RowPolicy["rule"]>(
    table.row_policy_valid === false ? "grants" : (current?.rule ?? "none"),
  );
  const [readColumn, setReadColumn] = useState(current?.view_column_id ?? "");
  const [writeColumn, setWriteColumn] = useState(current?.edit_column_id ?? "");
  const save = useTableRowPolicy(table.id);
  const columns = table.columns.filter(
    (column) => !column.archived && (column.type === "user" || column.type === "multi_user"),
  );
  const canManage = table.can_manage_row_access === true;
  return (
    <section className="border-border space-y-3 border-t pt-5" data-tour="table-row-access">
      <h3 className="font-medium">{t("rowRules")}</h3>
      {table.row_policy_valid === false && (
        <p role="alert" className="text-destructive text-sm">
          {t("invalidPolicy")}
        </p>
      )}
      <p className="text-muted-foreground text-sm">{t("rowRulesHelp")}</p>
      {canManage ? (
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate(
              rule === "assignee"
                ? {
                    ...current,
                    rule,
                    view_column_id: readColumn,
                    edit_column_id: writeColumn,
                  }
                : { rule },
            );
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="table-row-policy">{t("mode")}</Label>
            <Select
              value={rule}
              onValueChange={(value) => setRule(value as RowPolicy["rule"])}
              disabled={save.isPending}
            >
              <SelectTrigger id="table-row-policy">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">{t("modeAll")}</SelectItem>
                <SelectItem value="grants">{t("modeGrants")}</SelectItem>
                <SelectItem value="assignee">{t("modeFields")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <p className="text-muted-foreground text-sm">
            {t(rule === "none" ? "allHelp" : rule === "grants" ? "grantsHelp" : "fieldsHelp")}
          </p>
          {rule === "assignee" && (
            <div className="grid gap-3 sm:grid-cols-2">
              {(
                [
                  { id: "read", value: readColumn, change: setReadColumn },
                  { id: "write", value: writeColumn, change: setWriteColumn },
                ] as const
              ).map((field) => (
                <div className="space-y-1.5" key={field.id}>
                  <Label htmlFor={`row-policy-${field.id}`}>
                    {t(field.id === "read" ? "readField" : "writeField")}
                  </Label>
                  <Select
                    value={field.value}
                    onValueChange={field.change}
                    disabled={save.isPending}
                  >
                    <SelectTrigger id={`row-policy-${field.id}`}>
                      <SelectValue placeholder={t("chooseField")} />
                    </SelectTrigger>
                    <SelectContent>
                      {columns.map((column) => (
                        <SelectItem key={column.id} value={column.id}>
                          {column.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              ))}
            </div>
          )}
          <Button
            type="submit"
            disabled={save.isPending || (rule === "assignee" && (!readColumn || !writeColumn))}
          >
            {t("saveRules")}
          </Button>
        </form>
      ) : table.row_policy_valid !== false ? (
        <p className="text-sm">
          {t(
            current?.rule === "grants"
              ? "modeGrants"
              : current?.rule === "assignee"
                ? "modeFields"
                : "modeAll",
          )}
        </p>
      ) : null}
    </section>
  );
}
