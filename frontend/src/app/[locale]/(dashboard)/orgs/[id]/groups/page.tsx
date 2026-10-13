"use client";

import { use, useState } from "react";
import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { GroupFormDialog } from "@/components/orgs/group-form-dialog";
import { GroupList } from "@/components/orgs/group-list";
import { GroupMembersDialog } from "@/components/orgs/group-members-dialog";
import { Button, ConfirmDialog } from "@/components/ui";
import { useGroups, usePermissions } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";
import type { Group } from "@/types/groups";

interface PageProps {
  params: Promise<{ id: string }>;
}

/**
 * An organization's groups: named sets of its members, shared with as one.
 *
 * Every member may read them, because a group is what somebody picks when they
 * share an agent; creating, renaming, deleting and changing who is in one take
 * `members:manage`, and the controls for them are drawn only for a caller who
 * holds it.
 */
export default function GroupsPage({ params }: PageProps) {
  const t = useTranslations("groups");
  const { id: orgId } = use(params);
  const { can } = usePermissions();
  const canManage = can(Perm.membersManage);
  const { groups, isLoading, error, remove } = useGroups(orgId);
  // `"new"` for the create dialog, a group for the edit one.
  const [editing, setEditing] = useState<Group | "new" | null>(null);
  const [deleting, setDeleting] = useState<Group | null>(null);
  const [viewing, setViewing] = useState<Group | null>(null);

  const confirmDelete = async (group: Group) => {
    await remove.mutateAsync(group.id).catch(() => undefined);
    setDeleting(null);
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("title")}
        description={t("description")}
        breadcrumbs={[
          { label: t("organizations"), href: ROUTES.ORGS },
          { label: t("members"), href: ROUTES.ORG_MEMBERS(orgId) },
          { label: t("title") },
        ]}
        actions={
          canManage ? (
            <Button onClick={() => setEditing("new")} data-tour="org-groups-new">
              <Plus className="h-4 w-4" />
              {t("newGroup")}
            </Button>
          ) : null
        }
      />

      <p
        data-tour="org-groups"
        className="border-border bg-card text-muted-foreground rounded-xl border p-5 text-sm"
      >
        {t("intro")}
      </p>

      <GroupList
        groups={groups}
        isLoading={isLoading}
        error={error}
        canManage={canManage}
        onCreate={() => setEditing("new")}
        onEdit={setEditing}
        onDelete={setDeleting}
        onOpenMembers={setViewing}
      />

      {editing !== null && (
        <GroupFormDialog
          orgId={orgId}
          group={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}
      {viewing !== null && (
        <GroupMembersDialog
          orgId={orgId}
          group={viewing}
          canManage={canManage}
          onClose={() => setViewing(null)}
        />
      )}
      {deleting !== null && (
        <ConfirmDialog
          open
          onOpenChange={() => setDeleting(null)}
          title={t("deleteTitle", { name: deleting.name })}
          description={t("deleteBody")}
          confirmLabel={t("delete")}
          destructive
          loading={remove.isPending}
          onConfirm={() => confirmDelete(deleting)}
        />
      )}
    </div>
  );
}
