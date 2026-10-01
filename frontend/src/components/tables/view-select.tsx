"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Pencil, Plus, Trash2 } from "lucide-react";
import {
  Button,
  ConfirmDialog,
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
} from "@/components/ui";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";
import { NO_FAILURE, submitFailure } from "@/lib/api-error";
import type { TableViewRead, ViewKind, ViewVisibility } from "@/types/tables";

const NAME_FORM = { fields: ["name"], identifiedBy: "name" } as const;

/**
 * A dialog that names a view and saves it: the create and the rename dialog.
 *
 * `onSave` settles with the write's own outcome. The dialog closes only once
 * it resolves; a refusal keeps it open with the typed name, the name problem
 * (a taken name, 409) beside the input and anything else below it.
 */
function ViewNameDialog({
  open,
  onOpenChange,
  title,
  initialName,
  onSave,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  initialName: string;
  onSave: (name: string) => Promise<unknown>;
  children?: ReactNode;
}) {
  const t = useTranslations("pages.tables.views");
  const tErrors = useTranslations("errors");
  const [name, setName] = useState(initialName);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);

  // Each opening starts from the caller's name and no error: a refusal from
  // the last time the dialog was open is not about what is typed now.
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setName(initialName);
      setError(null);
      setSaving(false);
    }
  }
  // Bumped on every open and close, so a save still in flight from an earlier
  // opening - one cancelled while it ran - settles without touching this one.
  const opening = useRef(0);
  useEffect(() => {
    opening.current += 1;
  }, [open]);

  // `NO_FAILURE` when there is no error: `submitFailure` reads anything that
  // is not an `ApiError`, `null` included, as an unexpected failure.
  const failure = error != null ? submitFailure(error, NAME_FORM, tErrors) : NO_FAILURE;
  const nameProblem = failure.fields.name;

  async function save() {
    const mine = opening.current;
    setSaving(true);
    setError(null);
    let failed: unknown = null;
    let ok = false;
    try {
      await onSave(name.trim());
      ok = true;
    } catch (caught) {
      failed = caught;
    }
    if (opening.current !== mine) return;
    setSaving(false);
    if (ok) onOpenChange(false);
    else setError(failed);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={DIALOG_CONFIRM}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t("namePlaceholder")}
              aria-label={t("namePlaceholder")}
              aria-invalid={nameProblem ? true : undefined}
            />
            {nameProblem && <p className="text-destructive text-xs">{nameProblem}</p>}
          </div>
          {children}
        </div>
        {failure.toast !== null && <p className="text-destructive text-sm">{failure.toast}</p>}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button type="button" disabled={!name.trim() || saving} onClick={() => void save()}>
            {t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * The saved-view picker for the active kind, and the active view's rename and
 * delete controls. Gated on the view's own `can_manage` and `can_delete`, never
 * on `table.can_edit`: a table editor another member shared a view with may not
 * silently repoint their saved filter, and an owner who lost edit access may
 * still delete their view but not reshape it (see
 * `docs/virtual-tables.md#saved-views`).
 *
 * `onCreate` and `onRename` settle with their write's outcome, which is what
 * decides whether their dialog closes.
 */
export function ViewSelect({
  kind,
  views,
  activeViewId,
  onSelect,
  onCreate,
  onRename,
  onDelete,
  canCreate,
}: {
  kind: ViewKind;
  views: TableViewRead[];
  activeViewId: string | null;
  onSelect: (viewId: string | null) => void;
  onCreate: (name: string, visibility: ViewVisibility) => Promise<unknown>;
  onRename: (viewId: string, name: string) => Promise<unknown>;
  onDelete: (viewId: string) => void;
  canCreate: boolean;
}) {
  const t = useTranslations("pages.tables.views");
  const [createOpen, setCreateOpen] = useState(false);
  const [draftVisibility, setDraftVisibility] = useState<ViewVisibility>("private");
  const [renaming, setRenaming] = useState<TableViewRead | null>(null);
  const [deleting, setDeleting] = useState<TableViewRead | null>(null);

  const active = views.find((view) => view.id === activeViewId) ?? null;

  return (
    <div className="flex items-center gap-1">
      {/* The view and saving the screen as a new one read as one control. */}
      <div className="border-border bg-background flex h-8 items-stretch rounded-lg border">
        <Select
          value={activeViewId ?? "__default__"}
          onValueChange={(id) => onSelect(id === "__default__" ? null : id)}
        >
          <SelectTrigger
            className="h-full w-40 rounded-r-none border-0 bg-transparent text-sm shadow-none"
            aria-label={t("selectViewFor", { kind })}
          >
            <SelectValue placeholder={t("unsavedView")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__default__">{t("unsavedView")}</SelectItem>
            {views.map((view) => (
              <SelectItem key={view.id} value={view.id}>
                {view.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {canCreate && (
          <button
            type="button"
            data-tour="table-view-new"
            onClick={() => {
              setDraftVisibility("private");
              setCreateOpen(true);
            }}
            aria-label={t("newView")}
            title={t("newView")}
            className="border-border text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring flex w-8 items-center justify-center rounded-r-lg border-l outline-none focus-visible:ring-2"
          >
            <Plus className="h-4 w-4" />
          </button>
        )}
      </div>
      {active?.can_manage && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="text-muted-foreground size-8"
          aria-label={t("rename")}
          title={t("rename")}
          onClick={() => setRenaming(active)}
        >
          <Pencil className="h-4 w-4" />
        </Button>
      )}
      {active?.can_delete && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="text-muted-foreground size-8"
          aria-label={t("delete")}
          title={t("delete")}
          onClick={() => setDeleting(active)}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      )}

      <ViewNameDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        title={t("newView")}
        initialName=""
        onSave={(name) => onCreate(name, draftVisibility)}
      >
        <Select
          value={draftVisibility}
          onValueChange={(next) => setDraftVisibility(next as ViewVisibility)}
        >
          <SelectTrigger aria-label={t("visibilityLabel")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="private">{t("private")}</SelectItem>
            <SelectItem value="shared">{t("shared")}</SelectItem>
          </SelectContent>
        </Select>
      </ViewNameDialog>

      <ViewNameDialog
        open={renaming !== null}
        onOpenChange={(open) => !open && setRenaming(null)}
        title={t("rename")}
        initialName={renaming?.name ?? ""}
        // Rendered open only while `renaming` is set, so it is set whenever Save runs.
        onSave={(name) => onRename(renaming!.id, name)}
      />

      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={t("deleteTitle")}
        description={t("deleteDescription", { name: deleting?.name ?? "" })}
        confirmLabel={t("delete")}
        destructive
        onConfirm={() => {
          // The confirm button only exists while `ConfirmDialog` is open, and
          // it is only open while `deleting` is set (`open={!!deleting}`
          // above), so `deleting` is never null here.
          onDelete(deleting!.id);
          setDeleting(null);
        }}
      />
    </div>
  );
}
