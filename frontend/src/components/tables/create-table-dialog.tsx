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
import { fieldProblems } from "@/lib/api-error";
import type { ColumnInput, ColumnTypeName, TableVisibility } from "@/types/tables";

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
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState<TableVisibility>("private");
  const [columns, setColumns] = useState<DraftColumn[]>([]);

  const problems = fieldProblems(error);
  const nameProblem = problems.find((problem) => problem.field === "name")?.message;

  function reset() {
    setName("");
    setDescription("");
    setVisibility("private");
    setColumns([]);
  }

  function submit() {
    if (!name.trim()) return;
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
        if (!next) reset();
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
