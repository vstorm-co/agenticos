"use client";

import { useEffect, useMemo, useState } from "react";
import { BookOpen, FilePlus, Upload } from "lucide-react";
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
import { CategoryInput, categorySuggestions } from "@/components/skills/category-input";
import {
  FileTree,
  FileViewer,
  formatSize,
  NewFileForm,
  UploadButton,
} from "@/components/skills/skill-files";
import { buildTree } from "@/lib/file-tree";
import { readsAsText, resolveFileKind } from "@/lib/file-kinds";
import { cn } from "@/lib/utils";
import { useSkills } from "@/hooks";
import { apiClient } from "@/lib/api-client";
import { submitFailure } from "@/lib/api-error";
import { useTranslations } from "next-intl";

/** What the backend accepts, so an over-long value is refused before it is sent. */
const MAX_NAME = 64;
const MAX_DESCRIPTION = 500;
const MAX_CATEGORY = 64;

/** The body's place in the tree - the same manifest slot the workbench gives it. */
const BODY = "SKILL.md";

/** Beyond this a pending file is shown as a fact, not read into the pane. */
const MAX_PREVIEW_BYTES = 512 * 1024;

type Field = "name" | "description" | "category" | "content";

/** The path a picked file will be stored under - a folder drop keeps its layout. */
function pathOf(file: File): string {
  return file.webkitRelativePath || file.name;
}

/**
 * Whether a pending file can honestly be shown as text.
 *
 * The same question the viewer asks before choosing a request, and now literally the
 * same answer: this used to read `previewKind(path) !== "text"`, which said "a format
 * we recognise" by way of a double negative and needed two more clauses to cover the
 * cases it excluded.
 */
function isReadableText(file: File): boolean {
  if (file.size > MAX_PREVIEW_BYTES) return false;
  return readsAsText(resolveFileKind(pathOf(file), file.type));
}

interface CreateSkillDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * New skill, laid out as the editor it becomes.
 *
 * The same arrangement as `SkillWorkbench`, deliberately: a strip of facts on
 * top, the body as `SKILL.md` in a file tree on the left, one pane reading a
 * file on the right. It used to be a stacked form with a lone "Content"
 * textarea, which meant the second time anybody saw their skill it looked
 * nothing like the first - and the create form was the only place in the
 * product where a skill did not look like a folder.
 *
 * What differs from the workbench is only what cannot exist yet: the name is
 * editable here because it is being chosen, there is no Enabled switch because
 * a skill is created enabled, and the files are local File objects held until
 * the skill exists to attach them to.
 */
