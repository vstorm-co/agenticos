"use client";

import { use, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  Camera,
  Link2,
  Loader2,
  MailPlus,
  ShieldCheck,
  Trash2,
  UserPlus,
  Users,
} from "lucide-react";
import { toast } from "sonner";

import { ApiError, getErrorMessage, parseErrorMessage } from "@/lib/api-error";
import { ErrorState } from "@/components/states";
import { InviteLinkDialog, InviteMemberDialog, OrgSpendingLimit } from "@/components/teams";
import { PageHeader } from "@/components/dashboard/page-header";
import {
  Badge,
  Button,
  DataTable,
  AvatarColorPicker,
  EntityAvatar,
  Input,
  ListCard,
  ListCardEmpty,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  type Column,
} from "@/components/ui";
import {
  useAssignableRoles,
  useAuth,
  useInvitations,
  useMembers,
  useOrganizations,
  usePermissions,
} from "@/hooks";
import { Perm } from "@/types/permissions";
import type { OrganizationMember, OrgRole } from "@/types";
import { avatarInitials, avatarPalette } from "@/lib/avatar-color";
import { cn, formatDate, MAX_AVATAR_SIZE_BYTES } from "@/lib/utils";
import { ROUTES } from "@/lib/constants";
import { useChanged } from "@/hooks/use-changed";

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
  const locale = useLocale();
  const { id } = use(params);
  const { user } = useAuth();
  const { members, total, isLoading, error, fetchMembers, changeRole, removeMember } =
    useMembers(id);
  const { invitations, fetchInvitations, revokeInvitation } = useInvitations(id);
  const { orgs, fetchOrgs, patchOrg } = useOrganizations();
  const [inviteOpen, setInviteOpen] = useState(false);
  const [linkOpen, setLinkOpen] = useState(false);

  useEffect(() => {
    fetchMembers();
    fetchInvitations();
    fetchOrgs();
  }, [fetchMembers, fetchInvitations, fetchOrgs]);

  const { can } = usePermissions();
  const assignable = useAssignableRoles();
  const org = orgs.find((o) => o.id === id);
  // Derived from the server's permission catalog rather than a role-name check,
  // so adding a role that may manage members needs no change here.
  const canManage = can(Perm.membersManage);
  const pendingInvitations = invitations.filter((i) => i.status === "pending");

  // Workspace profile state - name edits stay local until "Save" lands the
  // PATCH; avatar uploads are immediate (a separate POST endpoint).
  const [name, setName] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [avatarUploading, setAvatarUploading] = useState(false);
  const avatarInputRef = useRef<HTMLInputElement>(null);

  // Re-seeded when the stored name moves - a save coming back, or another tab.
  // During render, so the old name is never shown in the field.
  if (useChanged(`${org?.id}|${org?.name}`) && org) setName(org.name);

  const handleSaveName = async () => {
    if (!org) return;
    const trimmed = name.trim();
    if (!trimmed || trimmed === org.name) return;
    setSavingName(true);
    try {
      await patchOrg(org.id, { name: trimmed });
    } finally {
      setSavingName(false);
    }
  };

  const handleColorChange = async (slot: number | null) => {
    if (!org || slot === (org.avatar_color ?? null)) return;
    await patchOrg(org.id, { avatar_color: slot });
  };

  const handleAvatarUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    if (file.size > MAX_AVATAR_SIZE_BYTES) {
      toast.error(t("avatarTooLargeMaximum"));
      return;
    }
    setAvatarUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`/api/orgs/${id}/avatar`, { method: "POST", body: fd });
      if (!res.ok) {
        const body: unknown = await res.json().catch(() => null);
        throw new ApiError(res.status, parseErrorMessage(body, t("uploadFailed2")), body);
      }
      toast.success(t("workspaceAvatarUpdated"));
      await fetchOrgs(true);
    } catch (err) {
      toast.error(getErrorMessage(err, tErrors, t("failedUploadAvatar")));
    } finally {
      setAvatarUploading(false);
    }
  };

  const columns = useMemo<Column<OrganizationMember>[]>(() => {
    const cols: Column<OrganizationMember>[] = [
      {
        key: "member",
        className: "pl-5",
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
                className="h-8 w-8 shrink-0 text-[10px]"
                ariaHidden
              />
              <div className="min-w-0">
                <p className="text-foreground truncate text-sm font-medium">
                  {m.full_name || m.email.split("@")[0]}
                  {isSelf && <span className="text-muted-foreground font-normal"> {t("you")}</span>}
                </p>
                <p className="text-muted-foreground truncate text-xs">{m.email}</p>
              </div>
            </div>
          );
        },
      },
      {
        key: "role",
        header: t("role2"),
        cell: (m) => {
          const isSelf = m.user_id === user?.id;
          const isOwner = m.role === "owner";
          if (canManage && !isOwner && !isSelf) {
            return (
              <Select value={m.role} onValueChange={(v) => changeRole(m.user_id, v as OrgRole)}>
                <SelectTrigger
                  className="h-8 w-32 capitalize"
                  aria-label={t("roleFor", { email: m.email })}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {assignable.map((option) => (
                    <SelectItem key={option} value={option} className="capitalize">
                      {option}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            );
          }
          return (
            <Badge variant={ROLE_VARIANT[m.role]} className="capitalize">
              {m.role}
            </Badge>
          );
        },
      },
      {
        key: "joined",
        header: t("joined"),
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
        className: "w-0 pr-5",
        cell: (m) => {
          const isSelf = m.user_id === user?.id;
          const isOwner = m.role === "owner";
          if (isOwner || isSelf) return null;
          return (
            <Button
              variant="ghost"
              size="sm"
              className="text-muted-foreground hover:text-destructive"
              onClick={() => removeMember(m.user_id)}
              aria-label={tc("removeNamed", { name: m.full_name || m.email })}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          );
        },
      });
    }

    return cols;
  }, [canManage, user?.id, assignable, changeRole, removeMember]);

  return (
    <div className="space-y-6">
      <PageHeader
        title={org?.name ?? t("members")}
        description={t("membersDescription", { count: total })}
        breadcrumbs={[
          { label: t("organizations"), href: ROUTES.ORGS },
          { label: org?.name ?? t("members2") },
        ]}
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" asChild>
              <Link href={ROUTES.ORG_ROLES(id)}>
                <ShieldCheck className="h-4 w-4" />
                {t("roles")}
              </Link>
            </Button>
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
                <Button onClick={() => setInviteOpen(true)}>
                  <UserPlus className="h-4 w-4" />
                  {t("inviteTeammate")}
                </Button>
              </>
            ) : null}
          </div>
        }
      />

      {org && (
        <section className="border-border bg-card flex flex-wrap items-start gap-5 rounded-xl border p-5 sm:p-6">
          <button
            type="button"
            onClick={() => avatarInputRef.current?.click()}
            disabled={!canManage || avatarUploading}
            className={cn(
              "group relative flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-xl disabled:cursor-default",
              org.avatar_url
                ? "bg-muted text-foreground"
                : avatarPalette(org.id, org.avatar_color).bg,
            )}
            title={canManage ? t("changeWorkspaceAvatar") : t("onlyOwnersAdminsCan")}
          >
            {org.avatar_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={`/api/orgs/${org.id}/avatar?v=${org.updated_at ?? ""}`}
                alt=""
                className="h-full w-full object-cover"
              />
            ) : (
              <span
                className={cn(
                  avatarPalette(org.id, org.avatar_color).fg,
                  "text-base font-semibold",
                )}
              >
                {avatarInitials(org.name)}
              </span>
            )}
            {canManage && (
              <span className="absolute inset-0 flex items-center justify-center bg-black/45 opacity-0 transition-opacity group-hover:opacity-100">
                {avatarUploading ? (
                  <Loader2 className="h-5 w-5 animate-spin text-white" />
                ) : (
                  <Camera className="h-5 w-5 text-white" />
                )}
              </span>
            )}
          </button>
          <input
            ref={avatarInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp,image/gif"
            className="hidden"
            onChange={handleAvatarUpload}
          />

          <div className="min-w-0 flex-1 space-y-3">
            <div>
              <p className="text-muted-foreground font-mono text-[11px] tracking-wider uppercase">
                {t("workspaceProfile")}
              </p>
              <p className="text-muted-foreground mt-0.5 text-xs">{t("nameAvatarShownAcross")}</p>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={!canManage || savingName}
                className="min-w-0 flex-1"
                placeholder={t("workspaceName")}
                maxLength={255}
              />
              {canManage && name.trim() !== org.name && name.trim() !== "" && (
                <Button onClick={handleSaveName} disabled={savingName}>
                  {savingName ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save"}
                </Button>
              )}
            </div>
            {!canManage && (
              <p className="text-muted-foreground text-[11px]">{t("onlyOwnersAdminsCan")}</p>
            )}
            {canManage && (
              <div>
                <p className="text-muted-foreground mb-2 text-xs">{t("avatarColour")}</p>
                <AvatarColorPicker value={org.avatar_color} onChange={handleColorChange} />
              </div>
            )}
          </div>
        </section>
      )}

      {/* The workspace's own spending ceiling sits with its other settings. It
          hides itself from anyone who may not change them. */}
      {org && <OrgSpendingLimit org={org} />}

      {/* The table draws its own skeleton from the same column definitions, so
          the header and every column width are already right while it loads -
          a stand-in list could only approximate them. The shared list card
          keeps the page's shape whether it is empty, loading or full. */}
      <ListCard
        title={t("membersCard")}
        counted={isLoading || error ? null : t("memberCount", { count: members.length })}
        contentClassName="p-0"
      >
        {error ? (
          // Every organization has at least its owner, so "no members yet"
          // over a failed read is a sentence that cannot be true (#32).
          <ErrorState description={getErrorMessage(error, tErrors)} className="m-5" />
        ) : !isLoading && members.length === 0 ? (
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
            columns={columns}
            rows={members}
            loading={isLoading}
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
            <p className="text-muted-foreground font-mono text-[11px] tracking-wider uppercase">
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
                        {t("usedOfMax", { used: inv.used_count ?? 0, max: inv.max_uses ?? "∞" })}
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

      <InviteMemberDialog open={inviteOpen} onOpenChange={setInviteOpen} orgId={id} />
      <InviteLinkDialog open={linkOpen} onOpenChange={setLinkOpen} orgId={id} />
    </div>
  );
}
