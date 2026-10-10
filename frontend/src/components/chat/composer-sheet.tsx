"use client";

import { Mic, Paperclip, Plus } from "lucide-react";
import { useState } from "react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";

interface ComposerSheetProps {
  onAttach: () => void;
  onVoice: () => void;
  disabled?: boolean;
}

/**
 * What a phone's composer adds to a message, behind one `+` (#2066).
 *
 * Two 36px icons a thumb has to hit beside the agent picker and the send button
 * is a desktop toolbar shrunk onto a phone. On a phone they open as an action
 * sheet of full-width rows instead, the way messaging apps offer them; at a desk
 * the composer keeps its icons.
 */
export function ComposerSheet({ onAttach, onVoice, disabled }: ComposerSheetProps) {
  const t = useTranslations("chat.input");
  const [open, setOpen] = useState(false);
  const pick = (action: () => void) => () => {
    setOpen(false);
    action();
  };
  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        onClick={() => setOpen(true)}
        disabled={disabled}
        className="h-9 w-9 shrink-0 active:scale-90 md:hidden"
        aria-label={t("addToMessage")}
        title={t("addToMessage")}
      >
        <Plus className="text-muted-foreground h-5 w-5" />
      </Button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="bottom">
          <SheetHeader>
            <SheetTitle className="text-base">{t("addToMessage")}</SheetTitle>
          </SheetHeader>
          <div className="flex flex-col p-2">
            <SheetRow icon={Paperclip} label={t("attachFile")} onClick={pick(onAttach)} />
            <SheetRow icon={Mic} label={t("voiceInput")} onClick={pick(onVoice)} />
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}

function SheetRow({
  icon: Icon,
  label,
  onClick,
}: {
  icon: typeof Mic;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="hover:bg-foreground/[0.04] active:bg-foreground/[0.08] flex min-h-14 items-center gap-3 rounded-xl px-4 text-left text-base"
    >
      <Icon className="text-muted-foreground h-5 w-5" aria-hidden />
      {label}
    </button>
  );
}
