"use client";

import { useState, useSyncExternalStore } from "react";
import { Users, UserPlus } from "lucide-react";
import styles from "./start.module.css";
import { useTranslations } from "next-intl";
import {
  Button,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { InviteMemberDialog } from "@/components/teams/invite-member-dialog";
import { useMembers } from "@/hooks/use-members";
import { useMemberStartPreview } from "@/hooks/use-start";
import { isLoopbackAddress } from "@/lib/local-server";

const subscribe = () => () => {};
export function StartTeam({ orgId }: { orgId: string }) {
  const t = useTranslations("start");
  const members = useMembers(orgId);
  const [person, setPerson] = useState("");
  const [inviting, setInviting] = useState(false);
  const preview = useMemberStartPreview(person);
  const local = useSyncExternalStore(
    subscribe,
    () => isLoopbackAddress(window.location.origin),
    () => false,
  );
  return (
    <section className={`${styles.panel} mt-4 space-y-3`}>
      <h2 className={`${styles.panelHeading} font-semibold`}>
        <Users size={20} aria-hidden />
        {t("team")}
      </h2>
      <p className="text-muted-foreground text-sm">{t("teamHint")}</p>
      {local && (
        <p role="note" className="text-muted-foreground text-sm">
          {t("localTeamWarning")}
        </p>
      )}
      <Label htmlFor="preview-member">{t("previewMember")}</Label>
      {members.error ? (
        <Button variant="outline" onClick={() => void members.refetch()}>
          {t("retry")}
        </Button>
      ) : (
        <Select value={person} onValueChange={setPerson} disabled={members.isLoading}>
          <SelectTrigger id="preview-member">
            <SelectValue placeholder={t("previewMember")} />
          </SelectTrigger>
          <SelectContent>
            {members.members.map((member) => (
              <SelectItem key={member.user_id} value={member.user_id}>
                {member.full_name || member.email}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
      {person && (
        <p role="status" className="text-sm">
          {t(
            preview.isFetching
              ? "previewChecking"
              : preview.error
                ? "loadFailed"
                : preview.data?.has_common_agent
                  ? "previewReady"
                  : "previewMissing",
          )}
        </p>
      )}
      {preview.error && (
        <Button variant="outline" onClick={() => void preview.refetch()}>
          {t("retry")}
        </Button>
      )}
      <p className="text-muted-foreground text-xs">{t("previewHint")}</p>
      <Button disabled={local} onClick={() => setInviting(true)}>
        <UserPlus size={15} aria-hidden />
        {t("invite")}
      </Button>
      <InviteMemberDialog orgId={orgId} open={inviting} onOpenChange={setInviting} />
    </section>
  );
}
