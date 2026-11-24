"use client";

import { useTranslations } from "next-intl";
import { Mail, RotateCw } from "lucide-react";
import {
  Button,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui";
import type { Onboarding } from "@/lib/onboarding-api";
import { useStart } from "@/hooks/use-start";
import { StartCompanions } from "./start-companions";
import { StartModel } from "./start-model";

export function StartSetup({
  data,
  open,
  onOpenChange,
  onReturnFocus,
}: {
  data: Onboarding;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onReturnFocus: () => void;
}) {
  const t = useTranslations("start");
  const state = useStart();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-xl"
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          onReturnFocus();
        }}
      >
        <StartCompanions members={["byte", "nimbus", "sunny"]} />
        <DialogHeader>
          <DialogTitle>{t(data.can_prepare ? "connectTitle" : "askOwner")}</DialogTitle>
          <DialogDescription>
            {t(data.can_prepare ? "connectHint" : "askOwnerHint")}
          </DialogDescription>
        </DialogHeader>
        {data.can_prepare ? (
          <StartModel allowAdd={data.can_configure_model} onPrepared={() => onOpenChange(false)} />
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            {data.support_email && (
              <a
                className="inline-flex items-center gap-2 text-sm underline"
                href={`mailto:${data.support_email}`}
              >
                <Mail size={15} aria-hidden />
                {data.support_email}
              </a>
            )}
            <Button variant="outline" onClick={() => void state.refetch()}>
              <RotateCw size={15} aria-hidden />
              {t("checkAgain")}
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
