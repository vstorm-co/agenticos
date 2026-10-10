"use client";

import { use, useState } from "react";
import Link from "next/link";
import { AppWindow, BookOpen, Bot, Database, FileText, Pencil, Plug, Users } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { GroupIcon } from "@/components/groups/group-icon";
import { GroupFormDialog } from "@/components/orgs/group-form-dialog";
import { GroupMembersDialog } from "@/components/orgs/group-members-dialog";
import { ErrorState, LoadingState } from "@/components/states";
import { Badge, Button, ListCard, ListCardEmpty } from "@/components/ui";
import { useGroupResources, useGroups, usePermissions } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { useOrgStore } from "@/stores";
import type { GroupResource } from "@/types/groups";
import { Perm } from "@/types/permissions";

interface PageProps {
  params: Promise<{ id: string }>;
}

/** Each kind of thing a group can be given: its icon, its heading, and where it opens. */
const KINDS: readonly {
  kind: GroupResource["kind"];
  icon: typeof Bot;
  heading: string;
  href: (id: string) => string;
}[] = [
  { kind: "agent", icon: Bot, heading: "Agents", href: ROUTES.AGENT_DETAIL },
  { kind: "collection", icon: Database, heading: "Collections", href: ROUTES.RAG_DETAIL },
  { kind: "skill", icon: BookOpen, heading: "Skills", href: () => ROUTES.SKILLS },
  { kind: "context", icon: FileText, heading: "Context", href: () => ROUTES.CONTEXT },
  { kind: "artifact", icon: AppWindow, heading: "Apps", href: ROUTES.ARTIFACT_DETAIL },
  { kind: "mcp_connection", icon: Plug, heading: "McpServers", href: () => ROUTES.MCP_SERVERS },
];

/**
 * One group - a department: who is in it and what it has been given (#2072).
 *
 * What it has been given is what was shared with it, narrowed by the server to
 * what the reader may open; a member of Sales reading Finance's page sees the
 * Finance things they could open anyway, and nothing else.
 */
export default function GroupPage({ params }: PageProps) {
  const t = useTranslations("groups");
  const tErrors = useTranslations("errors");
  const { id } = use(params);
  const orgId = useOrgStore((state) => state.activeOrgId) ?? "";
  const { can } = usePermissions();
  const canManage = can(Perm.membersManage);
  const { groups, isLoading: groupsLoading } = useGroups(orgId);
  const { resources, isLoading, error } = useGroupResources(orgId, id);
  const [editing, setEditing] = useState(false);
  const [members, setMembers] = useState(false);
  const group = groups.find((entry) => entry.id === id);

  if (groupsLoading) return <LoadingState variant="skeleton-panel" rows={3} />;
  if (!group) {
    return <ErrorState title={t("groupNotFound")} description={t("groupNotFoundWhy")} />;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: t("departmentsTitle"), href: ROUTES.GROUPS }, { label: group.name }]}
        title={
          <span className="flex items-center gap-3">
            <GroupIcon icon={group.icon} className="h-10 w-10 [&_svg]:h-5 [&_svg]:w-5" />
            {group.name}
          </span>
        }
        description={group.description ?? undefined}
        actions={
          <>
            <Button variant="outline" onClick={() => setMembers(true)}>
              <Users className="h-4 w-4" />
              {t("memberCount", { count: group.member_count })}
            </Button>
            {canManage && (
              <Button variant="outline" onClick={() => setEditing(true)}>
                <Pencil className="h-4 w-4" />
                {t("editGroup")}
              </Button>
            )}
          </>
        }
      />

      <ListCard
        title={t("whatItHas")}
        counted={isLoading || error ? null : t("resourceCount", { count: resources.length })}
      >
        {error ? (
          <ErrorState description={getErrorMessage(error, tErrors)} />
        ) : isLoading ? (
          <LoadingState variant="skeleton-panel" rows={2} />
        ) : resources.length === 0 ? (
          <ListCardEmpty
            icon={Users}
            title={t("nothingSharedYet", { name: group.name })}
            description={t("nothingSharedYetWhy")}
          />
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {KINDS.map(({ kind, icon: Icon, heading, href }) => {
              const items = resources.filter((resource) => resource.kind === kind);
              if (items.length === 0) return null;
              return (
                <section key={kind} className="space-y-2">
                  <h2 className="text-muted-foreground flex items-center gap-1.5 text-xs font-medium tracking-wide uppercase">
                    <Icon className="h-3.5 w-3.5" aria-hidden />
                    {t(`resource${heading}`)}
                  </h2>
                  <ul className="space-y-1">
                    {items.map((item) => (
                      <li key={item.id} className="flex items-center justify-between gap-2">
                        <Link
                          href={href(item.id)}
                          className="truncate text-sm font-medium hover:underline"
                        >
                          {item.name}
                        </Link>
                        <Badge variant="outline">{t(`level.${item.level}`)}</Badge>
                      </li>
                    ))}
                  </ul>
                </section>
              );
            })}
          </div>
        )}
      </ListCard>

      {editing && <GroupFormDialog orgId={orgId} group={group} onClose={() => setEditing(false)} />}
      {members && (
        <GroupMembersDialog
          orgId={orgId}
          group={group}
          canManage={canManage}
          onClose={() => setMembers(false)}
        />
      )}
    </div>
  );
}
