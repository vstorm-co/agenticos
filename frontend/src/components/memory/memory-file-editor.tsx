"use client";

import { useMemo, useState } from "react";
import { ShieldCheck } from "lucide-react";

import {
  Alert,
  AlertDescription,
  Button,
  DialogFooter,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { FileEditor } from "@/components/files";
import { OriginBadge, PartitionBadge } from "@/components/memory/memory-badges";
import { FORMATS, displayName } from "@/components/context/file-name";
import type { MemoryEdit } from "@/hooks/use-memory";
import type { MemoryFile } from "@/types/memory";
import { useTranslations } from "next-intl";

interface MemoryFileEditorProps {
  file: MemoryFile;
  /** A viewer reads a file; only an editor gets the write controls. */
  canEdit: boolean;
  isSaving: boolean;
  isPromoting: boolean;
  onSave: (edit: MemoryEdit) => void;
  onPromote: () => void;
  onCancel: () => void;
}

/**
 * Edit a memory file.
 *
 * The same shape as the context editor — the facts about the file in a strip at
 * the top, the body in the shared pane, one footer — with two things context
 * does not have: the origin and partition are shown (read-only facts a person
 * cannot change here), and an agent-authored file offers a Promote that marks it
 * trusted. Editing never changes the origin: a promote is the one deliberate act
 * that makes an agent's writing injectable, so it is a separate button, not a
 * side effect of saving.
 */
export function MemoryFileEditor({
  file,
  canEdit,
  isSaving,
  isPromoting,
  onSave,
  onPromote,
  onCancel,
}: MemoryFileEditorProps) {
  const t = useTranslations("memory");
  const [description, setDescription] = useState(file.description ?? "");
  const [format, setFormat] = useState(file.format);
  const [kind, setKind] = useState(file.kind);
  const [content, setContent] = useState(file.content);

  // A `<Select>` whose value matches no option renders empty, which reads as a file
  // with no format at all, so the file's own format joins the catalog.
  const formats = useMemo(() => {
    const stored = file.format.trim();
    return (FORMATS as readonly string[]).includes(stored) ? FORMATS : [...FORMATS, stored];
  }, [file.format]);

  const editedDescription = description.trim() === "" ? null : description.trim();
  const editedFormat = format;
  const editedKind = kind.trim() || file.kind;
  const changed =
    editedDescription !== file.description ||
    content !== file.content ||
    editedFormat !== file.format ||
    editedKind !== file.kind;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="space-y-4 rounded-md border p-3">
        <div className="flex flex-wrap items-start gap-4">
          <div className="w-32 shrink-0 space-y-1.5">
            <Label htmlFor="memory-kind">{t("kind")}</Label>
            <Input
              id="memory-kind"
              value={kind}
              onChange={(event) => setKind(event.target.value)}
              maxLength={32}
              readOnly={!canEdit}
            />
          </div>
          <div className="w-32 shrink-0 space-y-1.5">
            <Label htmlFor="memory-format">{t("format")}</Label>
            <Select value={format} onValueChange={setFormat} disabled={!canEdit}>
              <SelectTrigger id="memory-format" className="font-mono">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {formats.map((option) => (
                  <SelectItem key={option} value={option} className="font-mono">
                    {option}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="shrink-0 space-y-1.5">
            <Label>{t("colOrigin")}</Label>
            <div className="flex h-9 items-center gap-2">
              <OriginBadge origin={file.origin} />
              <PartitionBadge scopeKey={file.end_user_scope_key} />
            </div>
          </div>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="memory-description">{t("description")}</Label>
          <Input
            id="memory-description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder={t("descriptionPlaceholder")}
            maxLength={500}
            readOnly={!canEdit}
          />
        </div>
      </div>

      <FileEditor
        name={displayName(file.name, format)}
        content={content}
        canEdit={canEdit}
        onChange={setContent}
      />

      {file.origin === "agent" && (
        <Alert>
          <ShieldCheck className="h-4 w-4" />
          <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
            <span>{t("agentAuthoredNote")}</span>
            {canEdit && (
              <Button variant="outline" size="sm" onClick={onPromote} disabled={isPromoting}>
                {t("promote")}
              </Button>
            )}
          </AlertDescription>
        </Alert>
      )}

      <DialogFooter>
        <Button variant="outline" onClick={onCancel}>
          {canEdit ? t("cancel") : t("close")}
        </Button>
        {canEdit && (
          <Button
            onClick={() =>
              onSave({
                description: editedDescription,
                content,
                format: editedFormat,
                kind: editedKind,
              })
            }
            disabled={!changed || isSaving}
          >
            {t("save")}
          </Button>
        )}
      </DialogFooter>
    </div>
  );
}
