"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Shield, Trash2 } from "lucide-react";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { SubjectPicker } from "@/components/sharing/subject-picker";
import { parseSubject } from "@/components/sharing/grants";
import { useGroups, useMembers } from "@/hooks";
import { useRecordAccess } from "@/hooks/use-record-access";
import { getErrorMessage } from "@/lib/api-error";
import type {
  RecordAccessLevel,
  RecordGrant,
  RecordGrantInput,
} from "@/lib/table-record-access-api";
import { useOrgStore } from "@/stores";

function inputFor(grant: RecordGrant, level: RecordAccessLevel): RecordGrantInput {
  return {
    ...(grant.subject_group_id
      ? { subject_group_id: grant.subject_group_id }
      : { subject_user_id: grant.subject_user_id! }),
    level,
    expires_at: grant.expires_at,
  };
}

function RecordAccessForm({ tableId, recordId }: { tableId: string; recordId: string }) {
  const t = useTranslations("tables.access");
  const errors = useTranslations("errors");
  const locale = useLocale();
  const orgId = useOrgStore((state) => state.activeOrgId) ?? "";
  const { members } = useMembers(orgId);
  const { groups } = useGroups(orgId);
  const { data, isLoading, error, share, revoke } = useRecordAccess(tableId, recordId);
  const [subject, setSubject] = useState("");
  const [level, setLevel] = useState<RecordAccessLevel>("read");
  const [expires, setExpires] = useState("");
  const [openedAt] = useState(() => Date.now());
  const pending = share.isPending || revoke.isPending;

  if (isLoading) return <p role="status">{t("loading")}</p>;
  if (error) return <p role="alert">{getErrorMessage(error, errors)}</p>;

  return (
    <div className="space-y-5">
      <p className="text-muted-foreground text-sm">{t("tableRequired")}</p>
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (!subject) return;
          const chosen = parseSubject(subject);
          share.mutate(
            {
              ...(chosen.kind === "user"
                ? { subject_user_id: chosen.id }
                : { subject_group_id: chosen.id }),
              level,
              expires_at: expires ? new Date(expires).toISOString() : null,
            },
            {
              onSuccess: () => {
                setSubject("");
                setExpires("");
              },
            },
          );
        }}
      >
        <div className="space-y-1.5">
          <Label htmlFor="record-access-subject">{t("personOrGroup")}</Label>
          <SubjectPicker
            id="record-access-subject"
            members={members}
            groups={groups}
            value={subject}
            onChange={setSubject}
            placeholder={t("chooseSubject")}
            disabled={pending}
          />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="record-access-level">{t("permission")}</Label>
            <Select
              value={level}
              onValueChange={(value) => setLevel(value === "write" ? "write" : "read")}
              disabled={pending}
            >
              <SelectTrigger id="record-access-level">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="read">{t("read")}</SelectItem>
                <SelectItem value="write">{t("write")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="record-access-expiry">{t("expiry")}</Label>
            <Input
              id="record-access-expiry"
              type="datetime-local"
              value={expires}
              onChange={(event) => setExpires(event.target.value)}
              disabled={pending}
            />
          </div>
        </div>
        <p className="text-muted-foreground text-xs">{t("expiryHelp")}</p>
        <Button type="submit" disabled={!subject || pending}>
          {t("add")}
        </Button>
      </form>
      <section className="space-y-2">
        <h3 className="text-sm font-medium">{t("grants")}</h3>
        {data?.grants.length === 0 && <p className="text-muted-foreground text-sm">{t("empty")}</p>}
        <ul className="divide-border divide-y">
          {data?.grants.map((grant) => {
            const label =
              grant.subject_group_name ??
              grant.subject_email ??
              grant.subject_group_id ??
              grant.subject_user_id ??
              "";
            const expired =
              grant.expires_at !== null && new Date(grant.expires_at).getTime() <= openedAt;
            return (
              <li key={grant.id} className="flex items-center gap-2 py-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm">{label}</p>
                  {grant.expires_at && (
                    <p className="text-muted-foreground text-xs">
                      {expired
                        ? t("expired")
                        : t("expires", { date: new Date(grant.expires_at).toLocaleString(locale) })}
                    </p>
                  )}
                </div>
                <Select
                  value={grant.level}
                  disabled={pending || expired}
                  onValueChange={(value) =>
                    share.mutate(inputFor(grant, value === "write" ? "write" : "read"))
                  }
                >
                  <SelectTrigger className="w-28" aria-label={t("permissionFor", { name: label })}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="read">{t("read")}</SelectItem>
                    <SelectItem value="write">{t("write")}</SelectItem>
                  </SelectContent>
                </Select>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={t("removeFor", { name: label })}
                  disabled={pending}
                  onClick={() =>
                    revoke.mutate(
                      grant.subject_group_id
                        ? { kind: "group", id: grant.subject_group_id }
                        : { kind: "user", id: grant.subject_user_id! },
                    )
                  }
                >
                  <Trash2 className="size-4" />
                </Button>
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}

/** Mounted only when the server says this row's audience may be managed. */
export function RecordAccessDialog({ tableId, recordId }: { tableId: string; recordId: string }) {
  const t = useTranslations("tables.access");
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)} data-tour="record-access">
        <Shield className="size-3.5" />
        {t("manage")}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("title")}</DialogTitle>
            <DialogDescription>{t("writeHelp")}</DialogDescription>
          </DialogHeader>
          {open && <RecordAccessForm key={recordId} tableId={tableId} recordId={recordId} />}
        </DialogContent>
      </Dialog>
    </>
  );
}
