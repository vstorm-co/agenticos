"use client";

import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";
import {
  AudiencePicker,
  EVERYONE,
  audiencePayload,
  type Audience,
} from "@/components/sharing/audience-picker";
import { useId, useState } from "react";
import { ChevronDown } from "lucide-react";
import { toast } from "sonner";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
} from "@/components/ui";
import { FileEditor } from "@/components/files";
import {
  DEFAULT_FORMAT,
  inferContextFormat,
  displayName,
  type ContextDraft,
} from "@/components/context/file-name";
import { useContextFiles } from "@/hooks/use-context";
import { submitFailure } from "@/lib/api-error";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";
import { DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";

/** What the backend accepts, so an over-long value is refused before it is sent. */
const MAX_NAME = 64;
const MAX_DESCRIPTION = 500;

type Field = "name" | "description" | "content";

import type { ContextFile } from "@/types/providers";

interface CreateContextDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /**
   * A file somebody dropped, as the fields it becomes.
   *
   * Seeded into the state once, so the caller mounts this keyed by draft: the
   * name, format and body are then somebody's to edit like any other, and the
   * usage policy is chosen when the file is attached to an agent.
   */
  initial?: ContextDraft;
  /** How many more dropped files follow this one, for the note in the footer. */
  remaining?: number;
  /**
   * A file was created. The dialog does not close itself: whether that means
   * "done" or "next one" is the caller's queue to answer.
   */
  onCreated: (file: ContextFile) => void;
}

/**
 * New context file.
 *
 * A stacked form rather than the skills workbench, because a context file is one
 * body and no attachments - there is no folder to lay out. The body itself is the
 * same pane a skill's is written in, so what somebody types here looks like what
 * they will read afterwards.
 *
 * This edits the library entry. Whether it is injected or read on demand is
 * chosen separately when the file is attached to an agent.
 */
