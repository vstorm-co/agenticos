"use client";

import { useState } from "react";
import { Plus, Trash2, Users } from "lucide-react";
import { useTranslations } from "next-intl";

import { ErrorState, LoadingState } from "@/components/states";
import {
  Badge,
  Button,
  ConfirmDialog,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { useAssignableRoles, useDiscordRoleMappings, usePermissions } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_FORM } from "@/lib/dialog-sizes";
import type { ChannelBot, DiscordRoleMapping } from "@/types/channels";
import { Perm } from "@/types/permissions";
import { DiscordRoleMappingForm } from "./discord-role-mapping-form";

/**
 * Which roles in a Discord bot's servers place people in which groups here (#2569).
 *
 * Opened only for somebody holding `members:manage`, which every call takes.
 * A mapping that admits with a role is deleted only by somebody who could have
 * made it: deleting it removes everybody it admitted. Mounted only while open,
 * so each opening starts with the form closed.
 */
export function DiscordRoleMappingsDialog({
  bot,
  onClose,
}: {
  bot: ChannelBot;
  onClose: () => void;
}) {
  const t = useTranslations("discordRoles");
  const tErrors = useTranslations("errors");
  const { can } = usePermissions();
  const assignable = useAssignableRoles();
  const { mappings, isLoading, error, remove } = useDiscordRoleMappings(bot.id);
  const [adding, setAdding] = useState(false);
  const [deleting, setDeleting] = useState<DiscordRoleMapping | null>(null);
  const mayDelete = (mapping: DiscordRoleMapping) =>
    mapping.role === null || (can(Perm.rolesManage) && assignable.includes(mapping.role));

  const confirmDelete = async (mapping: DiscordRoleMapping) => {
    // A refusal is the hook's toast; the confirmation closes either way.
    await remove.mutateAsync(mapping.id).catch(() => undefined);
    setDeleting(null);
  };

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className={DIALOG_FORM}>
        <DialogHeader>
          <DialogTitle>{t("title", { bot: bot.name })}</DialogTitle>
          <DialogDescription>{t("howItWorks")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          {error ? (
            <ErrorState description={getErrorMessage(error, tErrors)} />
          ) : isLoading ? (
            <LoadingState variant="pending" />
          ) : mappings.length === 0 && !adding ? (
            <p className="text-muted-foreground py-4 text-center text-sm">{t("empty")}</p>
          ) : (
            mappings.map((mapping) => (
              <div key={mapping.id} className="flex items-center gap-3 rounded-md border p-3">
                <Users className="text-muted-foreground h-4 w-4 shrink-0" aria-hidden />
                <span className="min-w-0 flex-1 text-sm">
                  {t("row", {
                    server: mapping.guild_name,
                    role: mapping.discord_role_name,
                    group: mapping.group_name ?? mapping.group_id,
                  })}
                </span>
                {mapping.role !== null && (
                  <Badge variant="secondary" className="capitalize">
                    {mapping.role}
                  </Badge>
                )}
                {mayDelete(mapping) && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-muted-foreground hover:text-destructive"
                    onClick={() => setDeleting(mapping)}
                    aria-label={t("deleteNamed", { role: mapping.discord_role_name })}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                )}
              </div>
            ))
          )}
          {adding ? (
            <DiscordRoleMappingForm botId={bot.id} onDone={() => setAdding(false)} />
          ) : (
            <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
              <Plus className="h-4 w-4" />
              {t("addMapping")}
            </Button>
          )}
        </div>
      </DialogContent>
      {deleting !== null && (
        <ConfirmDialog
          open
          onOpenChange={() => setDeleting(null)}
          title={t("deleteTitle")}
          description={t("deleteBody", { role: deleting.discord_role_name })}
          confirmLabel={t("delete")}
          destructive
          loading={remove.isPending}
          onConfirm={() => confirmDelete(deleting)}
        />
      )}
    </Dialog>
  );
}