export function CreateSkillDialog({ open, onOpenChange }: CreateSkillDialogProps) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("skills");
  const { create, categories, suggestedCategories } = useSkills();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("");
  const [content, setContent] = useState("");
  // Held until the skill exists. A dropped folder is the common way a skill
  // arrives, and making somebody create an empty one first to attach it is the
  // step this avoids.
  const [files, setFiles] = useState<File[]>([]);
  // `null` is the body. Every other value is a pending file's path.
  const [openPath, setOpenPath] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  const setters: Record<Field, (value: string) => void> = {
    name: setName,
    description: setDescription,
    category: setCategory,
    content: setContent,
  };

  function edit(field: Field, value: string) {
    setters[field](value);
    // The refusal was about the value that was sent; it stops being true the
    // moment that value changes.
    if (errors[field]) setErrors(({ [field]: _removed, ...rest }) => rest);
  }

  /** Add files, replacing by path: picking `checklist.md` twice is a re-pick. */
  function addFiles(picked: File[]) {
    if (picked.length === 0) return;
    setFiles((current) => {
      const incoming = new Set(picked.map(pathOf));
      return [...current.filter((file) => !incoming.has(pathOf(file))), ...picked];
    });
  }

  function removeFile(path: string) {
    setFiles((current) => current.filter((file) => pathOf(file) !== path));
    setOpenPath(null);
  }

  const tree = useMemo(
    () =>
      buildTree(
        files.map((file) => ({ id: pathOf(file), name: pathOf(file), size_bytes: file.size })),
      ),
    [files],
  );
  const selected = files.find((file) => pathOf(file) === openPath) ?? null;

  /** The same multipart write the editor's upload makes, once the id exists. */
  async function uploadFiles(skillId: string, picked: File[]) {
    await apiClient.uploadMany(`/skills/${skillId}/resources/upload`, picked, pathOf);
  }

  async function handleCreate() {
    try {
      const skill = await create.mutateAsync({
        name,
        description,
        content,
        // Whitespace-only means "no category" - the backend refuses an empty
        // string but takes null as uncategorized.
        category: category.trim() === "" ? null : category.trim(),
      });
      // Files go up after the skill exists, because a resource hangs off a
      // skill id - there is nothing to attach them to before this point. A
      // failure here leaves the skill created and says so, rather than
      // pretending nothing happened and leaving a half-made one behind.
      if (files.length > 0) {
        await uploadFiles(skill.id, files);
      }
      setName("");
      setDescription("");
      setCategory("");
      setContent("");
      setFiles([]);
      setOpenPath(null);
      setAdding(false);
      setErrors({});
      onOpenChange(false);
    } catch (error) {
      const failure = submitFailure(
        error,
        {
          fields: ["name", "description", "category", "content"],
          identifiedBy: "name",
        },
        tErrors,
      );
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[92vh] flex-col sm:max-w-[92rem]">
        <DialogHeader>
          <DialogTitle>{t("newSkill")}</DialogTitle>
          <DialogDescription>{t("availableEveryAgentOrganization")}</DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-3">
          <div className="flex flex-wrap items-start gap-4 rounded-md border p-3">
            <div className="w-56 shrink-0 space-y-1.5" data-tour="skill-dialog-name">
              <Label htmlFor="new-skill-name">{t("name")}</Label>
              <Input
                id="new-skill-name"
                value={name}
                onChange={(event) => edit("name", event.target.value)}
                placeholder="refund-policy"
                maxLength={MAX_NAME}
                className="font-mono"
                aria-invalid={errors.name ? true : undefined}
              />
              <FieldNote error={errors.name}>{t("howModelRefersSkill")}</FieldNote>
            </div>
            <div
              className="min-w-0 flex-1 basis-72 space-y-1.5"
              data-tour="skill-dialog-description"
            >
              <Label htmlFor="new-skill-description">{t("description")}</Label>
              <Input
                id="new-skill-description"
                value={description}
                onChange={(event) => edit("description", event.target.value)}
                placeholder={t("howRefundsTheirExceptions")}
                maxLength={MAX_DESCRIPTION}
                aria-invalid={errors.description ? true : undefined}
              />
              <FieldNote error={errors.description}>{t("onlyPartModelReads")}</FieldNote>
            </div>
            <div className="w-56 shrink-0 space-y-1.5">
              <Label htmlFor="new-skill-category">{t("category")}</Label>
              <CategoryInput
                id="new-skill-category"
                value={category}
                onChange={(value) => edit("category", value)}
                suggestions={categorySuggestions(categories, suggestedCategories)}
                maxLength={MAX_CATEGORY}
              />
              <FieldNote error={errors.category}>{t("optionalGroupsListingNever")}</FieldNote>
            </div>
          </div>

          <div className="grid min-h-0 flex-1 gap-3 md:grid-cols-[minmax(0,15rem)_minmax(0,1fr)]">
            <div className="flex min-h-0 flex-col gap-2">
              <div className="grid grid-cols-3 gap-1">
                <Button
                  variant="outline"
                  size="sm"
                  className="px-2"
                  onClick={() => {
                    setAdding(true);
                    setOpenPath(null);
                  }}
                >
                  <FilePlus className="h-3.5 w-3.5" />
                  {t("new")}
                </Button>
                <UploadButton icon={Upload} label={t("files")} onPick={addFiles} />
                {/* A directory picker sends every file with its relative path,
                    which is exactly the name a resource takes - so a dropped
                    folder arrives as a folder with nothing to reconstruct. */}
                <UploadButton icon={Upload} label={t("folder")} directory onPick={addFiles} />
              </div>

              <div className="min-h-0 flex-1 overflow-auto rounded-md border p-1">
                <button
                  type="button"
                  onClick={() => {
                    setOpenPath(null);
                    setAdding(false);
                  }}
                  aria-current={openPath === null && !adding}
                  className={cn(
                    "flex w-full items-center gap-1.5 rounded px-2 py-1.5 text-left transition-colors",
                    openPath === null && !adding
                      ? "bg-accent text-foreground"
                      : "hover:bg-accent/60",
                  )}
                >
                  <BookOpen className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
                  <span className="truncate font-mono text-xs">{BODY}</span>
                </button>
                <FileTree
                  nodes={tree}
                  openId={openPath}
                  onOpen={(id) => {
                    setOpenPath(id);
                    setAdding(false);
                  }}
                />
              </div>
            </div>

            <div className="flex min-h-0 flex-col" data-tour="skill-dialog-editor">
              {adding ? (
                <NewFileForm
                  busy={false}
                  onCancel={() => setAdding(false)}
                  onSubmit={(draft) => {
                    // A typed draft becomes a File so it rides the same upload
                    // as a picked one once the skill exists.
                    addFiles([new File([draft.content], draft.name, { type: "text/plain" })]);
                    setAdding(false);
                    setOpenPath(draft.name);
                  }}
                />
              ) : selected ? (
                <PendingFilePane
                  key={pathOf(selected)}
                  file={selected}
                  onRemove={() => removeFile(pathOf(selected))}
                />
              ) : (
                <FileViewer
                  name={BODY}
                  content={content}
                  canEdit
                  onChange={(next) => edit("content", next)}
                  footer={
                    <p
                      className={cn(
                        "text-xs",
                        errors.content ? "text-destructive" : "text-muted-foreground",
                      )}
                    >
                      {errors.content ?? t("markdownYouCanFill")}
                    </p>
                  }
                />
              )}
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              {t("cancel")}
            </Button>
            <Button
              onClick={handleCreate}
              disabled={!name.trim() || !description.trim() || create.isPending}
              data-tour="skill-dialog-create"
            >
              {t("create")}
            </Button>
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** A field's helper line, or the refusal that replaced it. */
function FieldNote({ error, children }: { error?: string; children: React.ReactNode }) {
  if (error) return <p className="text-destructive text-xs">{error}</p>;
  return <p className="text-muted-foreground text-xs">{children}</p>;
}

/**
 * A file that exists only in this dialog, read the way the workbench reads a
 * saved one when it can be read at all. A binary or oversized pick is stated
 * as a fact - name and size - rather than garbled into a text pane.
 */
function PendingFilePane({ file, onRemove }: { file: File; onRemove: () => void }) {
  const t = useTranslations("skills");
  const path = pathOf(file);
  const readable = isReadableText(file);
  const [text, setText] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!readable) return;
    let cancelled = false;
    file
      .text()
      .then((body) => {
        if (!cancelled) setText(body);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [file, readable]);

  const footer = (
    <>
      <p className="text-muted-foreground min-w-0 flex-1 truncate text-xs">
        {t("sizeUploadsWhenCreated", { size: formatSize(file.size) })}
      </p>
      <Button variant="ghost" size="sm" onClick={onRemove}>
        {t("remove")}
      </Button>
    </>
  );

  if (!readable || failed) {
    return (
      <div className="flex min-h-0 flex-1 flex-col rounded-md border">
        <div className="flex items-center gap-2 border-b px-3 py-2">
          <span className="min-w-0 flex-1 truncate font-mono text-xs">{path}</span>
        </div>
        <div className="flex flex-1 items-center justify-center p-6">
          <p className="text-muted-foreground max-w-sm text-center text-xs">
            {t("notShownHereAgent")}
          </p>
        </div>
        <div className="flex items-center gap-2 border-t px-3 py-2">{footer}</div>
      </div>
    );
  }

  return (
    <FileViewer
      name={path}
      content={text ?? ""}
      loading={text === null}
      canEdit={false}
      footer={footer}
    />
  );
}
