"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Plus, Trash2 } from "lucide-react";
import {
  Button,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
import { DIALOG_FORM } from "@/lib/dialog-sizes";
import { NO_FAILURE, submitFailure } from "@/lib/api-error";
import type { ColumnInput, ColumnTypeName, TableVisibility } from "@/types/tables";

const FORM = { fields: ["name"], identifiedBy: "name" } as const;

const COLUMN_TYPES: ColumnTypeName[] = [
  "text",
  "long_text",
  "number",
  "integer",
  "boolean",
  "date",
  "datetime",
  "single_select",
  "multi_select",
];

interface DraftColumn {
  key: string;
  label: string;
  type: ColumnTypeName;
}

/** Name, columns, visibility - a table's creation flow, in one dialog. */
export function CreateTableDialog({
  open,
  onOpenChange,
  onCreate,
  isCreating,
  error,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (input: {
    name: string;
    description: string | null;
    visibility: TableVisibility;
    columns: ColumnInput[];
  }) => void;
  isCreating: boolean;
  error: unknown;
}) {
  const t = useTranslations("tables.create");
  const tErrors = useTranslations("errors");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState<TableVisibility>("private");
  const [columns, setColumns] = useState<DraftColumn[]>([]);

  // `submitFailure`, not `fieldProblems`: a taken name is a 409 `AlreadyExistsError`
  // reporting a fact about the row that exists (`details: {name}`), not a
  // structured `details.fields` list - `identifiedBy` is what routes a conflict
  // like that to the one input that could have produced it. `.toast` is what is
  // left once the name has claimed its own problem - a duplicate column label,
  // say, which the server refuses on `columns` rather than on any input this
  // form renders. `NO_FAILURE` when `error` is absent: `submitFailure` treats
  // anything that is not an `ApiError` - `null` included - as an unexpected
  // failure and fills `.toast` with a fallback sentence, which would render on
  // a dialog that has not failed at all.
  const failure = error != null ? submitFailure(error, FORM, tErrors) : NO_FAILURE;
  const nameProblem = failure.fields.name;

  function reset() {
    setName("");
    setDescription("");
    setVisibility("private");
    setColumns([]);
  }

  function submit() {
    // The only caller is the footer's Create button, which is `disabled` for
    // a blank name - a disabled button fires no click, so `submit` never runs
    // with an empty `name` and this needs no guard of its own.
    onCreate({
      name: name.trim(),
      description: description.trim() || null,
      visibility,
      columns: columns
        .filter((column) => column.label.trim())
        .map((column) => ({
          label: column.label.trim(),
          type: column.type,
        })),
    });
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        // This dialog renders no `DialogTrigger` of its own - `open` is driven
        // entirely by the caller - so Radix only ever invokes this with
        // `false`, from an in-dialog close (Escape, overlay, the close
        // button). Resetting unconditionally is therefore equivalent to
        // resetting on close, without a branch that never takes its other arm.
        reset();
        onOpenChange(next);
      }}
    >
      <DialogContent className={DIALOG_FORM}>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5" data-tour="table-dialog-name">
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t("namePlaceholder")}
              aria-label={t("nameLabel")}
              aria-invalid={nameProblem ? true : undefined}
            />
            {nameProblem && <p className="text-destructive text-xs">{nameProblem}</p>}
          </div>
          <Textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder={t("descriptionPlaceholder")}
            aria-label={t("descriptionLabel")}
          />
          <Select
            value={visibility}
            onValueChange={(next) => setVisibility(next as TableVisibility)}
          >
            <SelectTrigger data-tour="table-dialog-visibility" aria-label={t("visibilityLabel")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="private">{t("visibility.private")}</SelectItem>
              <SelectItem value="team">{t("visibility.team")}</SelectItem>
              <SelectItem value="org">{t("visibility.org")}</SelectItem>
            </SelectContent>
          </Select>
          <div className="space-y-2" data-tour="table-dialog-columns">
            {columns.map((column) => (
              <div key={column.key} className="flex items-center gap-2">
                <Input
                  value={column.label}
                  placeholder={t("columnPlaceholder")}
                  aria-label={t("columnLabel")}
                  onChange={(event) =>
                    setColumns((current) =>
                      current.map((c) =>
                        c.key === column.key ? { ...c, label: event.target.value } : c,
                      ),
                    )
                  }
                />
                <Select
                  value={column.type}
                  onValueChange={(value) =>
                    setColumns((current) =>
                      current.map((c) =>
                        c.key === column.key ? { ...c, type: value as ColumnTypeName } : c,
                      ),
                    )
                  }
                >
                  <SelectTrigger className="w-40" aria-label={t("columnType")}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {COLUMN_TYPES.map((type) => (
                      <SelectItem key={type} value={type}>
                        {t(`types.${type}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  aria-label={t("removeColumn")}
                  onClick={() =>
                    setColumns((current) => current.filter((c) => c.key !== column.key))
                  }
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() =>
                setColumns((current) => [
                  ...current,
                  { key: crypto.randomUUID(), label: "", type: "text" },
                ])
              }
            >
              <Plus className="h-3.5 w-3.5" /> {t("addColumn")}
            </Button>
          </div>
        </div>
        {failure.toast !== null && <p className="text-destructive text-sm">{failure.toast}</p>}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            type="button"
            onClick={submit}
            disabled={isCreating || !name.trim()}
            data-tour="table-dialog-create"
          >
            {t("submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