export function CreateContextDialog({
  open,
  onOpenChange,
  initial,
  remaining = 0,
  onCreated,
}: CreateContextDialogProps) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("context");
  const tc = useTranslations("common");
  const ta = useTranslations("audience");
  const metadataId = useId();
  const [metadataOpen, setMetadataOpen] = useState(false);
  const { create } = useContextFiles();
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState("");
  const format = inferContextFormat(name, initial?.format ?? DEFAULT_FORMAT);
  const [audience, setAudience] = useState<Audience>(EVERYONE);
  const [content, setContent] = useState(initial?.content ?? "");
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  const setters: Record<Field, (value: string) => void> = {
    name: setName,
    description: setDescription,
    content: setContent,
  };

  function edit(field: Field, value: string) {
    setters[field](value);
    if (errors[field]) setErrors(({ [field]: _removed, ...rest }) => rest);
  }

  const source = useId();
  function reset() {
    setName("");
    setDescription("");
    setContent("");
    setAudience(EVERYONE);
    setErrors({});
    setMetadataOpen(false);
  }
  const audienceWords =
    audience.mode === "chosen" && audience.group_ids.length + audience.user_ids.length > 0
      ? ta("chosen")
      : audience.mode === "private"
        ? ta("onlyMe")
        : ta("everyone");
  useUnsavedChanges(source, {
    dirty:
      open &&
      (name !== "" || description !== "" || content !== "" || audience.mode !== EVERYONE.mode),
    save: name.trim() !== "" && remaining === 0 ? handleCreate : undefined,
    discard: () => {
      reset();
      onOpenChange(false);
    },
  });
  // This dialog has no trigger: only dismissal asks to change its open state.
  function close() {
    if (!create.isPending)
      useUnsavedChangesStore.getState().leave(() => onOpenChange(false), [source]);
  }

  async function handleCreate(): Promise<boolean> {
    if (create.isPending || name.trim() === "") return false;
    try {
      const file = await create.mutateAsync({
        name,
        // Whitespace-only means "no description" - the column is nullable and a
        // blank one says nothing to a reader of the link list.
        description: description.trim() === "" ? null : description.trim(),
        content,
        format: format.trim() || DEFAULT_FORMAT,
        mode: "inject",
        ...audiencePayload(audience),
      });
      reset();
      onCreated(file);
      return true;
    } catch (error) {
      const failure = submitFailure(
        error,
        { fields: ["name", "description", "content"], identifiedBy: "name" },
        tErrors,
      );
      setErrors(failure.fields);
      if (failure.fields.description) setMetadataOpen(true);
      if (failure.toast) toast.error(failure.toast);
      return false;
    }
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent dismissible={!create.isPending} className={cn(DIALOG_COLUMN, DIALOG_FORM)}>
        <DialogHeader>
          <DialogTitle>{t("newContext")}</DialogTitle>
          <DialogDescription>{t("availableEveryAgentOrganization")}</DialogDescription>
        </DialogHeader>

        {/* `overflow-auto` is a clipping box, and a focus ring is drawn outside
            the control's own border - so the ring on the first field was sliced
            off flush against the left edge of this container. The padding gives
            it somewhere to land; the negative margin keeps the fields aligned
            with the title and the footer either side of the scroller. */}
        <div className="-mx-1.5 flex min-h-0 flex-1 flex-col gap-4 overflow-auto px-1.5 py-1">
          <fieldset disabled={create.isPending} className="min-w-0 space-y-4">
            <legend className="sr-only">{t("newContext")}</legend>
            {/* A grid that fills the row rather than three fixed widths that stop
              two thirds of the way across. The description under them is full
              width, so a short row above it read as a dialog missing its right
              hand side - and the wider the sheet, the bigger the hole. Name
              takes the slack because a name is the field that can be long. */}
            <div className="grid grid-cols-1 items-start gap-4">
              <div className="min-w-0 space-y-1.5">
                <Label htmlFor="new-context-name">{t("name")}</Label>
                <Input
                  id="new-context-name"
                  value={name}
                  onChange={(event) => edit("name", event.target.value)}
                  placeholder={t("namePlaceholder")}
                  maxLength={MAX_NAME}
                  className="font-mono"
                  aria-describedby="new-context-name-note"
                  aria-invalid={errors.name ? true : undefined}
                />
                <div id="new-context-name-note">
                  <FieldNote error={errors.name}>{t("howItIsReferredTo")}</FieldNote>
                </div>
              </div>
            </div>

            <Button
              type="button"
              variant="outline"
              size="sm"
              className="w-full justify-between md:hidden"
              aria-expanded={metadataOpen}
              aria-controls={metadataId}
              onClick={() => setMetadataOpen(!metadataOpen)}
            >
              <span>
                {tc("details")} · {audienceWords}
              </span>
              <ChevronDown
                aria-hidden
                className={cn("size-4 shrink-0", metadataOpen && "rotate-180")}
              />
            </Button>
            <div id={metadataId} className={cn("space-y-4", !metadataOpen && "max-md:hidden")}>
              <div className="space-y-1.5">
                <Label htmlFor="new-context-description">{t("description")}</Label>
                <Input
                  id="new-context-description"
                  value={description}
                  onChange={(event) => edit("description", event.target.value)}
                  placeholder={t("whatIsInIt")}
                  maxLength={MAX_DESCRIPTION}
                  aria-describedby="new-context-description-note"
                  aria-invalid={errors.description ? true : undefined}
                />
                <div id="new-context-description-note">
                  <FieldNote error={errors.description}>{t("shownWhenLinked")}</FieldNote>
                </div>
              </div>

              <div className="space-y-1.5">
                <Label>{t("whoCanUseIt")}</Label>
                <AudiencePicker value={audience} onChange={setAudience} />
              </div>
            </div>

            {/* The pane the file will be read in once it exists, rather than a
              textarea that becomes one on save - the same one a skill's body is
              written in. Named from what has been typed so far, so the preview
              renders as the format the file is being given. */}
            <FileEditor
              initialMode="source"
              // The placeholder until a name is typed, which is what the name
              // field itself shows: `.md` alone reads as a broken filename, and
              // the extension is what decides how the preview renders.
              name={displayName(name.trim() || t("namePlaceholder"), format)}
              content={content}
              canEdit={!create.isPending}
              placeholder={t("bodyPlaceholder")}
              className="min-h-72"
              onChange={(next) => edit("content", next)}
              footer={
                <p
                  className={cn(
                    "text-xs",
                    errors.content ? "text-destructive" : "text-muted-foreground",
                  )}
                >
                  {errors.content ?? t("textOnlyBinaryElsewhere")}
                </p>
              }
            />
          </fieldset>
        </div>

        <DialogFooter>
          {remaining > 0 && (
            <p className="text-muted-foreground mr-auto self-center text-xs">
              {t("moreFilesWaiting", { count: remaining })}
            </p>
          )}
          <Button variant="outline" onClick={close} disabled={create.isPending}>
            {t("cancel")}
          </Button>
          <Button onClick={handleCreate} loading={create.isPending} disabled={!name.trim()}>
            {t("create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** A field's helper line, or the refusal that replaced it. */
function FieldNote({ error, children }: { error?: string; children?: React.ReactNode }) {
  if (error) return <p className="text-destructive text-xs">{error}</p>;
  return <p className="text-muted-foreground text-xs">{children}</p>;
}
