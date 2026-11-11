"use client";

import { use, useEffect, useId, useMemo, useState } from "react";
import Link from "next/link";
import {
  Building2,
  Sparkles,
  Radar,
  Link2,
  MailPlus,
  Network,
  Archive,
  ShieldCheck,
  Trash2,
  UserPlus,
  Users,
} from "lucide-react";

import { getErrorMessage } from "@/lib/api-error";
import { ErrorState } from "@/components/states";
import {
  InviteLinkDialog,
  InviteMemberDialog,
  OrgApprovalWaiver,
  OrgAssistant,
  OrgPublicAttribution,
  OrgPublicLiveData,
  OrgProactivity,
  OrgSystemAgents,
  OrgSpendingLimit,
  OrgVoiceSettings,
} from "@/components/teams";
import { SetupIndicator } from "@/components/settings/setup-indicator";
import { useSystemAgents } from "@/hooks/use-system-agents";
import {
  voiceSetupHints,
  proactivitySetupHints,
  systemAgentSetupHints,
  architectSetupHints,
  type SetupHint,
} from "@/lib/setup-hints";
import { PageHeader } from "@/components/dashboard/page-header";
import { ForgetMemberMemory } from "@/components/memory/forget-member-memory";
import { DirectoryBadge } from "@/components/orgs/directory-badge";
import { DiscordBadge } from "@/components/orgs/discord-badge";
import {
  Badge,
  Button,
  DataTable,
  ConfirmDialog,
  EntityAvatar,
  ListCard,
  ListCardEmpty,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  type Column,
} from "@/components/ui";
import {
  useUrlState,
  useAssignableRoles,
  useAuth,
  useInvitations,
  useMembers,
  useOrganizations,
  usePermissions,
  useRoleCatalog,
} from "@/hooks";
import { Perm } from "@/types/permissions";
import type { OrganizationMember, OrgRole } from "@/types";
import { formatDate } from "@/lib/utils";
import { ROUTES } from "@/lib/constants";
import { useOrgStore } from "@/stores";
import { useAssistant } from "@/hooks/use-assistant";
import { OrganizationProfileSettings } from "@/components/teams/organization-profile-settings";
import { useTenantId } from "@/hooks/use-organizations";

interface PageProps {
  params: Promise<{ id: string }>;
}

import { useLocale, useTranslations } from "next-intl";
const ROLE_VARIANT: Record<OrgRole, "default" | "secondary" | "outline"> = {
  owner: "default",
  admin: "secondary",
  builder: "secondary",
  operator: "secondary",
  member: "outline",
  viewer: "outline",
};

