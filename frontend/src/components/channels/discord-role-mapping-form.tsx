"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { ErrorState } from "@/components/states";
import {
  Button,
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import {
  useAssignableRoles,
  useDiscordRoleMappings,
  useDiscordServers,
  useGroups,
  usePermissions,
} from "@/hooks";
import { getErrorMessage, submitFailure } from "@/lib/api-error";
import { useOrgStore } from "@/stores";
import type { OrgRole } from "@/types";
import { Perm } from "@/types/permissions";

/** A Radix select item cannot hold the empty string, so "admit nobody" needs a value of its own. */
const NO_ROLE = "none";

/**
 * Mapping one role of a server the bot is in to a group, and optionally a role, here.
 *
 * The servers and their roles come from Discord itself, so only a role the bot
 * can see - not `@everyone`, not one Discord manages for a bot - is offered.
 * The organization role is offered only to somebody holding `roles:manage`, and
 * only the roles their own strictly outranks, the same arithmetic the server
 * applies to this write (#1028).
 */
export function DiscordRoleMappingForm({ botId, onDone }: { botId: string; onDone: () => void }) {
  const t = useTranslations("discordRoles");
  const tErrors = useTranslations("errors");
  const orgId = useOrgStore((state) => state.activeOrgId) ?? "";
  const { can } = usePermissions();
  const { create } = useDiscordRoleMappings(botId);
  const { servers, isLoading, error } = useDiscordServers(botId, true);
  const { groups } = useGroups(orgId);
  const assignable = useAssignableRoles();
  const offered = can(Perm.rolesManage) ? assignable : [];
  const [guildId, setGuildId] = useState("");
  const [roleId, setRoleId] = useState("");
  const [groupId, setGroupId] = useState("");
  const [orgRole, setOrgRole] = useState<string>(NO_ROLE);
  const [problems, setProblems] = useState<Readonly<Record<string, string>>>({});
  const server = servers.find((candidate) => candidate.id === guildId);

  if (error) return <ErrorState description={getErrorMessage(error, tErrors)} />;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      await create.mutateAsync({
        guild_id: guildId,
        discord_role_id: roleId,
        group_id: groupId,
        // Every item below but NO_ROLE is an `OrgRole` from `offered`.
        role: orgRole === NO_ROLE ? null : (orgRole as OrgRole),
      });
      onDone();
    } catch (failure) {
      const refused = submitFailure(
        failure,
        { fields: ["guild_id", "discord_role_id", "group_id"], identifiedBy: "discord_role_id" },
        tErrors,
      );
      setProblems(refused.fields);
      if (refused.toast) toast.error(refused.toast);
    }
  };

  return (
    <form onSubmit={submit} className="border-border space-y-4 rounded-lg border p-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label={t("server")} htmlFor="discord-map-server" error={problems.guild_id}>
          <Select
            value={guildId}
            onValueChange={(value) => {
              setGuildId(value);
              setRoleId("");
              setProblems({});
            }}
            disabled={isLoading}
          >
            <SelectTrigger id="discord-map-server">
              <SelectValue placeholder={isLoading ? t("loadingServers") : t("pickServer")} />
            </SelectTrigger>
            <SelectContent>
              {servers.map((option) => (
                <SelectItem key={option.id} value={option.id}>
                  {option.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField
          label={t("discordRole")}
          htmlFor="discord-map-role"
          error={problems.discord_role_id}
        >
          <Select value={roleId} onValueChange={setRoleId} disabled={!server}>
            <SelectTrigger id="discord-map-role">
              <SelectValue placeholder={t("pickRole")} />
            </SelectTrigger>
            <SelectContent>
              {server?.roles.map((option) => (
                <SelectItem key={option.id} value={option.id}>
                  @{option.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField label={t("group")} htmlFor="discord-map-group" error={problems.group_id}>
          <Select value={groupId} onValueChange={setGroupId}>
            <SelectTrigger id="discord-map-group">
              <SelectValue placeholder={t("pickGroup")} />
            </SelectTrigger>
            <SelectContent>
              {groups.map((group) => (
                <SelectItem key={group.id} value={group.id}>
                  {group.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        {offered.length > 0 && (
          <FormField label={t("orgRole")} htmlFor="discord-map-org-role">
            <Select value={orgRole} onValueChange={setOrgRole}>
              <SelectTrigger id="discord-map-org-role" className="capitalize">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_ROLE}>{t("membersOnly")}</SelectItem>
                {offered.map((option) => (
                  <SelectItem key={option} value={option} className="capitalize">
                    {option}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        )}
      </div>
      <p className="text-muted-foreground text-xs">
        {orgRole === NO_ROLE ? t("membersOnlyHint") : t("admitsHint")}
      </p>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" size="sm" onClick={onDone}>
          {t("cancel")}
        </Button>
        <Button
          type="submit"
          size="sm"
          loading={create.isPending}
          disabled={!guildId || !roleId || !groupId}
        >
          {t("add")}
        </Button>
      </div>
    </form>
  );
}
