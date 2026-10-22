"use client";

import {
  Camera,
  ChevronRight,
  FileUp,
  FolderKanban,
  Image as ImageIcon,
  Mic,
  Paperclip,
  Plus,
  SquareSlash,
  X,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";

import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";

/** Where a file comes from: a phone's camera, its photos, or anywhere. */
export type AttachSource = "camera" | "photos" | "files";

interface ComposerSheetProps {
  onAttach: (source: AttachSource) => void;
  /** Starts dictating; absent where the organization's engine offers no microphone. */
  onVoice?: () => void;
  /** Starts a slash command; absent where the composer offers none. */
  onCommand?: () => void;
  /** Picks the project a new chat starts in; absent once the chat exists. */
  onProject?: () => void;
  /**
   * More rows for the phone's sheet: the controls that sit beside the composer
   * at a desk - the call, the model and approvals, the context used - which a
   * phone's single row has no room for.
   */
  phoneRows?: ReactNode;
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
  phoneRows,
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
      run: () => onAttach("files"),
    },
    ...(onVoice
      ? [
          {
            key: "voice",
            icon: Mic,
            label: t("voiceInput"),
            description: t("voiceInputHint"),
            run: onVoice,
          },
        ]
      : []),
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
      {/* A phone's sheet, the way a messenger's is: where a file comes from as
          three tiles, then the rest as grouped rows (#2066, #2097). */}
      <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
        <SheetContent side="bottom" className="bg-background rounded-t-3xl">
          <SheetHeader className="relative flex-row items-center justify-center border-0 pt-4">
            <button
              type="button"
              onClick={() => setSheetOpen(false)}
              aria-label={t("closeSheet")}
              className="bg-card absolute top-3 left-4 inline-flex size-10 items-center justify-center rounded-full shadow-sm"
            >
              <X className="size-5" aria-hidden />
            </button>
            <SheetTitle className="text-base font-semibold">{t("addToMessage")}</SheetTitle>
          </SheetHeader>
          <div className="flex flex-col gap-3 px-4 pt-2 pb-4">
            <div className="grid grid-cols-3 gap-2">
              {SOURCES.map(({ source, icon: Icon }) => (
                <button
                  key={source}
                  type="button"
                  disabled={disabled}
                  onClick={() => {
                    setSheetOpen(false);
                    onAttach(source);
                  }}
                  className="bg-card active:bg-card/70 flex h-24 flex-col items-center justify-center gap-2 rounded-2xl text-sm font-medium"
                >
                  <Icon className="size-6" aria-hidden />
                  {t(`source.${source}`)}
                </button>
              ))}
            </div>
            <SheetGroup>
              {actions
                .filter((action) => action.key !== "attach")
                .map((action) => (
                  <button
                    key={action.key}
                    type="button"
                    onClick={() => {
                      setSheetOpen(false);
                      action.run();
                    }}
                    className="active:bg-foreground/[0.04] flex min-h-14 w-full items-center gap-3 px-4 text-left"
                  >
                    <action.icon className="text-muted-foreground size-5 shrink-0" aria-hidden />
                    <span className="min-w-0 flex-1 text-base">{action.label}</span>
                    <ChevronRight className="text-muted-foreground size-4 shrink-0" aria-hidden />
                  </button>
                ))}
            </SheetGroup>
            {phoneRows ? <SheetGroup>{phoneRows}</SheetGroup> : null}
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}

const SOURCES: readonly { source: AttachSource; icon: typeof Camera }[] = [
  { source: "camera", icon: Camera },
  { source: "photos", icon: ImageIcon },
  { source: "files", icon: FileUp },
];

/** Rows on one card, a hairline between them - a settings list, as a phone draws one. */
function SheetGroup({ children }: { children: ReactNode }) {
  return (
    <div className="bg-card divide-border/60 flex flex-col divide-y overflow-hidden rounded-2xl">
      {children}
    </div>
  );
}

/**
 * One row of the phone's sheet for a control that is not an action of its own:
 * what it is on the left, the control itself on the right.
 */
export function SheetRow({
  icon: Icon,
  label,
  children,
}: {
  icon: typeof Camera;
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-14 items-center gap-3 px-4">
      <Icon className="text-muted-foreground size-5 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1 truncate text-base">{label}</span>
      <span className="flex shrink-0 items-center">{children}</span>
    </div>
  );
}
