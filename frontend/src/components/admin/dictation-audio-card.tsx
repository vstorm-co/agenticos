"use client";

import { useState } from "react";
import { TriangleAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Label,
  ListCard,
  Switch,
} from "@/components/ui";
import { DIALOG_CONFIRM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";

const RISKS = ["riskLength", "riskPublic", "riskScope"] as const;

export interface DictationAudioCardProps {
  /** The draft's `dictation_compressed_audio`. */
  checked: boolean;
  disabled: boolean;
  onChange: (accept: boolean) => void;
}

/**
 * Whether dictation accepts compressed recordings, deployment-wide (#1797).
 *
 * Off, every browser records 16 kHz mono PCM WAV, whose length is its size,
 * so the longest dictation bounds what one recording costs. Turning it on
 * trades that bound for uploads about half the size, so it goes through
 * a dialog naming the risks and a box ticked to say they were read; turning
 * it off is the safe direction and needs neither. Either way the change is a
 * draft until the page is saved, like every other field on it.
 */
export function DictationAudioCard({ checked, disabled, onChange }: DictationAudioCardProps) {
  const t = useTranslations("pages.adminDictation");
  const [asking, setAsking] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);

  const close = () => {
    setAsking(false);
    setAcknowledged(false);
  };

  return (
    <ListCard title={t("title")} counted={t("hint")}>
      <div className="border-border flex items-start justify-between gap-4 rounded-xl border p-4">
        <div className="min-w-0">
          <p className="text-foreground text-sm font-medium">{t("toggle")}</p>
          <p className="text-muted-foreground mt-0.5 text-xs">{t("toggleHint")}</p>
        </div>
        <Switch
          checked={checked}
          onCheckedChange={(accept) => (accept ? setAsking(true) : onChange(false))}
          disabled={disabled}
          aria-label={t("toggle")}
        />
      </div>

      {/* No trigger inside it, so the dialog only ever asks to close. */}
      <Dialog open={asking} onOpenChange={close}>
        <DialogContent className={cn(DIALOG_CONFIRM, DIALOG_SCROLL)}>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <TriangleAlert className="text-warning h-5 w-5 shrink-0" aria-hidden />
              {t("dialogTitle")}
            </DialogTitle>
            <DialogDescription>{t("dialogIntro")}</DialogDescription>
          </DialogHeader>

          <ul className="text-foreground list-disc space-y-2 pl-5 text-sm">
            {RISKS.map((risk) => (
              <li key={risk}>{t(risk)}</li>
            ))}
          </ul>
          <p className="text-muted-foreground text-sm">{t("benefit")}</p>

          <div className="flex items-start gap-2">
            <Checkbox
              id="dictation-compressed-ack"
              checked={acknowledged}
              onCheckedChange={(value) => setAcknowledged(value === true)}
              className="mt-0.5"
            />
            <Label htmlFor="dictation-compressed-ack" className="text-sm leading-snug">
              {t("acknowledge")}
            </Label>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={close}>
              {t("cancel")}
            </Button>
            <Button
              variant="destructive"
              disabled={!acknowledged}
              onClick={() => {
                onChange(true);
                close();
              }}
            >
              {t("confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </ListCard>
  );
}
