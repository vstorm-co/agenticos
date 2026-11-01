"use client";

import { useEffect, useRef, useState } from "react";
import { BookOpen, Pencil, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Textarea,
} from "@/components/ui";
import { useTable } from "@/hooks/use-tables";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_FORM } from "@/lib/dialog-sizes";
import { currentColumns } from "./column-inputs";
import { DOCUMENT_TEMPLATE_KEYS } from "./document-template-field";
import type { ColumnInput, DocumentTemplate } from "@/types/tables";

/** The library is loaded only when opened; saved bodies belong to this table column. */
export function DocumentTemplates({
  tableId,
  columnId,
  body,
  onApply,
}: {
  tableId: string;
  columnId: string;
  body: string;
  onApply: (body: string) => void;
}) {
  const t = useTranslations("tables.markdown");
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button type="button" variant="ghost" size="sm" onClick={() => setOpen(true)}>
        <BookOpen className="size-4" aria-hidden />
        {t("library")}
      </Button>
      {open && (
        <TemplateLibrary
          tableId={tableId}
          columnId={columnId}
          body={body}
          onClose={() => setOpen(false)}
          onApply={(value) => {
            setOpen(false);
            onApply(value);
          }}
        />
      )}
    </>
  );
}

function TemplateLibrary({
  tableId,
  columnId,
  body,
  onClose,
  onApply,
}: {
  tableId: string;
  columnId: string;
  body: string;
  onClose: () => void;
  onApply: (body: string) => void;
}) {
  const t = useTranslations("tables.markdown");
  const errors = useTranslations("errors");
  const { table, changeSchema, isLoading, error: loadError } = useTable(tableId);
  const column = table?.columns.find((item) => item.id === columnId);
  const [editing, setEditing] = useState<DocumentTemplate | null>(null);
  const [name, setName] = useState("");
  const nameField = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (editing) nameField.current?.focus();
  }, [editing]);
  const [draft, setDraft] = useState("");
  const [asDefault, setAsDefault] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const templates = column?.document_templates ?? [];
  const busy = changeSchema.isPending;
  const canEdit = Boolean(table?.can_edit);
  const save = async (patch: Partial<ColumnInput>): Promise<boolean> => {
    if (!table || !column || !table.can_edit) return false;
    setError(null);
    try {
      await changeSchema.mutateAsync({
        expected_version: table.schema_version,
        columns: currentColumns(table.columns).map((item) =>
          item.id === columnId ? { ...item, ...patch } : item,
        ),
      });
      return true;
    } catch (cause) {
      setError(getErrorMessage(cause, errors));
      return false;
    }
  };
  const edit = (template: DocumentTemplate, makeDefault = false) => {
    setEditing(template);
    setName(template.name);
    setDraft(template.body);
    setAsDefault(makeDefault || column?.default_template_id === template.id);
  };
  const write = async () => {
    if (!editing || !name.trim() || !column) return;
    const next = { id: editing.id, name: name.trim(), body: draft };
    const values = templates.some((item) => item.id === next.id)
      ? templates.map((item) => (item.id === next.id ? next : item))
      : [...templates, next];
    if (
      await save({
        document_templates: values,
        default_template_id: asDefault
          ? next.id
          : column.default_template_id === next.id
            ? null
            : column.default_template_id,
        ...(column.default_template_id === next.id && !asDefault ? { default: null } : {}),
      })
    )
      setEditing(null);
  };
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) onClose();
      }}
    >
      <DialogContent data-document-templates={columnId} className={DIALOG_FORM}>
        <DialogHeader>
          <DialogTitle>{t("library")}</DialogTitle>
          <DialogDescription>{t("libraryHint")}</DialogDescription>
        </DialogHeader>
        {(error || loadError) && (
          <p role="alert" className="text-destructive text-sm">
            {error ?? getErrorMessage(loadError, errors)}
          </p>
        )}
        {isLoading && <p className="text-muted-foreground text-sm">{t("loadingTemplates")}</p>}
        {editing ? (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void write();
            }}
            className="space-y-4"
          >
            <div className="space-y-1.5">
              <Label htmlFor="document-template-name">{t("templateName")}</Label>
              <Input
                id="document-template-name"
                value={name}
                maxLength={64}
                onChange={(event) => setName(event.target.value)}
                required
                ref={nameField}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="document-template-body">{t("templateBody")}</Label>
              <Textarea
                id="document-template-body"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                maxLength={100000}
                rows={10}
                className="max-h-[40dvh] font-mono text-sm"
              />
            </div>
            <Label className="flex items-center gap-2">
              <Checkbox
                checked={asDefault}
                onCheckedChange={(checked) => setAsDefault(checked === true)}
              />
              {t("makeDefault")}
            </Label>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => setEditing(null)}
              >
                {t("backToTemplates")}
              </Button>
              <Button type="submit" disabled={busy || !canEdit || !name.trim()}>
                {t("saveTemplate")}
              </Button>
            </DialogFooter>
          </form>
        ) : (
          <>
            <div className="max-h-[55dvh] space-y-4 overflow-y-auto pr-1">
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-sm font-medium">{t("yourTemplates")}</h3>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={!canEdit || busy || templates.length >= 10}
                    onClick={() => edit({ id: crypto.randomUUID(), name: "", body })}
                  >
                    <Plus className="size-4" aria-hidden />
                    {t("newTemplate")}
                  </Button>
                </div>
                {templates.map((template) => (
                  <div key={template.id} className="flex flex-col gap-2 rounded-lg border p-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{template.name}</p>
                      {column?.default_template_id === template.id && (
                        <p className="text-muted-foreground text-xs">{t("defaultTemplate")}</p>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center justify-end gap-1">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => onApply(template.body)}
                      >
                        {t("useTemplate")}
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        disabled={busy || !canEdit}
                        onClick={() => void save({ default_template_id: template.id })}
                      >
                        {t("setDefault")}
                      </Button>
                      <Button
                        type="button"
                        size="icon"
                        variant="ghost"
                        aria-label={t("editTemplate", { name: template.name })}
                        disabled={busy || !canEdit}
                        onClick={() => edit(template)}
                      >
                        <Pencil className="size-4" aria-hidden />
                      </Button>
                      <Button
                        type="button"
                        size="icon"
                        variant="ghost"
                        aria-label={t("deleteTemplate", { name: template.name })}
                        disabled={busy || !canEdit}
                        onClick={() =>
                          void save({
                            document_templates: templates.filter((item) => item.id !== template.id),
                            ...(column?.default_template_id === template.id
                              ? { default_template_id: null, default: null }
                              : {}),
                          })
                        }
                      >
                        <Trash2 className="size-4" aria-hidden />
                      </Button>
                    </div>
                  </div>
                ))}
                {!templates.length && (
                  <p className="text-muted-foreground py-3 text-sm">{t("noCustomTemplates")}</p>
                )}
              </div>
              <div className="space-y-2">
                <h3 className="text-sm font-medium">{t("chooseTemplate")}</h3>
                {DOCUMENT_TEMPLATE_KEYS.map((key) => (
                  <div
                    key={key}
                    className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2"
                  >
                    <span className="text-sm">{t(`templates.${key}.label`)}</span>
                    <div className="flex gap-1">
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        onClick={() => onApply(t(`templates.${key}.body`))}
                      >
                        {t("useTemplate")}
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        disabled={!canEdit || busy}
                        onClick={() =>
                          edit(
                            {
                              id: crypto.randomUUID(),
                              name: t(`templates.${key}.label`),
                              body: t(`templates.${key}.body`),
                            },
                            true,
                          )
                        }
                      >
                        {t("customizeTemplate")}
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
              {column?.default != null && (
                <div className="flex items-center justify-between gap-3 border-t pt-3">
                  <span className="text-muted-foreground text-xs">{t("defaultActive")}</span>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    disabled={!canEdit || busy}
                    onClick={() => void save({ default_template_id: null, default: null })}
                  >
                    {t("clearDefault")}
                  </Button>
                </div>
              )}
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" disabled={busy} onClick={onClose}>
                {t("done")}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
