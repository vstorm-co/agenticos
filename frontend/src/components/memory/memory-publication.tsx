"use client";

import { useId, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useGroups } from "@/hooks/use-groups";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";

export function MemoryPublication({
  publish,
}: {
  publish: (group: string | null) => Promise<unknown>;
}) {
  const t = useTranslations("pages.memory.library");
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}>
        {t("share")}
      </Button>
      {open && <AudienceDialog onClose={() => setOpen(false)} publish={publish} />}
    </>
  );
}

function AudienceDialog({
  onClose,
  publish,
}: {
  onClose: () => void;
  publish: (group: string | null) => Promise<unknown>;
}) {
  const t = useTranslations("pages.memory.library");
  const audienceId = useId();
  const org = useOrgStore((state) => state.activeOrgId) ?? "";
  const { groups } = useGroups(org);
  const client = useQueryClient();
  const [audience, setAudience] = useState("");
  const [pending, setPending] = useState(false);
  const [outcome, setOutcome] = useState<"idle" | "saved" | "error">("idle");
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !pending) onClose();
      }}
    >
      <DialogContent dismissible={!pending}>
        <DialogHeader>
          <DialogTitle>{t("share")}</DialogTitle>
          <DialogDescription>{t("shareHint")}</DialogDescription>
        </DialogHeader>
        <label htmlFor={audienceId} className="text-sm font-medium">
          {t("audience")}
        </label>
        <Select
          value={audience}
          onValueChange={setAudience}
          disabled={pending || outcome === "saved"}
        >
          <SelectTrigger id={audienceId}>
            <SelectValue placeholder={t("audience")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="organization">{t("wholeOrganization")}</SelectItem>
            {groups.map((group) => (
              <SelectItem key={group.id} value={group.id}>
                {group.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {outcome === "error" && (
          <p role="alert" className="text-sm">
            {t("shareFailure")}
          </p>
        )}
        {outcome === "saved" && (
          <p role="status" className="text-sm">
            {t("published")}
          </p>
        )}
        <DialogFooter>
          {outcome === "saved" ? (
            <Button onClick={onClose}>{t("close")}</Button>
          ) : (
            <Button
              disabled={!audience || pending}
              onClick={async () => {
                setPending(true);
                try {
                  await publish(audience === "organization" ? null : audience);
                  await client.invalidateQueries({ queryKey: qk.memory.all(org || "current") });
                  setOutcome("saved");
                } catch {
                  setOutcome("error");
                } finally {
                  setPending(false);
                }
              }}
            >
              {t("confirmShare")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
