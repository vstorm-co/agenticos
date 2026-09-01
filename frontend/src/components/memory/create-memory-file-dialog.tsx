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
} from "@/components/ui";
import { FileEditor } from "@/components/files";
import { DEFAULT_FORMAT, FORMATS, displayName } from "@/components/context/file-name";
import { useMemoryFiles } from "@/hooks/use-memory";
import { submitFailure } from "@/lib/api-error";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";
import { DIALOG_COLUMN, DIALOG_WIDE } from "@/lib/dialog-sizes";

/** What the backend accepts, so an over-long value is refused before it is sent. */
const MAX_NAME = 64;
const MAX_KIND = 32;
const MAX_DESCRIPTION = 500;
const DEFAULT_KIND = "note";

type Field = "name" | "description" | "format" | "kind" | "content";

interface CreateMemoryFileDialogProps {
  agentId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * New operator memory file — a trusted, injectable record, always written to the
 * shared store.
 *
 * Operators author the company memory every end-user shares; a file scoped to
 * one person is the agent's own to write, from what it learns in that person's
 * runs. So there is no partition picker here: the file lands in `shared`, and
 * `origin=operator` is set server-side.
 */
export function CreateMemoryFileDialog({
  agentId,
  open,
  onOpenChange,
}: CreateMemoryFileDialogProps) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("memory");
  const { create } = useMemoryFiles({ agentId });
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [format, setFormat] = useState<string>(DEFAULT_FORMAT);
  const [kind, setKind] = useState(DEFAULT_KIND);
  const [content, setContent] = useState("");
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  const setters: Record<Field, (value: string) => void> = {
    name: setName,
    description: setDescription,
    format: setFormat,
    kind: setKind,
    content: setContent,
  };

  function edit(field: Field, value: string) {
    setters[field](value);
    if (errors[field]) setErrors(({ [field]: _removed, ...rest }) => rest);
  }

  function reset() {
    setName("");
    setDescription("");
    setFormat(DEFAULT_FORMAT);
    setKind(DEFAULT_KIND);
    setContent("");
    setErrors({});
  }

  async function handleCreate() {
    try {
      await create.mutateAsync({
        name,
        description: description.trim() === "" ? null : description.trim(),
        content,
        format: format.trim() || DEFAULT_FORMAT,
        kind: kind.trim() || DEFAULT_KIND,
        end_user_scope_key: null,
      });
      reset();
      onOpenChange(false);
    } catch (error) {
      const failure = submitFailure(
        error,
        { fields: ["name", "description", "format", "kind", "content"], identifiedBy: "name" },
        tErrors,
      );
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(DIALOG_COLUMN, DIALOG_WIDE)}>
        <DialogHeader>
          <DialogTitle>{t("newFile")}</DialogTitle>
          <DialogDescription>{t("newFileHint")}</DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto">
          <div className="flex flex-wrap items-start gap-4">
            <div className="w-56 shrink-0 space-y-1.5">
              <Label htmlFor="new-memory-name">{t("name")}</Label>
              <Input
                id="new-memory-name"
                value={name}
                onChange={(event) => edit("name", event.target.value)}
                placeholder={t("namePlaceholder")}
                maxLength={MAX_NAME}
                className="font-mono"
                aria-invalid={errors.name ? true : undefined}
              />
              <FieldNote error={errors.name}>{t("nameNote")}</FieldNote>
            </div>
            <div className="w-32 shrink-0 space-y-1.5">
              <Label htmlFor="new-memory-kind">{t("kind")}</Label>
              <Input
                id="new-memory-kind"
                value={kind}
                onChange={(event) => edit("kind", event.target.value)}
                placeholder={t("kindPlaceholder")}
                maxLength={MAX_KIND}
                aria-invalid={errors.kind ? true : undefined}
              />
              <FieldNote error={errors.kind}>{t("kindNote")}</FieldNote>
            </div>
            <div className="w-32 shrink-0 space-y-1.5">
              <Label htmlFor="new-memory-format">{t("format")}</Label>
              <Select value={format} onValueChange={(value) => edit("format", value)}>
                <SelectTrigger id="new-memory-format" className="font-mono">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {FORMATS.map((option) => (
                    <SelectItem key={option} value={option} className="font-mono">
                      {option}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <FieldNote error={errors.format}>{t("formatNote")}</FieldNote>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="new-memory-description">{t("description")}</Label>
            <Input
              id="new-memory-description"
              value={description}
              onChange={(event) => edit("description", event.target.value)}
              placeholder={t("descriptionPlaceholder")}
              maxLength={MAX_DESCRIPTION}
              aria-invalid={errors.description ? true : undefined}
            />
            <FieldNote error={errors.description}>{t("descriptionNote")}</FieldNote>
          </div>

          <FileEditor
            name={displayName(name.trim() || t("namePlaceholder"), format)}
            content={content}
            canEdit
            className="min-h-72"
            onChange={(next) => edit("content", next)}
            footer={
              <p
                className={cn(
                  "text-xs",
                  errors.content ? "text-destructive" : "text-muted-foreground",
                )}
              >
                {errors.content ?? t("bodyNote")}
              </p>
            }
          />
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
