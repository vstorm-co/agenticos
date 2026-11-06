"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
} from "@/components/ui";
import { useEditReplyExpectation } from "@/hooks/use-workflow-runs";
import type { ReplyExpectation } from "@/lib/workflows/types";

export function ReplyExpectationControl({
  runId,
  nodeRunId,
  value,
  editable,
}: {
  runId: string;
  nodeRunId: string;
  value: ReplyExpectation;
  editable: boolean;
}) {
  const t = useTranslations("pages.workflows");
  const [open, setOpen] = useState(false);
  return (
    <div className="space-y-2 px-2 text-sm">
      <p>
        {t(value.paused ? "replyPaused" : "replyWaiting", {
          sender: value.expected_sender,
          deadline: value.deadline,
        })}
      </p>
      {editable && (
        <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
          {t("replyEdit")}
        </Button>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("replyEdit")}</DialogTitle>
          </DialogHeader>
          {open && (
            <ReplyExpectationForm
              runId={runId}
              nodeRunId={nodeRunId}
              value={value}
              onDone={() => setOpen(false)}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ReplyExpectationForm({
  runId,
  nodeRunId,
  value,
  onDone,
}: {
  runId: string;
  nodeRunId: string;
  value: ReplyExpectation;
  onDone: () => void;
}) {
  const t = useTranslations("pages.workflows");
  const edit = useEditReplyExpectation(runId, nodeRunId);
  const [paused, setPaused] = useState(value.paused);
  const [review, setReview] = useState(false);
  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        const text = (name: string) => String(form.get(name) ?? "");
        edit.mutate(
          {
            thread_id: text("thread"),
            expected_sender: text("sender"),
            not_before: text("after"),
            deadline: text("deadline"),
            anchor_message_id: text("anchor") || null,
            paused,
            review_mailbox: review,
          },
          { onSuccess: onDone },
        );
      }}
    >
      <p className="text-muted-foreground text-xs">
        {t("replyScope", { provider: value.provider, account: value.connection_id })}
      </p>
      {(
        [
          ["thread", "replyThread", value.thread_id, "text"],
          ["sender", "replySender", value.expected_sender, "email"],
          ["after", "replyAfter", value.not_before, "text"],
          ["deadline", "replyDeadline", value.deadline, "text"],
          ["anchor", "replyAnchor", value.anchor_message_id ?? "", "text"],
        ] as const
      ).map(([name, label, initial, type]) => (
        <div key={name} className="space-y-1">
          <Label htmlFor={`reply-${nodeRunId}-${name}`}>{t(label)}</Label>
          <Input
            id={`reply-${nodeRunId}-${name}`}
            name={name}
            type={type}
            defaultValue={initial}
            required={name !== "anchor"}
            maxLength={
              name === "thread" ? 2048 : name === "sender" ? 320 : name === "anchor" ? 998 : 80
            }
          />
        </div>
      ))}
      <Label className="flex gap-2">
        <Checkbox checked={paused} onCheckedChange={(checked) => setPaused(checked === true)} />
        {t("replyPause")}
      </Label>
      <Label className="flex gap-2">
        <Checkbox checked={review} onCheckedChange={(checked) => setReview(checked === true)} />
        {t("replyReview")}
      </Label>
      <Button type="submit" disabled={edit.isPending}>
        {t("replySave")}
      </Button>
    </form>
  );
}
