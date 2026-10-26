"use client";

import { use, useState } from "react";
import Link from "next/link";
import {
  AppWindow,
  BookOpen,
  Bot,
  Database,
  FileText,
  Pencil,
  Plug,
  Share2,
  Users,
} from "lucide-react";
import { useTranslations } from "next-intl";

import { AgentFace } from "@/components/dashboard/agent-face";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/dashboard/page-header";
import { AddToGroupDialog } from "@/components/groups/add-to-group-dialog";
import { DepartmentBudget } from "@/components/groups/department-budget";
import { DepartmentQuality } from "@/components/groups/department-quality";
import { GroupIcon } from "@/components/groups/group-icon";
import { GroupFormDialog } from "@/components/orgs/group-form-dialog";
import { GroupMembersDialog } from "@/components/orgs/group-members-dialog";
import { ErrorState } from "@/components/states";
import { Button, ListCard, ListCardEmpty } from "@/components/ui";
import { useGroupMembers, useGroupResources, useGroups, usePermissions } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { useAuthStore, useOrgStore } from "@/stores";
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
  const ts = useTranslations("states");
  const { id } = use(params);
  const orgId = useOrgStore((state) => state.activeOrgId) ?? "";
  const { can } = usePermissions();
  const canManage = can(Perm.membersManage);
  const { groups, isLoading: groupsLoading } = useGroups(orgId);
  const { resources, isLoading, error } = useGroupResources(orgId, id);
  const userId = useAuthStore((state) => state.user?.id);
  const { members: people } = useGroupMembers(orgId, id);
  // A lead reads their department's answer quality without `runs:view` (#2101).
  const leads = people.some((person) => person.user_id === userId && person.is_lead);
  const seesRuns = can(Perm.runsView);
  const [editing, setEditing] = useState(false);
  const [members, setMembers] = useState(false);
  const [adding, setAdding] = useState(false);
  const group = groups.find((entry) => entry.id === id);

  if (groupsLoading)
    return (
      <div className="space-y-6" role="status" aria-label={ts("loading")}>
        <div className="space-y-3">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-9 w-64" />
        </div>
        {(seesRuns || leads) && (
          <div className="grid gap-4 lg:grid-cols-2">
            <Skeleton className="h-64 w-full rounded-2xl" />
            <Skeleton className="h-64 w-full rounded-2xl" />
          </div>
        )}
        <ListCard title={t("whatItHas")} counted={null}>
          <ResourceSkeleton />
        </ListCard>
      </div>
    );
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
            <Button variant="outline" onClick={() => setMembers(true)} data-tour="group-members">
              <Users className="h-4 w-4" />
              {t("memberCount", { count: group.member_count })}
            </Button>
            <Button variant="outline" onClick={() => setAdding(true)} data-tour="group-add-to">
              <Share2 className="h-4 w-4" />
              {t("addToGroup")}
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

      {(seesRuns || leads) && (
        <div className="grid gap-4 lg:grid-cols-2">
          {seesRuns && <DepartmentBudget orgId={orgId} group={group} />}
          <DepartmentQuality orgId={orgId} group={group} />
        </div>
      )}

      <ListCard
        title={t("whatItHas")}
        counted={isLoading || error ? null : t("resourceCount", { count: resources.length })}
      >
        {error ? (
          <ErrorState description={getErrorMessage(error, tErrors)} />
        ) : isLoading ? (
          <ResourceSkeleton />
        ) : resources.length === 0 ? (
          <ListCardEmpty
            icon={Users}
            title={t("nothingSharedYet", { name: group.name })}
            description={t("nothingSharedYetWhy")}
            cta={{ label: t("addToGroup"), onClick: () => setAdding(true) }}
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
                  <ul className="space-y-0.5">
                    {items.map((item) => (
                      <li key={item.id}>
                        {/* The thing's face where it has one - an agent - and its
                            kind's mark otherwise, the way the dialog that added
                            it drew it. */}
                        <Link
                          href={href(item.id)}
                          className="hover:bg-accent/50 flex items-center gap-2.5 rounded-lg px-2 py-1.5"
                        >
                          {item.kind === "agent" ? (
                            <AgentFace agentId={item.id} className="size-6 shrink-0" />
                          ) : (
                            <span className="bg-muted grid size-6 shrink-0 place-items-center rounded-md">
                              <Icon className="text-muted-foreground h-3.5 w-3.5" aria-hidden />
                            </span>
                          )}
                          <span className="min-w-0 flex-1 truncate text-sm font-medium">
                            {item.name}
                          </span>
                          <span className="bg-muted text-muted-foreground shrink-0 rounded-full px-2 py-0.5 text-xs">
                            {t(`level.${item.level}`)}
                          </span>
                        </Link>
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
      {adding && <AddToGroupDialog orgId={orgId} group={group} onClose={() => setAdding(false)} />}
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

function ResourceSkeleton() {
  return (
    <div className="grid gap-4 md:grid-cols-2" aria-hidden>
      {[0, 1].map((kind) => (
        <section key={kind} className="space-y-2">
          <Skeleton className="h-4 w-32" />
          {[0, 1, 2].map((row) => (
            <Skeleton key={row} className="h-7 w-full" />
          ))}
        </section>
      ))}
    </div>
  );
}
