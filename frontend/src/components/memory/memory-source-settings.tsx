"use client";

import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import {
  Button,
  ConfirmDialog,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
} from "@/components/ui";
import { ErrorState, LoadingState } from "@/components/states";
import {
  getMemoryMailRule,
  removeMemoryMailRule,
  saveMemoryMailRule,
  type MemoryMailState,
} from "@/lib/memory-api";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";

export function MemorySourceSettings() {
  const t = useTranslations("pages.memory.library");
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        {t("sourceSettings")}
      </Button>
      {open && <MemorySourceDialog onClose={() => setOpen(false)} />}
    </>
  );
}

function MemorySourceDialog({ onClose }: { onClose: () => void }) {
  const t = useTranslations("pages.memory.library");
  const org = useOrgStore((state) => state.activeOrgId) ?? "current";
  const rule = useQuery({
    queryKey: [...qk.memory.all(org), "gmail-rule"],
    queryFn: getMemoryMailRule,
  });
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="max-h-[90dvh] overflow-auto">
        <DialogHeader>
          <DialogTitle>{t("sourceSettings")}</DialogTitle>
          <DialogDescription>{t("sourceHint")}</DialogDescription>
        </DialogHeader>
        {rule.isPending ? (
          <LoadingState variant="pending" />
        ) : rule.error ? (
          <ErrorState />
        ) : (
          <MemorySourceForm org={org} rule={rule.data ?? null} />
        )}
      </DialogContent>
    </Dialog>
  );
}

function MemorySourceForm({ org, rule }: { org: string; rule: MemoryMailState | null }) {
  const t = useTranslations("pages.memory.library");
  const tErrors = useTranslations("errors");
  const senderId = useId();
  const subjectId = useId();
  const commitmentId = useId();
  const objectKeyId = useId();
  const [mode, setMode] = useState(rule?.mode ?? "shadow");
  const [confirming, setConfirming] = useState(false);
  const client = useQueryClient();
  const key = [...qk.memory.all(org), "gmail-rule"];
  const save = useMutation({
    mutationFn: saveMemoryMailRule,
    onSuccess: (data) => client.setQueryData(key, data),
  });
  const remove = useMutation({
    mutationFn: removeMemoryMailRule,
    onSuccess: () => {
      client.setQueryData(key, null);
      setConfirming(false);
      void client.invalidateQueries({ queryKey: qk.memory.all(org) });
    },
  });
  return (
    <>
      {rule && (
        <p role="status" className="text-muted-foreground text-sm">
          {!rule.authorized ? t("sourceRevoked") : t("sourceReviewed")}
          {rule.last_outcome ? ` · ${t(`outcome.${rule.last_outcome}`)}` : null}
        </p>
      )}
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          const values = new FormData(event.currentTarget);
          const sender = values.get("sender");
          const subject = values.get("subject");
          const commitment = values.get("commitment");
          const objectKey = values.get("object_key");
          if (
            typeof sender !== "string" ||
            typeof subject !== "string" ||
            typeof commitment !== "string"
          )
            return;
          save.mutate({
            sender,
            subject,
            commitment,
            object_key: typeof objectKey === "string" ? objectKey.trim() || null : null,
            mode,
            notify: mode === "active" && values.has("notify"),
          });
        }}
      >
        <div className="space-y-1">
          <label htmlFor={senderId} className="text-sm">
            {t("sourceSender")}
          </label>
          <Input
            id={senderId}
            name="sender"
            type="email"
            maxLength={254}
            defaultValue={rule?.sender}
            required
          />
        </div>
        <div className="space-y-1">
          <label htmlFor={subjectId} className="text-sm">
            {t("sourceSubject")}
          </label>
          <Input
            id={subjectId}
            name="subject"
            maxLength={200}
            defaultValue={rule?.subject}
            required
          />
        </div>
        <div className="space-y-1">
          <label htmlFor={commitmentId} className="text-sm">
            {t("sourceCommitment")}
          </label>
          <Input
            id={commitmentId}
            name="commitment"
            maxLength={160}
            defaultValue={rule?.commitment}
            required
          />
        </div>
        <div className="space-y-1">
          <label htmlFor={objectKeyId} className="text-sm">
            {t("sourceObjectKey")}
          </label>
          <Input
            id={objectKeyId}
            name="object_key"
            maxLength={260}
            defaultValue={rule?.object_key ?? undefined}
            aria-describedby={`${objectKeyId}-hint`}
          />
          <p id={`${objectKeyId}-hint`} className="text-muted-foreground text-xs">
            {t("sourceObjectKeyHint")}
          </p>
        </div>
        <fieldset className="space-y-2">
          <legend className="mb-1 text-sm">{t("sourceMode")}</legend>
          <div className="flex flex-wrap gap-3">
            <label className="inline-flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="mode"
                value="shadow"
                checked={mode === "shadow"}
                onChange={() => setMode("shadow")}
              />
              {t("shadow")}
            </label>
            <label className="inline-flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="mode"
                value="active"
                checked={mode === "active"}
                onChange={() => setMode("active")}
              />
              {t("active")}
            </label>
          </div>
          {mode === "active" && (
            <label className="inline-flex items-center gap-2 text-sm">
              <input type="checkbox" name="notify" defaultChecked={rule?.notify} />
              {t("notify")}
            </label>
          )}
        </fieldset>
        {(save.error || remove.error) && (
          <p role="alert" className="text-sm">
            {tErrors("unexpected")}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={save.isPending || remove.isPending}>
            {t("approveSource")}
          </Button>
          {rule && (
            <Button type="button" variant="outline" onClick={() => setConfirming(true)}>
              {t("disableSource")}
            </Button>
          )}
        </div>
      </form>
      <ConfirmDialog
        loading={remove.isPending}
        destructive
        open={confirming}
        onOpenChange={setConfirming}
        title={t("disableSource")}
        description={t("disableSourceHint")}
        confirmLabel={t("disableSource")}
        onConfirm={() => remove.mutate()}
      />
    </>
  );
}
