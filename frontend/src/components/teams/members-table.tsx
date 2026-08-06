"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Trash2 } from "lucide-react";
import { useAssignableRoles } from "@/hooks";
import type { OrganizationMember, OrgRole } from "@/types";
import { useTranslations } from "next-intl";

interface MembersTableProps {
  members: OrganizationMember[];
  currentUserId: string;
  canManage: boolean;
  onRoleChange: (userId: string, role: OrgRole) => void;
  onRemove: (userId: string) => void;
}

const roleBadgeVariant: Record<OrgRole, "default" | "secondary" | "outline"> = {
  owner: "default",
  admin: "secondary",
  builder: "secondary",
  operator: "secondary",
  member: "outline",
  viewer: "outline",
};

/**
 * What each role is *for*, in the picker.
 *
 * The names alone do not answer the question somebody is actually asking -
 * "which of these lets them build an agent but not publish it" - and the
 * permission matrix that does answer it is a different page. One line each,
 * here, at the moment of the decision.
 */
/** The catalog key for each role's one line; the words are in `messages/en.json`. */
const roleBlurb: Record<OrgRole, string> = {
  owner: "roleOwnerDetail",
  admin: "roleAdminDetail",
  builder: "roleBuilderDetail",
  operator: "roleOperatorDetail",
  member: "roleMemberDetail",
  viewer: "roleViewerDetail",
};

export function MembersTable({
  members,
  currentUserId,
  canManage,
  onRoleChange,
  onRemove,
}: MembersTableProps) {
  const t = useTranslations("teams");
  const assignable = useAssignableRoles();

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("member")}</TableHead>
          <TableHead>{t("role2")}</TableHead>
          <TableHead>{t("joined")}</TableHead>
          {canManage && <TableHead className="w-12" />}
        </TableRow>
      </TableHeader>
      <TableBody>
        {members.map((m) => {
          const isSelf = m.user_id === currentUserId;
          const isOwner = m.role === "owner";
          return (
            <TableRow key={m.id}>
              <TableCell>
                <div className="flex items-center gap-3">
                  <Avatar className="h-8 w-8">
                    <AvatarFallback className="text-xs">
                      {(m.full_name ?? m.email).substring(0, 2).toUpperCase()}
                    </AvatarFallback>
                  </Avatar>
                  <div>
                    <p className="text-sm font-medium">{m.full_name ?? m.email}</p>
                    {m.full_name && <p className="text-muted-foreground text-xs">{m.email}</p>}
                    {isSelf && <span className="text-muted-foreground text-xs">{t("you")}</span>}
                  </div>
                </div>
              </TableCell>
              <TableCell>
                {canManage && !isOwner && !isSelf ? (
                  <Select
                    value={m.role}
                    onValueChange={(v) => onRoleChange(m.user_id, v as OrgRole)}
                  >
                    <SelectTrigger className="h-7 w-36" aria-label={`Role for ${m.email}`}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {assignable.map((role) => (
                        <SelectItem
                          key={role}
                          value={role}
                          // The blurb answers "which of these lets them build
                          // but not publish", which is a question about the
                          // options as a set. Radix draws an item's `ItemText`
                          // in the closed trigger, so in `children` it became a
                          // second line inside `h-7 w-36` explaining a role
                          // nobody is choosing any more.
                          trailing={
                            <span className="text-muted-foreground ml-auto max-w-64 pl-3 text-xs">
                              {t(roleBlurb[role])}
                            </span>
                          }
                        >
                          <span className="capitalize">{role}</span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Badge variant={roleBadgeVariant[m.role]} className="capitalize">
                    {m.role}
                  </Badge>
                )}
              </TableCell>
              <TableCell className="text-muted-foreground text-sm">
                {new Date(m.joined_at).toLocaleDateString()}
              </TableCell>
              {canManage && (
                <TableCell>
                  {!isOwner && !isSelf && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-destructive hover:text-destructive h-7 w-7 p-0"
                      onClick={() => onRemove(m.user_id)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </TableCell>
              )}
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
