"use client";

import { useState } from "react";
import { Plus, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { DepartmentTemplates } from "@/components/groups/department-templates";
import { GroupFormDialog } from "@/components/orgs/group-form-dialog";
import { GroupList } from "@/components/orgs/group-list";
import { GroupMembersDialog } from "@/components/orgs/group-members-dialog";
import { Button, ConfirmDialog } from "@/components/ui";
import { useGroups, usePermissions } from "@/hooks";
import { useOrgStore } from "@/stores";
import { Perm } from "@/types/permissions";
import type { Group } from "@/types/groups";

/**
 * The organization's groups - its departments - as a section of their own (#2072).
 *
 * The same groups `/orgs/{id}/groups` manages, for the organization being worked
 * in: a company is organized by department, and a department's people, agents,
 * knowledge and skills are what somebody comes here to see. Anyone may read;
 * `members:manage` creates, edits and deletes.
 */
export default function GroupsPage() {
  const t = useTranslations("groups");
  const orgId = useOrgStore((state) => state.activeOrgId) ?? "";
  const { can } = usePermissions();
  const canManage = can(Perm.membersManage);
  const { groups, isLoading, error, remove } = useGroups(orgId);
  const [editing, setEditing] = useState<Group | "new" | null>(null);
  const [deleting, setDeleting] = useState<Group | null>(null);
  const [viewing, setViewing] = useState<Group | null>(null);
  const [templates, setTemplates] = useState(false);

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("departmentsTitle")}
        description={t("departmentsDescription")}
        actions={
          canManage ? (
            <>
              <Button variant="outline" onClick={() => setTemplates(true)}>
                <Sparkles className="h-4 w-4" />
                {t("addDepartments")}
              </Button>
              <Button onClick={() => setEditing("new")} data-tour="groups-new">
                <Plus className="h-4 w-4" />
                {t("newGroup")}
              </Button>
            </>
          ) : null
        }
      />

      <div data-tour="groups-list">
        <GroupList
          groups={groups}
          isLoading={isLoading}
          error={error}
          canManage={canManage}
          onCreate={() => setTemplates(true)}
          onEdit={setEditing}
          onDelete={setDeleting}
          onOpenMembers={setViewing}
        />
      </div>

      {templates && (
        <DepartmentTemplates orgId={orgId} existing={groups} onClose={() => setTemplates(false)} />
      )}
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
          onConfirm={async () => {
            await remove.mutateAsync(deleting.id).catch(() => undefined);
            setDeleting(null);
          }}
        />
      )}
    </div>
  );
}
