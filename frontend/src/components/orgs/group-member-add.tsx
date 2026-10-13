"use client";

import { useState } from "react";
import { UserPlus } from "lucide-react";
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
import type { OrganizationMember } from "@/types";

interface GroupMemberAddProps {
  /** Organization members not already in the group - the only ones the server accepts. */
  candidates: OrganizationMember[];
  pending: boolean;
  onAdd: (userId: string) => void;
}

/** The row that adds one more of the organization's members to a group by hand. */
export function GroupMemberAdd({ candidates, pending, onAdd }: GroupMemberAddProps) {
  const t = useTranslations("groups");
  const [userId, setUserId] = useState("");
  const empty = candidates.length === 0;

  return (
    <div className="flex flex-wrap items-end gap-3 border-t pt-4">
      <div className="min-w-56 flex-1 space-y-2">
        <Label htmlFor="group-add-member">{t("addMember")}</Label>
        <Select value={userId} onValueChange={setUserId} disabled={empty}>
          <SelectTrigger id="group-add-member">
            <SelectValue placeholder={empty ? t("everyoneIsIn") : t("chooseMember")} />
          </SelectTrigger>
          <SelectContent>
            {candidates.map((member) => (
              <SelectItem key={member.user_id} value={member.user_id}>
                {member.full_name ? `${member.full_name} (${member.email})` : member.email}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <Button
        onClick={() => {
          onAdd(userId);
          setUserId("");
        }}
        disabled={userId === "" || pending}
      >
        <UserPlus className="h-4 w-4" />
        {t("add")}
      </Button>
    </div>
  );
}
