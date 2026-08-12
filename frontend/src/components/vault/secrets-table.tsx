"use client";

import { Lock, RotateCw, Trash2, Users } from "lucide-react";

import { ProviderIcon } from "@/components/vault/provider-icon";
import {
  Avatar,
  AvatarFallback,
  AvatarImage,
  Badge,
  Button,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui";
import { cn } from "@/lib/utils";
import type { Secret, SecretPurpose } from "@/types/secrets";
import { useTranslations } from "next-intl";

interface SecretsTableProps {
  secrets: readonly Secret[];
  purposes: readonly SecretPurpose[];
  canManage: boolean;
  onShare: (secret: Secret) => void;
  onRotate: (secret: Secret) => void;
  onDelete: (secret: Secret) => void;
}

/** What a key is for, in words, falling back to the stored id for a custom one. */
function purposeLabel(
  purposes: readonly SecretPurpose[],
  purpose: string | undefined,
  t: (key: string) => string,
): string {
  if (!purpose || purpose === "custom") return t("customService");
  return purposes.find((entry) => entry.id === purpose)?.label ?? purpose;
}

/**
 * How far one key reaches, in the words the sharing panel uses.
 *
 * Visibility and share count are two different facts and the listing shows
 * both: an organization-wide key reaches everybody whatever the grants say, and
 * a private key shared with four people is a different thing from a private key
 * shared with nobody. Collapsing them into one number is how somebody deletes
 * the wrong key.
 */
function reach(
  secret: Secret,
  t: (key: string, values?: Record<string, number>) => string,
): { label: string; detail: string | null } {
  const shared = secret.shared_with ?? 0;
  const sharedWith = shared === 0 ? null : t("sharedWithPeople", { count: shared });
  if (secret.visibility === "private") return { label: t("visibilityPrivate"), detail: sharedWith };
  if (secret.visibility === "team") return { label: t("visibilityTeam"), detail: sharedWith };
  return { label: t("visibilityOrg"), detail: null };
}

/** Two letters for a face nobody uploaded, and nothing at all for nobody. */
function initials(email: string | null | undefined): string {
  return (email ?? "?").slice(0, 2).toUpperCase();
}

/**
 * The organization's keys, one row each.
 *
 * A table rather than cards because every question asked here is a comparison
 * across rows - which of these is private, who added that one, what is holding
 * up which agent - and cards put the answers in different places on every row.
 */
export function SecretsTable({
  secrets,
  purposes,
  canManage,
  onShare,
  onRotate,
  onDelete,
}: SecretsTableProps) {
  const t = useTranslations("vault");
  const tc = useTranslations("common");
  return (
    <Table
      className={cn(
        // The card's own gutter on the outer columns: `Table` pads cells by 2
        // units, which inside a card leaves the first column starting left of
        // the header above it and the action buttons touching the border.
        "[&_td:first-child]:pl-5 [&_td:last-child]:pr-5 [&_th:first-child]:pl-5 [&_th:last-child]:pr-5",
        // Rows tall enough for the avatar and the two-line key cell.
        "[&_td]:py-3",
        // The card already draws the bottom edge; a second line under the last
        // row reads as an empty row.
        "[&_tr:last-child]:border-0",
      )}
    >
      <TableHeader>
        <TableRow>
          <TableHead>{t("key")}</TableHead>
          <TableHead>{t("for")}</TableHead>
          <TableHead>{t("access")}</TableHead>
          <TableHead>{t("addedBy")}</TableHead>
          <TableHead>{t("usedBy")}</TableHead>
          {canManage && <TableHead className="w-32 text-right">{t("actions")}</TableHead>}
        </TableRow>
      </TableHeader>
      <TableBody>
        {secrets.map((secret) => {
          const access = reach(secret, t);
          const used = secret.used_by ?? [];
          return (
            <TableRow key={secret.id}>
              <TableCell>
                <div className="flex items-center gap-3">
                  {/* The service's own mark. A vault is scanned, not read:
                      fifty rows of identical text is a list nobody finds
                      anything in, and the logo is what the eye lands on. */}
                  <ProviderIcon provider={secret.purpose ?? "custom"} />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{secret.name}</p>
                    <p className="text-muted-foreground font-mono text-xs">····{secret.hint}</p>
                  </div>
                </div>
              </TableCell>

              <TableCell className="text-muted-foreground text-sm">
                {purposeLabel(purposes, secret.purpose, t)}
              </TableCell>

              <TableCell>
                <div className="flex flex-col items-start gap-1">
                  <Badge variant={secret.visibility === "private" ? "outline" : "secondary"}>
                    {secret.visibility === "private" && <Lock className="mr-1 h-3 w-3" />}
                    {access.label}
                  </Badge>
                  {access.detail && (
                    <span className="text-muted-foreground text-xs">{access.detail}</span>
                  )}
                </div>
              </TableCell>

              <TableCell>
                {secret.created_by_email ? (
                  <div className="flex items-center gap-2">
                    <Avatar className="h-6 w-6">
                      {secret.created_by_avatar_url && (
                        <AvatarImage src={secret.created_by_avatar_url} alt="" />
                      )}
                      <AvatarFallback className="text-[10px]">
                        {initials(secret.created_by_email)}
                      </AvatarFallback>
                    </Avatar>
                    <span className="text-muted-foreground truncate text-xs">
                      {secret.created_by_email}
                    </span>
                  </div>
                ) : (
                  // The key outlives the person, which is itself worth seeing:
                  // it is the one nobody is going to rotate.
                  <span className="text-muted-foreground text-xs">{t("noLongerHere")}</span>
                )}
              </TableCell>

              <TableCell className="text-muted-foreground text-xs">
                {used.length === 0 ? t("notUsedYet") : used.map((usage) => usage.name).join(", ")}
              </TableCell>

              {canManage && (
                <TableCell>
                  <div className="flex justify-end gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={t("manageAccessTo", { name: secret.name })}
                      onClick={() => onShare(secret)}
                    >
                      <Users className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={t("rotateNamed", { name: secret.name })}
                      onClick={() => onRotate(secret)}
                    >
                      <RotateCw className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={tc("deleteNamed", { name: secret.name })}
                      onClick={() => onDelete(secret)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </TableCell>
              )}
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
