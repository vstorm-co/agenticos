"use client";

import { FolderKanban, Mic, Paperclip, Plus, SquareSlash } from "lucide-react";
import { useState } from "react";
import { useTranslations } from "next-intl";

import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";

interface ComposerSheetProps {
  onAttach: () => void;
  onVoice: () => void;
  /** Starts a slash command; absent where the composer offers none. */
  onCommand?: () => void;
  /** Picks the project a new chat starts in; absent once the chat exists. */
  onProject?: () => void;
  disabled?: boolean;
}

interface Action {
  key: string;
  icon: typeof Mic;
  label: string;
  description: string;
  run: () => void;
}

/**
 * What a message can be given besides text, behind one `+`.
 *
 * A row of bare icons - a paperclip, a microphone - says nothing to somebody who
 * has not met them, and grew by one icon per thing the composer learned. Each
 * action here has a name and a line saying what it does. At a desk they open as a
 * menu over the `+`; on a phone as an action sheet of full-width rows, the way
 * messaging apps offer them (#2066).
 */
export function ComposerSheet({
  onAttach,
  onVoice,
  onCommand,
  onProject,
  disabled,
}: ComposerSheetProps) {
  const t = useTranslations("chat.input");
  const [sheetOpen, setSheetOpen] = useState(false);
  const actions: Action[] = [
    {
      key: "attach",
      icon: Paperclip,
      label: t("attachFile"),
      description: t("attachFileHint"),
      run: onAttach,
    },
    {
      key: "voice",
      icon: Mic,
      label: t("voiceInput"),
      description: t("voiceInputHint"),
      run: onVoice,
    },
    ...(onCommand
      ? [
          {
            key: "command",
            icon: SquareSlash,
            label: t("commands"),
            description: t("commandsHint"),
            run: onCommand,
          },
        ]
      : []),
    ...(onProject
      ? [
          {
            key: "project",
            icon: FolderKanban,
            label: t("project"),
            description: t("projectHint"),
            run: onProject,
          },
        ]
      : []),
  ];
  const trigger = (className: string, onClick?: () => void) => (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      onClick={onClick}
      disabled={disabled}
      className={className}
      aria-label={t("addToMessage")}
      title={t("addToMessage")}
    >
      <Plus className="text-muted-foreground h-5 w-5" />
    </Button>
  );

  return (
    <>
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          {trigger("hidden h-9 w-9 shrink-0 md:inline-flex")}
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" side="top" sideOffset={8} className="w-80 p-1.5">
          {actions.map((action) => (
            <DropdownMenuItem
              key={action.key}
              onSelect={action.run}
              className="items-start gap-3 rounded-lg px-2.5 py-2"
            >
              <action.icon className="text-muted-foreground mt-0.5 size-4 shrink-0" aria-hidden />
              <span className="min-w-0">
                <span className="block text-sm font-medium">{action.label}</span>
                <span className="text-muted-foreground block text-xs leading-snug">
                  {action.description}
                </span>
              </span>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      {trigger("h-9 w-9 shrink-0 active:scale-90 md:hidden", () => setSheetOpen(true))}
      <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
        <SheetContent side="bottom">
          <SheetHeader>
            <SheetTitle className="text-base">{t("addToMessage")}</SheetTitle>
          </SheetHeader>
          <div className="flex flex-col p-2">
            {actions.map((action) => (
              <button
                key={action.key}
                type="button"
                onClick={() => {
                  setSheetOpen(false);
                  action.run();
                }}
                className="hover:bg-foreground/[0.04] active:bg-foreground/[0.08] flex min-h-14 items-center gap-3 rounded-xl px-4 py-2 text-left"
              >
                <action.icon className="text-muted-foreground h-5 w-5 shrink-0" aria-hidden />
                <span className="min-w-0">
                  <span className="block text-base">{action.label}</span>
                  <span className="text-muted-foreground block text-xs">{action.description}</span>
                </span>
              </button>
            ))}
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}