export default function OrgMembersPage({ params }: PageProps) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("pages.orgs");
  const tc = useTranslations("common");
  const tSetup = useTranslations("setupHints");
  const setupId = useId();
  const tGroups = useTranslations("groups");
  const tDirectory = useTranslations("directory");
  const tDiscord = useTranslations("discordRoles");
  const locale = useLocale();
  const { id } = use(params);
  const { user } = useAuth();
  const { members, total, isLoading, error, fetchMembers, changeRole, removeMember } =
    useMembers(id);
  const { invitations, fetchInvitations, revokeInvitation } = useInvitations(id);
  const { orgs, fetchOrgs } = useOrganizations();
  const [inviteOpen, setInviteOpen] = useState(false);
  const [removing, setRemoving] = useState<OrganizationMember | null>(null);
  const [removingBusy, setRemovingBusy] = useState(false);
  const [linkOpen, setLinkOpen] = useState(false);

  useEffect(() => {
    fetchMembers();
    fetchInvitations();
    fetchOrgs();
  }, [fetchMembers, fetchInvitations, fetchOrgs]);

  const { can, isLoading: permissionsLoading } = usePermissions();
  const assignable = useAssignableRoles();
  // Every row's role control is derived from the catalog, so a catalog that
  // never arrived leaves the table showing labels - the same pixels a Viewer
  // sees, and a different fact. Said, above the table (#1028).
  const { error: rolesError } = useRoleCatalog();
  const org = orgs.find((o) => o.id === id);
  // Derived from the server's permission catalog rather than a role-name check,
  // so adding a role that may manage members needs no change here.
  const canManage = can(Perm.membersManage);
  const canSettings = can(Perm.orgSettings);
  const { assistant } = useAssistant();
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const tenantId = useTenantId();
  const [tabParam, setTabParam] = useUrlState("tab");
  const canConfigureAssistant =
    activeOrgId === id && !!assistant?.can_configure && !!assistant.agent_id;
  const canSystemServices = can(Perm.budgetsManage) && tenantId === id;
  const { roles: systemRoles, error: systemRolesError } = useSystemAgents(canSystemServices);
  const hints: Record<string, SetupHint[]> = {
    profile: org && canSettings ? voiceSetupHints(org) : [],
    proactivity: org && can(Perm.budgetsManage) ? proactivitySetupHints(org) : [],
    assistant: [
      ...(canConfigureAssistant && assistant ? architectSetupHints(assistant) : []),
      ...(canSystemServices && !systemRolesError
        ? (systemRoles ?? []).flatMap(systemAgentSetupHints)
        : []),
    ],
  };
  const sections = [
    { id: "members", label: "members", icon: Users, visible: true },
    { id: "profile", label: "tabProfile", icon: Building2, visible: true },
    {
      id: "governance",
      label: "tabGovernance",
      icon: ShieldCheck,
      visible: can(Perm.budgetsManage) || can(Perm.approvalsDecide) || canSettings,
    },
    {
      id: "proactivity",
      label: "tabProactivity",
      icon: Radar,
      visible: tenantId !== id || can(Perm.budgetsManage) || canSettings,
    },
    {
      id: "assistant",
      label: "tabAssistant",
      icon: Sparkles,
      visible: canConfigureAssistant || canSystemServices,
    },
  ].filter((section) => section.visible);
  // Existing bookmarks and settings links keep opening the moved voice controls.
  const requestedTab = tabParam === "voice" && canSettings ? "profile" : tabParam;
  const tab = sections.find((section) => section.id === requestedTab)?.id ?? "members";
  const pendingInvitations = invitations.filter((i) => i.status === "pending");

  const columns = useMemo<Column<OrganizationMember>[]>(() => {
    const cols: Column<OrganizationMember>[] = [
      {
        key: "member",
        className: "pl-5 @max-md/table:w-full @max-md/table:pb-1",
        header: t("member"),
        cell: (m) => {
          const isSelf = m.user_id === user?.id;
          return (
            <div className="flex min-w-0 items-center gap-3">
              <EntityAvatar
                seed={m.user_id}
                name={m.full_name || m.email}
                imageSrc={`/api/users/avatar/${m.user_id}`}
                hasImage={!!m.avatar_url}
                colorSlot={m.avatar_color}
                className="h-8 w-8 shrink-0 text-[11px]"
                ariaHidden
              />
              <div className="max-w-28 min-w-0 sm:max-w-xs @max-md/table:max-w-none">
                <p className="text-foreground truncate text-sm font-medium">
                  {m.full_name || m.email.split("@")[0]}
                  {isSelf && <span className="text-muted-foreground font-normal"> {t("you")}</span>}
                </p>
                <p className="text-muted-foreground truncate text-xs" title={m.email}>
                  {m.email}
                </p>
              </div>
            </div>
          );
        },
      },
      {
        key: "role",
        header: t("role2"),
        className: "@max-md/table:flex-1 @max-md/table:pl-5 @max-md/table:pt-1",
        cell: (m) => {
          const isSelf = m.user_id === user?.id;
          const isOwner = m.role === "owner";
          // Two different questions, and a selector needs both answered. `assignable`
          // is about the *requester*: which roles their own strictly outranks, so an
          // empty list is a dropdown with nothing in it (#1028). `can_change_role` is
          // the server's answer about *this target*: whether the requester outranks
          // the role the member holds now, which is what stops a peer Admin getting a
          // selector whose only result is a 403 toast (#700).
          //
          // A membership the directory or Discord sync made says so beside the
          // role, since changing that role here is also what takes the row off the sync.
          const synced =
            m.source === "directory" ? (
              <DirectoryBadge explanation={tDirectory("memberHint")} />
            ) : m.source === "discord" ? (
              <DiscordBadge explanation={tDiscord("memberHint")} />
            ) : null;
          if (canManage && !isOwner && !isSelf && m.can_change_role && assignable.length > 0) {
            return (
              <div className="flex items-center gap-2">
                <Select value={m.role} onValueChange={(v) => changeRole(m.user_id, v as OrgRole)}>
                  <SelectTrigger
                    className="h-8 w-32 capitalize"
                    aria-label={t("roleFor", { email: m.email })}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {/* The row's own role, when this caller cannot assign it -
                      a peer Admin, to an Admin. Present because Radix draws the
                      chosen item's text in the trigger, so without it the
                      control renders blank; disabled because assigning it is
                      what they may not do. Demoting that peer still is:
                      `change_role` judges the role being handed out, not the
                      one being replaced (#1028). */}
                    {!assignable.includes(m.role) && (
                      <SelectItem value={m.role} disabled className="capitalize">
                        {m.role}
                      </SelectItem>
                    )}
                    {assignable.map((option) => (
                      <SelectItem key={option} value={option} className="capitalize">
                        {option}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {synced}
              </div>
            );
          }
          return (
            <div className="flex items-center gap-2">
              <Badge variant={ROLE_VARIANT[m.role]} className="capitalize">
                {m.role}
              </Badge>
              {synced}
            </div>
          );
        },
      },
      {
        key: "joined",
        header: t("joined"),
        hideBelow: "md",
        className: "@max-md/table:hidden",
        cell: (m) => (
          <span className="text-muted-foreground text-sm">{formatDate(m.joined_at, locale)}</span>
        ),
      },
    ];

    if (canManage) {
      cols.push({
        key: "actions",
        header: "",
        align: "right",
        className: "w-0 pr-5 @max-md/table:w-auto @max-md/table:pt-1",
        cell: (m) => {
          const isSelf = m.user_id === user?.id;
          const isOwner = m.role === "owner";
          return (
            <div className="flex items-center justify-end gap-1">
              {/* Offered for the owner and for yourself too: erasing what agents
                  wrote about somebody is not a change to their standing in the
                  organization the way removing them is. */}
              <ForgetMemberMemory userId={m.user_id} name={m.full_name || m.email} />
              {!isOwner && !isSelf && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-muted-foreground hover:text-destructive"
                  onClick={() => setRemoving(m)}
                  aria-label={tc("removeNamed", { name: m.full_name || m.email })}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </div>
          );
        },
      });
    }

    return cols;
  }, [canManage, user?.id, assignable, changeRole, removeMember, tDirectory]);

  return (
    <div className="flex flex-1 flex-col space-y-4">
      <PageHeader
        title={org?.name ?? t("members")}
        description={t("membersDescription", { count: total })}
        breadcrumbs={[
          { label: t("organizations"), href: ROUTES.ORGS },
          { label: org?.name ?? t("members2") },
        ]}
        secondaryActions={
          // Wrapping, because four links are wider than a phone (#2075).
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" asChild>
              <Link href={ROUTES.ORG_ROLES(id)}>
                <ShieldCheck className="h-4 w-4" />
                {t("roles")}
              </Link>
            </Button>
            {/* For everybody, like the roles: any member reads the groups, because a
                group is what they pick when sharing something. */}
            <Button variant="outline" asChild>
              <Link href={ROUTES.ORG_GROUPS(id)}>
                <Users className="h-4 w-4" />
                {tGroups("title")}
              </Link>
            </Button>
            {/* The mappings are readable only with `members:manage`, so the way
                in is drawn only for those who hold it. */}
            {canManage ? (
              <Button variant="outline" asChild>
                <Link href={ROUTES.ORG_DIRECTORY(id)}>
                  <Network className="h-4 w-4" />
                  {tDirectory("navLabel")}
                </Link>
              </Button>
            ) : null}
            {/* Only for the people who can change it - the page refuses anybody
                else, and a button that leads to a refusal is a button that
                teaches nothing (#1420). */}
            {canSettings ? (
              <Button variant="outline" asChild>
                <Link href={ROUTES.ORG_RETENTION(id)}>
                  <Archive className="h-4 w-4" />
                  {t("retention")}
                </Link>
              </Button>
            ) : null}
            {canManage ? (
              <>
                {/* Two ways in, because onboarding a team and inviting one
                    person are different jobs. The link is the outline button:
                    it is the powerful one, and the addressed invitation is
                    what most people want most of the time. */}
                <Button variant="outline" onClick={() => setLinkOpen(true)}>
                  <Link2 className="h-4 w-4" />
                  {t("inviteLink")}
                </Button>
              </>
            ) : null}
          </div>
        }
        actions={
          canManage && (
            <Button onClick={() => setInviteOpen(true)}>
              <UserPlus className="h-4 w-4" />
              {t("inviteTeammate")}
            </Button>
          )
        }
      />

      <Tabs
        className="flex flex-1 flex-col"
        value={tab}
        onValueChange={(next) => {
          setTabParam(next === "members" ? null : next);
          // A legacy card anchor must not point into the panel we just hid.
          if (window.location.hash) {
            const url = new URL(window.location.href);
            url.hash = "";
            window.history.replaceState({}, "", url.toString());
          }
        }}
      >
        <TabsList data-tour="org-tabs">
          {sections.map((section) => (
            <div key={section.id} className="relative pt-2">
              <TabsTrigger
                value={section.id}
                data-tour={`org-tab-${section.id}`}
                aria-describedby={
                  hints[section.id]?.length ? `${setupId}-${section.id}` : undefined
                }
              >
                <section.icon className="mr-1.5 size-4 shrink-0" aria-hidden />
                {t(section.label)}
              </TabsTrigger>
              <span id={`${setupId}-${section.id}`} className="sr-only">
                {(hints[section.id] ?? []).map((hint) => tSetup(hint)).join(" ")}
              </span>
              <SetupIndicator
                hints={hints[section.id] ?? []}
                className="absolute top-0 right-0"
                focusable={false}
              />
            </div>
          ))}
        </TabsList>
        {/* Keep drafts mounted while another section is open. Hidden panels take
            no layout space and cannot receive keyboard focus. */}
        <TabsContent
          value="members"
          hidden={tab !== "members"}
          forceMount
          className="flex-1 flex-col space-y-6 data-[state=active]:flex"
        >
          {/* The table draws its own skeleton from the same column definitions, so
          the header and every column width are already right while it loads -
          a stand-in list could only approximate them. The shared list card
          keeps the page's shape whether it is empty, loading or full. */}
          <ListCard
            fill
            data-tour="org-members"
            title={t("membersCard")}
            counted={
              isLoading || permissionsLoading || error
                ? null
                : t("memberCount", { count: members.length })
            }
            contentClassName="p-0"
          >
            {rolesError && !error && (
              <p className="text-destructive px-5 pt-4 text-sm">{t("rolesUnavailable")}</p>
            )}
            {error ? (
              // Every organization has at least its owner, so "no members yet"
              // over a failed read is a sentence that cannot be true (#32).
              <ErrorState description={getErrorMessage(error, tErrors)} className="m-5" />
            ) : !isLoading && !permissionsLoading && members.length === 0 ? (
              <ListCardEmpty
                icon={Users}
                title={t("noMembersYet")}
                description={t("inviteTeammatesByEmail")}
                cta={
                  canManage
                    ? { label: t("inviteTeammate"), onClick: () => setInviteOpen(true) }
                    : undefined
                }
              />
            ) : (
              <DataTable<OrganizationMember>
                stackOnNarrow
                columns={columns}
                rows={members}
                // Wait on the permission answer too, or the row-action column - built
                // from `canManage` - draws without its actions and then flickers them
                // in a beat later once `can()` resolves (safe direction, but a glitch).
                loading={isLoading || permissionsLoading}
                skeletonRows={4}
                getRowKey={(m) => m.id}
                empty={t("noMembersYet")}
                className="rounded-none border-0 bg-transparent"
              />
            )}
          </ListCard>

          {pendingInvitations.length > 0 && (
            <section className="space-y-3">
              <div>
                <p className="text-muted-foreground font-mono text-xs tracking-wider uppercase">
                  {t("pendingInvitations")}
                </p>
                <h2 className="text-foreground text-sm font-semibold">
                  {t("waitingOnResponse", { count: pendingInvitations.length })}
                </h2>
              </div>
              <ul className="border-border bg-card divide-border divide-y overflow-hidden rounded-xl border">
                {pendingInvitations.map((inv) => (
                  <li key={inv.id} className="flex flex-wrap items-center gap-3 px-4 py-3.5">
                    <span className="bg-muted text-muted-foreground inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
                      <MailPlus className="h-4 w-4" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-foreground truncate text-sm font-medium">
                        {inv.email ?? t("shareableLink")}
                      </p>
                      <p className="text-muted-foreground mt-0.5 truncate text-xs">
                        {/* A link is not waiting on one person, so "invited" is the
                        wrong word for it and its limits are what matter. */}
                        {inv.email === null ? (
                          <>
                            {/* The sum, because that is what the ceiling compares:
                            registering through a link spends a use, since joining
                            needs a session and happens later. */}
                            {t("usedOfMax", {
                              used: (inv.used_count ?? 0) + (inv.reserved_count ?? 0),
                              max: inv.max_uses ?? "∞",
                            })}
                            {inv.reserved_count ? (
                              <> · {t("awaitingSignup", { count: inv.reserved_count })}</>
                            ) : null}
                            {inv.email_domain && (
                              <> · {t("domainOnly", { domain: inv.email_domain })}</>
                            )}
                          </>
                        ) : (
                          <>{t("invitedOn", { date: formatDate(inv.created_at, locale) })}</>
                        )}
                        {inv.expires_at && (
                          <> · {t("expiresOn", { date: formatDate(inv.expires_at, locale) })}</>
                        )}
                      </p>
                    </div>
                    <Badge variant={ROLE_VARIANT[inv.role]} className="capitalize">
                      {inv.role}
                    </Badge>
                    {canManage && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-muted-foreground hover:text-destructive"
                        onClick={() => revokeInvitation(inv.id)}
                      >
                        {t("revoke")}
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </TabsContent>
        <TabsContent
          value="profile"
          hidden={tab !== "profile"}
          forceMount
          className="space-y-6 data-[state=inactive]:hidden"
        >
          <p className="text-muted-foreground max-w-3xl text-sm leading-6">
            {t("workspaceSettingsHint")}
          </p>
          {org && <OrganizationProfileSettings org={org} />}
          {org && canSettings && <OrgVoiceSettings org={org} />}
        </TabsContent>
        <TabsContent
          value="governance"
          data-tour="org-governance"
          hidden={tab !== "governance"}
          forceMount
          className="space-y-6 data-[state=inactive]:hidden"
        >
          {org && <OrgSpendingLimit org={org} />}
          {org && <OrgApprovalWaiver org={org} />}
          {org && <OrgPublicAttribution org={org} />}
          {org && <OrgPublicLiveData org={org} />}
        </TabsContent>
        <TabsContent
          value="proactivity"
          data-tour="org-proactivity"
          hidden={tab !== "proactivity"}
          forceMount
          className="space-y-6 data-[state=inactive]:hidden"
        >
          {org && <OrgProactivity org={org} />}
        </TabsContent>
        <TabsContent
          value="assistant"
          hidden={tab !== "assistant"}
          forceMount
          className="space-y-6 data-[state=inactive]:hidden"
        >
          <p className="text-muted-foreground max-w-3xl text-sm leading-6">{t("aiServicesHint")}</p>
          {canConfigureAssistant && <OrgAssistant orgId={id} />}
          {org && canSystemServices && <OrgSystemAgents org={org} />}
        </TabsContent>
      </Tabs>

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => {
          if (!open && !removingBusy) setRemoving(null);
        }}
        title={tc("removeNamedConfirm", { name: removing?.full_name || removing?.email || "" })}
        confirmLabel={tc("removeNamed", { name: removing?.full_name || removing?.email || "" })}
        loading={removingBusy}
        destructive
        onConfirm={async () => {
          if (!removing || removingBusy) return;
          setRemovingBusy(true);
          try {
            if (await removeMember(removing.user_id)) setRemoving(null);
          } finally {
            setRemovingBusy(false);
          }
        }}
      />
      <InviteMemberDialog open={inviteOpen} onOpenChange={setInviteOpen} orgId={id} />
      <InviteLinkDialog open={linkOpen} onOpenChange={setLinkOpen} orgId={id} />
    </div>
  );
}
