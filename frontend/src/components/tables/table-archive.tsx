"use client";

import { Archive, ArchiveRestore } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { SchemaDependents } from "@/components/tables/schema-dependents";
import { Alert, AlertDescription, AlertTitle, Button, ConfirmDialog } from "@/components/ui";
import { getErrorMessage, schemaDependents } from "@/lib/api-error";

/**
 * Asks before a table is archived, saying what that does. A refusal is shown in
 * place rather than toasted, so the list of what still uses the table stays beside
 * the button that would archive it once those are changed.
 */
export function ArchiveTableDialog({
  open,
  onOpenChange,
  name,
  loading,
  error,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  name: string;
  loading: boolean;
  error: unknown;
  onConfirm: () => void;
}) {
  const t = useTranslations("pages.tables.archive");
  const tErrors = useTranslations("errors");

  return (
    <ConfirmDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("title", { name })}
      description={t("description")}
      confirmLabel={t("action")}
      destructive
      loading={loading}
      onConfirm={onConfirm}
    >
      {/* What still uses the table, by name, is what the person can act on; any other
          refusal is the server's own message. */}
      {schemaDependents(error) !== null ? (
        <SchemaDependents error={error} />
      ) : (
        error != null && (
          <p role="alert" className="text-destructive text-sm">
            {getErrorMessage(error, tErrors)}
          </p>
        )
      )}
    </ConfirmDialog>
  );
}

/** The archived table's notice: since when it takes no changes, and the way back for whoever may. */
export function ArchivedTableNotice({
  archivedAt,
  canRestore,
  restoring,
  onRestore,
}: {
  archivedAt: string;
  canRestore: boolean;
  restoring: boolean;
  onRestore: () => void;
}) {
  const t = useTranslations("pages.tables.archive");
  const locale = useLocale();
  const when = new Date(archivedAt).toLocaleDateString(locale, { dateStyle: "medium" });

  return (
    <Alert variant="warning" className="mb-4">
      <Archive aria-hidden="true" className="size-4" />
      {/* One wrapper after the icon: the Alert indents every sibling of its icon,
          which pushed the button's own padding off balance. */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <AlertTitle>{t("noticeTitle", { when })}</AlertTitle>
          <AlertDescription>
            {canRestore ? t("noticeRestorable") : t("noticeReadOnly")}
          </AlertDescription>
        </div>
        {canRestore && (
          <Button variant="outline" size="sm" disabled={restoring} onClick={onRestore}>
            <ArchiveRestore className="h-4 w-4" /> {t("restore")}
          </Button>
        )}
      </div>
    </Alert>
  );
}
