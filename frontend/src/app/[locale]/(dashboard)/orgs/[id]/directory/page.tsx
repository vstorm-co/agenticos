"use client";

import { use, useState } from "react";
import { Network } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { DirectoryMappingDialog } from "@/components/orgs/directory-mapping-dialog";
import { DirectoryMappingList } from "@/components/orgs/directory-mapping-list";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { ConfirmDialog } from "@/components/ui";
import { useDirectoryMappings, usePermissions } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";
import type { DirectoryMapping } from "@/types/directory";

interface PageProps {
  params: Promise<{ id: string }>;
}

/**
 * Which directory groups make somebody what in this organization.
 *
 * Reading the mappings takes `members:manage`, so the page is drawn only for a
 * caller holding it; adding or deleting one hands a role out and so takes
 * `roles:manage` as well, and those controls are drawn only for a caller with
 * both. The server refuses either way - this decides what is drawn.
 */
export default function DirectoryPage({ params }: PageProps) {
  const t = useTranslations("directory");
  const { id: orgId } = use(params);
  const { can, isLoaded, error: permissionsError } = usePermissions();
  const canRead = can(Perm.membersManage);
  const canEdit = canRead && can(Perm.rolesManage);
  const { mappings, isLoading, error, remove } = useDirectoryMappings(orgId, canRead);
  const [adding, setAdding] = useState(false);
  const [deleting, setDeleting] = useState<DirectoryMapping | null>(null);

  const header = (
    <PageHeader
      title={t("title")}
      description={t("description")}
      breadcrumbs={[
        { label: t("organizations"), href: ROUTES.ORGS },
        { label: t("members"), href: ROUTES.ORG_MEMBERS(orgId) },
        { label: t("title") },
      ]}
    />
  );

  // `can()` answers false while the permission set loads and after it fails, so
  // deciding on it alone would tell every Owner "not yours" on navigation - the
  // retention page's reasoning (#1420 review).
  if (permissionsError || !isLoaded || !canRead) {
    return (
      <div className="space-y-6">
        {header}
        {permissionsError ? (
          <ErrorState />
        ) : !isLoaded ? (
          <LoadingState variant="skeleton-table" columns={3} rows={4} />
        ) : (
          <EmptyState icon={Network} title={t("notYours")} description={t("askAnAdmin")} />
        )}
      </div>
    );
  }

  const confirmDelete = async (mapping: DirectoryMapping) => {
    await remove.mutateAsync(mapping.id).catch(() => undefined);
    setDeleting(null);
  };

  return (
    <div className="space-y-6">
      {header}

      <section
        data-tour="org-directory"
        className="border-border bg-card text-muted-foreground space-y-2 rounded-xl border p-5 text-sm"
      >
        <p>{t("howItWorks")}</p>
        <p>{t("precedence")}</p>
        <p>{t("removal")}</p>
      </section>

      <DirectoryMappingList
        mappings={mappings}
        isLoading={isLoading}
        error={error}
        canEdit={canEdit}
        onAdd={() => setAdding(true)}
        onDelete={setDeleting}
      />

      {adding && <DirectoryMappingDialog orgId={orgId} onClose={() => setAdding(false)} />}
      {deleting !== null && (
        <ConfirmDialog
          open
          onOpenChange={() => setDeleting(null)}
          title={t("deleteTitle")}
          description={t("deleteBody", { group: deleting.external_group })}
          confirmLabel={t("delete")}
          destructive
          loading={remove.isPending}
          onConfirm={() => confirmDelete(deleting)}
        />
      )}
    </div>
  );
}
