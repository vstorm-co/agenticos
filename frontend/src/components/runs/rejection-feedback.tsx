"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Button, Textarea } from "@/components/ui";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

// Both approval decision APIs cap the existing `note` at 500 characters.
const MAX_NOTE_LENGTH = 500;

export function RejectionFeedback({
  requests,
  disabled,
  onReject,
}: {
  requests: { id: string; label?: string }[];
  disabled: boolean;
  onReject: (notes: (string | undefined)[]) => void;
}) {
  const t = useTranslations("approvalFeedback");
  const common = useTranslations("common");
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const notes = requests.map(({ id }) => drafts[id]?.trim() || undefined);
  const batch = requests.length > 1;

  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button type="button" size="sm" variant="ghost" disabled={disabled}>
          {t("trigger")}
        </Button>
      </DialogTrigger>
      <DialogContent mobilePresentation="sheet">
        <DialogHeader>
          <DialogTitle>{t("trigger")}</DialogTitle>
          <DialogDescription>{t(batch ? "batchHint" : "hint")}</DialogDescription>
        </DialogHeader>
        <form
          className="min-w-0 space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (!disabled && notes.some(Boolean)) onReject(notes);
          }}
        >
          {requests.map(({ id, label }, index) => (
            <label key={id} className="block space-y-1.5 text-sm font-medium">
              <span>
                {batch ? t("call", { number: index + 1, action: label ?? "" }) : t("comment")}
              </span>
              <Textarea
                data-initial-focus={index === 0 ? "" : undefined}
                disabled={disabled}
                maxLength={MAX_NOTE_LENGTH}
                value={drafts[id] ?? ""}
                onChange={(event) => {
                  const value = event.target.value;
                  setDrafts((current) => ({ ...current, [id]: value }));
                }}
              />
            </label>
          ))}
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                {common("cancel")}
              </Button>
            </DialogClose>
            <Button type="submit" variant="destructive" disabled={disabled || !notes.some(Boolean)}>
              {t(batch ? "rejectAll" : "submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
