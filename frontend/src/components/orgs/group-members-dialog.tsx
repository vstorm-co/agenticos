"use client";

import { Crown, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { DirectoryBadge } from "@/components/orgs/directory-badge";
import { GroupMemberAdd } from "@/components/orgs/group-member-add";
import { MemberIdentity } from "@/components/orgs/member-identity";
import { ErrorState, LoadingState } from "@/components/states";
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { useGroupMembers, useMembers } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores";
import type { Group } from "@/types/groups";

interface GroupMembersDialogProps {
  orgId: string;
  group: Group;
  canManage: boolean;
  onClose: () => void;
}

/**
 * Who is in one group, and - for a caller holding `members:manage`, or leading the
 * group - adding and removing people by hand. Only an administrator names a lead
 * (#2072): a lead adds members, so naming one hands out part of administering.
 *
 * A row the directory sync placed says so: the sync added it at somebody's
 * sign-in and will remove it when the directory stops listing them, so a hand
 * removal lasts only until their next sign-in.
 */
export function GroupMembersDialog({ orgId, group, canManage, onClose }: GroupMembersDialogProps) {
  const t = useTranslations("groups");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const { members, isLoading, error, add, remove, setLead } = useGroupMembers(orgId, group.id);
  const { members: orgMembers } = useMembers(orgId);
  const me = useAuthStore((state) => state.user?.id);
  const leads = members.some((member) => member.user_id === me && member.is_lead);
  const canChangeMembers = canManage || leads;
  const inGroup = new Set(members.map((member) => member.user_id));
  const candidates = orgMembers.filter((member) => !inGroup.has(member.user_id));

  return (
    // Mounted only while open, so the one change of openness it can report is closing.
    <Dialog open onOpenChange={onClose}>
      <DialogContent className={cn(DIALOG_FORM, DIALOG_COLUMN)}>
        <DialogHeader>
          <DialogTitle>{t("membersOf", { name: group.name })}</DialogTitle>
          <DialogDescription>{t("membersBody")}</DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-2 overflow-y-auto">
          {error ? (
            <ErrorState description={getErrorMessage(error, tErrors)} />
          ) : isLoading ? (
            <LoadingState variant="skeleton-panel" rows={3} />
          ) : members.length === 0 ? (
            <p className="text-muted-foreground py-6 text-center text-sm">{t("nobodyYet")}</p>
          ) : (
            members.map((member) => (
              <div key={member.user_id} className="flex items-center gap-3 rounded-md border p-3">
                <MemberIdentity member={member} className="flex-1" />
                {member.source === "directory" && (
                  <DirectoryBadge explanation={t("directoryMemberHint")} />
                )}
                {member.is_lead && (
                  <Badge variant="secondary" className="gap-1">
                    <Crown className="h-3 w-3" aria-hidden />
                    {t("lead")}
                  </Badge>
                )}
                {canManage && (
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={setLead.isPending}
                    onClick={() =>
                      setLead.mutate({ userId: member.user_id, isLead: !member.is_lead })
                    }
                    aria-label={t(member.is_lead ? "unmakeLead" : "makeLead", {
                      name: member.full_name || member.email,
                    })}
                    title={t(member.is_lead ? "unmakeLead" : "makeLead", {
                      name: member.full_name || member.email,
                    })}
                    className="text-muted-foreground"
                  >
                    <Crown className="h-4 w-4" />
                  </Button>
                )}
                {canChangeMembers && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-muted-foreground hover:text-destructive"
                    disabled={remove.isPending}
                    onClick={() => remove.mutate(member.user_id)}
                    aria-label={tc("removeNamed", { name: member.full_name || member.email })}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                )}
              </div>
            ))
          )}
        </div>
        {canChangeMembers && (
          <GroupMemberAdd
            candidates={candidates}
            pending={add.isPending}
            onAdd={(userId) => add.mutate(userId)}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
