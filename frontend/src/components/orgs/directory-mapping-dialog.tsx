"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useAssignableRoles, useDirectoryMappings, useGroups } from "@/hooks";
import { submitFailure } from "@/lib/api-error";
import { defaultAssignable } from "@/lib/assignable-roles";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";
import type { OrgRole } from "@/types";

/** What the backend accepts for a DN or a claim value. */
const MAX_EXTERNAL = 1024;

// i18n-exempt: an example LDAP DN, which reads the same in every language
const EXAMPLE_DN = "cn=finance,ou=groups,dc=example,dc=com";

/** A Radix select item cannot hold the empty string, so "no group" needs a value of its own. */
const NO_GROUP = "none";

/**
 * Mapping one directory group to a role here, and optionally to one of the
 * organization's groups.
 *
 * The roles offered are the ones the caller's own role strictly outranks - the
 * same arithmetic the server applies to this write, so the picker never offers a
 * role that would be refused after the rest was typed (#1028). Mounted only while
 * open, so each opening starts empty.
 */
export function DirectoryMappingDialog({ orgId, onClose }: { orgId: string; onClose: () => void }) {
  const t = useTranslations("directory");
  const tErrors = useTranslations("errors");
  const { create } = useDirectoryMappings(orgId, true);
  const { groups } = useGroups(orgId);
  const assignable = useAssignableRoles();
  const [externalGroup, setExternalGroup] = useState("");
  const [chosenRole, setChosenRole] = useState<OrgRole | "">("");
  const [groupId, setGroupId] = useState(NO_GROUP);
  const [problems, setProblems] = useState<Readonly<Record<string, string>>>({});
  // Derived rather than seeded: the catalog the offer is computed from may land
  // after the dialog opens, and a seed taken from an empty list would stay empty.
  const role = chosenRole || defaultAssignable(assignable, "member");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (role === "") return;
    try {
      await create.mutateAsync({
        external_group: externalGroup.trim(),
        role,
        group_id: groupId === NO_GROUP ? null : groupId,
      });
      onClose();
    } catch (error) {
      // An external group mapped here already is a fact about that field.
      const failure = submitFailure(
        error,
        { fields: ["external_group"], identifiedBy: "external_group" },
        tErrors,
      );
      setProblems(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    }
  };

  return (
    // Mounted only while open, so the one change of openness it can report is closing.
    <Dialog open onOpenChange={onClose}>
      <DialogContent className={DIALOG_CONFIRM}>
        <DialogHeader>
          <DialogTitle>{t("addMapping")}</DialogTitle>
          <DialogDescription>{t("dialogBody")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <FormField
            label={t("externalGroup")}
            htmlFor="mapping-external"
            description={t("externalGroupHint")}
            error={problems.external_group}
          >
            <Input
              id="mapping-external"
              value={externalGroup}
              onChange={(e) => {
                setExternalGroup(e.target.value);
                setProblems({});
              }}
              placeholder={EXAMPLE_DN}
              maxLength={MAX_EXTERNAL}
              className="font-mono text-xs"
            />
          </FormField>
          <FormField label={t("role")} htmlFor="mapping-role">
            {/* Radix hands back the value of an item below, and every item is an
                `OrgRole` from `assignable`; the members table narrows the same way. */}
            <Select value={role} onValueChange={(value) => setChosenRole(value as OrgRole)}>
              <SelectTrigger id="mapping-role" className="capitalize">
                <SelectValue placeholder={t("noRoleToOffer")} />
              </SelectTrigger>
              <SelectContent>
                {assignable.map((option) => (
                  <SelectItem key={option} value={option} className="capitalize">
                    {option}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField label={t("group")} htmlFor="mapping-group" description={t("groupHint")}>
            <Select value={groupId} onValueChange={setGroupId}>
              <SelectTrigger id="mapping-group">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_GROUP}>{t("noGroup")}</SelectItem>
                {groups.map((group) => (
                  <SelectItem key={group.id} value={group.id}>
                    {group.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("cancel")}
            </Button>
            <Button
              type="submit"
              disabled={!externalGroup.trim() || role === "" || create.isPending}
            >
              {t("add")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
