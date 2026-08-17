"use client";

import { useState } from "react";
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
import { useContextFiles } from "@/hooks/use-context";
import { submitFailure } from "@/lib/api-error";
import { cn } from "@/lib/utils";
import type { ContextMode } from "@/types/providers";
import { useTranslations } from "next-intl";

/** What the backend accepts, so an over-long value is refused before it is sent. */
const MAX_NAME = 64;
const MAX_DESCRIPTION = 500;
const MAX_FORMAT = 16;

type Field = "name" | "description" | "format" | "content";

interface CreateContextDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * New context file.
 *
 * A stacked form rather than the skills workbench, because a context file is one
 * body and no attachments - there is no folder to lay out. The one decision that
 * is never implicit is `mode`: it is a select rather than a default, because
 * injecting into every run and reading on demand are different enough that the
 * author should choose rather than discover.
 */
export function CreateContextDialog({ open, onOpenChange }: CreateContextDialogProps) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("context");
  const { create } = useContextFiles();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [format, setFormat] = useState("md");
  const [mode, setMode] = useState<ContextMode>("inject");
  const [content, setContent] = useState("");
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  const setters: Record<Field, (value: string) => void> = {
    name: setName,
    description: setDescription,
    format: setFormat,
    content: setContent,
  };

  function edit(field: Field, value: string) {
    setters[field](value);
    if (errors[field]) setErrors(({ [field]: _removed, ...rest }) => rest);
  }

  async function handleCreate() {
    try {
      await create.mutateAsync({
        name,
        // Whitespace-only means "no description" - the column is nullable and a
        // blank one says nothing to a reader of the link list.
        description: description.trim() === "" ? null : description.trim(),
        content,
        format: format.trim() || "md",
        mode,
      });
      setName("");
      setDescription("");
      setFormat("md");
      setMode("inject");
      setContent("");
      setErrors({});
      onOpenChange(false);
    } catch (error) {
      const failure = submitFailure(
        error,
        { fields: ["name", "description", "format", "content"], identifiedBy: "name" },
        tErrors,
      );
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[92vh] flex-col sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t("newContext")}</DialogTitle>
          <DialogDescription>{t("availableEveryAgentOrganization")}</DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto">
          <div className="flex flex-wrap items-start gap-4">
            <div className="w-56 shrink-0 space-y-1.5">
              <Label htmlFor="new-context-name">{t("name")}</Label>
              <Input
                id="new-context-name"
                value={name}
                onChange={(event) => edit("name", event.target.value)}
                placeholder={t("namePlaceholder")}
                maxLength={MAX_NAME}
                className="font-mono"
                aria-invalid={errors.name ? true : undefined}
              />
              <FieldNote error={errors.name}>{t("howItIsReferredTo")}</FieldNote>
            </div>
            <div className="w-40 shrink-0 space-y-1.5">
              <Label htmlFor="new-context-mode">{t("mode")}</Label>
              <Select value={mode} onValueChange={(value) => setMode(value as ContextMode)}>
                <SelectTrigger id="new-context-mode">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="inject">{t("modeInject")}</SelectItem>
                  <SelectItem value="link">{t("modeLink")}</SelectItem>
                </SelectContent>
              </Select>
              <FieldNote>{t(mode === "inject" ? "modeInjectHint" : "modeLinkHint")}</FieldNote>
            </div>
            <div className="w-28 shrink-0 space-y-1.5">
              <Label htmlFor="new-context-format">{t("format")}</Label>
              <Input
                id="new-context-format"
                value={format}
                onChange={(event) => edit("format", event.target.value)}
                placeholder={t("formatPlaceholder")}
                maxLength={MAX_FORMAT}
                className="font-mono"
                aria-invalid={errors.format ? true : undefined}
              />
              <FieldNote error={errors.format}>{t("formatHint")}</FieldNote>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="new-context-description">{t("description")}</Label>
            <Input
              id="new-context-description"
              value={description}
              onChange={(event) => edit("description", event.target.value)}
              placeholder={t("whatIsInIt")}
              maxLength={MAX_DESCRIPTION}
              aria-invalid={errors.description ? true : undefined}
            />
            <FieldNote error={errors.description}>{t("shownWhenLinked")}</FieldNote>
          </div>

          <div className="flex min-h-0 flex-1 flex-col space-y-1.5">
            <Label htmlFor="new-context-content">{t("content")}</Label>
            <Textarea
              id="new-context-content"
              value={content}
              onChange={(event) => edit("content", event.target.value)}
              placeholder={t("theBodyAsText")}
              className="min-h-56 flex-1 font-mono text-sm"
              aria-invalid={errors.content ? true : undefined}
            />
            <p
              className={cn(
                "text-xs",
                errors.content ? "text-destructive" : "text-muted-foreground",
              )}
            >
              {errors.content ?? t("textOnlyBinaryElsewhere")}
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button onClick={handleCreate} disabled={!name.trim() || create.isPending}>
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
