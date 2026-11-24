"use client";

import { useId, useState } from "react";
import { RotateCcw } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Label,
} from "@/components/ui";
import { useWorkflowMediaScope } from "@/hooks/use-workflow-media-scope";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";

interface Props {
  runId: string;
  /** Null until the saved graph is known; a whole-run retry always creates new operations. */
  hasMedia: boolean | null;
  busy: boolean;
  onRetry: () => void;
}

export function RunRetryButton(props: Props) {
  const scope = useWorkflowMediaScope();
  return <Retry key={JSON.stringify([scope, props.runId, props.hasMedia])} {...props} />;
}

function Retry({ hasMedia, busy, onRetry }: Props) {
  const t = useTranslations("pages.workflows");
  const [open, setOpen] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const id = useId();
  const close = (next: boolean) => {
    setOpen(next);
    setAccepted(false);
  };
  const confirm = () => {
    close(false);
    onRetry();
  };
  return (
    <>
      <Button
        disabled={busy || hasMedia === null}
        onClick={() => {
          if (hasMedia) close(true);
          else onRetry();
        }}
      >
        <RotateCcw className="h-4 w-4" />
        {t("runRetry")}
      </Button>
      {open && (
        <Dialog open onOpenChange={close}>
          <DialogContent className={DIALOG_CONFIRM}>
            <DialogHeader>
              <DialogTitle>{t("mediaRunRetryTitle")}</DialogTitle>
              <DialogDescription>{t("mediaRunRetryDescription")}</DialogDescription>
            </DialogHeader>
            <div className="flex items-start gap-2">
              <Checkbox
                id={id}
                checked={accepted}
                disabled={busy}
                onCheckedChange={(checked) => setAccepted(checked === true)}
              />
              <Label htmlFor={id} className="text-sm leading-5">
                {t("mediaRetryAcknowledge")}
              </Label>
            </div>
            <div className="flex flex-wrap justify-end gap-2">
              <Button variant="outline" disabled={busy} onClick={() => close(false)}>
                {t("mediaRetryCancel")}
              </Button>
              <Button disabled={busy || !accepted} onClick={confirm}>
                {t("mediaRunRetryConfirm")}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}
