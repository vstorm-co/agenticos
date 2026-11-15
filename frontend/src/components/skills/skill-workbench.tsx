"use client";

import { useId, useMemo, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  ExternalLink,
  ChevronDown,
  FolderOpen,
  FilePlus,
  Upload,
} from "lucide-react";

import { Alert, AlertDescription, Button, DialogFooter, Input, Label } from "@/components/ui";
import { FileEditor } from "@/components/files";
import { ResourceActions } from "@/components/sharing/resource-actions";
import { ShareResourceButton } from "@/components/sharing/share-resource-button";
import { FilePane, FileTree, NewFileForm, UploadButton } from "@/components/skills/skill-files";
import { CategoryInput } from "@/components/skills/category-input";
import { buildTree } from "@/lib/file-tree";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";
import { cn } from "@/lib/utils";
import { useSkill } from "@/hooks";
import type { SkillEdit } from "@/hooks/use-skills";
import type { Skill } from "@/types/providers";
import { useTranslations } from "next-intl";

/** The body's place in the tree. A skill is a folder, and this is its manifest. */
const BODY = "SKILL.md";

interface SkillWorkbenchProps {
  skill: Skill;
  /** Without it the body is still readable - the write controls are the part that goes. */
  canEdit: boolean;
  isSaving: boolean;
  /** What the category field suggests: shelves in use plus the deployment's predefined ones. */
  categorySuggestions?: string[];
  /** What saving does to the agents using the line being edited. */
  saveWarning: string;
  /**
   * Editing a fork: only its description and body are its own, so the files and the
   * category - shared with main - stay read-only.
   */
  fork?: boolean;
  onSave: (edit: SkillEdit) => Promise<boolean | void>;
  /** A file was written: each such write is a new version the next save builds on. */
  onFilesWritten: () => void;
  onCancel: () => void;
  onDelete?: () => void;
  onOpenFull?: () => void;
}

/**
 * A skill, edited as the folder it is.
 *
 * One editor rather than two stacked forms. The body and the files were
 * separate panels with a footer between them, which put Save halfway down the
 * dialog and left the files looking like an afterthought bolted below it -
 * they are not, they are the same skill.
 *
 * So the body sits at the top of the tree as Instructions - the name History and
 * the diff give it too - and it gets the same pane every other file gets:
 * Markdown with a preview, because `SKILL.md` is what it is on disk. Everything
 * below it is a file. One footer, at the bottom, saving the skill.
 *
 * The body's own state is seeded once, so mount this keyed by skill id: the
 * unsaved diff is what decides whether to warn about the blast radius, and
 * reseeding it mid-edit would discard somebody's typing.
 */
export function SkillWorkbench({
  skill,
  canEdit,
  isSaving,
  categorySuggestions = [],
  saveWarning,
  fork = false,
  onSave,
  onFilesWritten,
  onCancel,
  onDelete,
  onOpenFull,
}: SkillWorkbenchProps) {
  const t = useTranslations("skills");
  const { addResource, saveResource, removeResource, uploadResources } = useSkill(skill.id);

  const [description, setDescription] = useState(skill.description);
  const [content, setContent] = useState(skill.content);
  // Held as text while it is edited; whitespace-only means "no category", so
  // clearing the field is how a skill leaves its shelf.
  const [category, setCategory] = useState(skill.category ?? "");
  // `null` is the body. Every other value is a resource id.
  const [openId, setOpenId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [metadataOpen, setMetadataOpen] = useState(false);
  const metadataId = useId();
  const filesId = useId();
  const [filesOpen, setFilesOpen] = useState(false);

  const files = useMemo(() => skill.resources ?? [], [skill.resources]);
  const tree = useMemo(() => buildTree(files), [files]);
  const selected = files.find((file) => file.id === openId) ?? null;

  const editedCategory = category.trim() === "" ? null : category.trim();
  const changed =
    description !== skill.description ||
    content !== skill.content ||
    editedCategory !== skill.category;

  const save = async (): Promise<boolean> => {
    try {
      return (await onSave({ description, content, category: editedCategory })) !== false;
    } catch {
      // The mutation owns error feedback; keep the unsaved fields available.
      return false;
    }
  };
  useUnsavedChanges(`skill-editor:${skill.id}`, {
    dirty: canEdit && changed,
    save: description.trim() ? save : undefined,
    discard: () => {
      setDescription(skill.description);
      setContent(skill.content);
      setCategory(skill.category ?? "");
    },
  });
  const leaveResource = (proceed: () => void) => {
    useUnsavedChangesStore
      .getState()
      .leave(proceed, openId === null ? [] : [`skill-resource:${skill.id}:${openId}`]);
  };

  const upload = async (picked: File[]) => {
    if (picked.length === 0) return;
    await uploadResources.mutateAsync(picked).then(onFilesWritten, () => null);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="flex shrink-0 items-center gap-2 md:hidden">
        <button
          type="button"
          className="touch:min-h-11 flex h-8 min-w-0 items-center gap-2 rounded-lg border px-3 text-left text-xs"
          aria-expanded={metadataOpen}
          aria-controls={metadataId}
          onClick={() => {
            setMetadataOpen(!metadataOpen);
            setFilesOpen(false);
          }}
        >
          <span className="shrink-0 font-medium">{t("description3")}</span>{" "}
          <span className="sr-only">{description}</span>
          <ChevronDown
            className={cn("size-4 shrink-0", metadataOpen && "rotate-180")}
            aria-hidden
          />
        </button>
        <Button
          variant="outline"
          size="sm"
          aria-expanded={filesOpen}
          aria-controls={filesId}
          onClick={() => {
            setFilesOpen(!filesOpen);
            setMetadataOpen(false);
          }}
        >
          <FolderOpen aria-hidden />
          {t("files3")}
        </Button>
      </div>
      <div
        id={metadataId}
        className={cn(
          "flex shrink-0 flex-wrap items-start gap-4 rounded-md border p-3 max-md:max-h-[35dvh] max-md:overflow-y-auto",
          !metadataOpen && "max-md:hidden",
        )}
      >
        <div className="min-w-0 flex-1 basis-72 space-y-1.5">
          <Label htmlFor="skill-description">{t("description3")}</Label>
          <Input
            id="skill-description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            readOnly={!canEdit}
          />
          <p className="text-muted-foreground text-xs">{t("onlyPartModelReads2")}</p>
          <p className="text-muted-foreground text-xs">{t("markdownLoadedOnlyAfter")}</p>
        </div>
        <div className="w-full shrink-0 space-y-1.5 md:w-56">
          <Label htmlFor="skill-category">{t("category2")}</Label>
          <CategoryInput
            id="skill-category"
            value={category}
            onChange={setCategory}
            suggestions={categorySuggestions}
            maxLength={64}
            readOnly={!canEdit || fork}
          />
          <p className="text-muted-foreground text-xs">{t("groupsListingNeverReaches")}</p>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-3 md:grid md:grid-cols-[minmax(0,15rem)_minmax(0,1fr)] md:grid-rows-1">
        <div
          id={filesId}
          className={cn(
            "flex min-h-0 shrink-0 flex-col gap-2 max-md:max-h-[30dvh] md:shrink",
            !filesOpen && "max-md:hidden",
          )}
        >
          {canEdit && !fork && (
            // One row of three, above the tree: stacked below it they wrapped
            // onto two lines and read as an afterthought under a tall empty box.
            <div className="grid grid-cols-3 gap-1">
              <Button
                variant="outline"
                size="sm"
                className="px-2"
                onClick={() =>
                  leaveResource(() => {
                    setAdding(true);
                    setOpenId(null);
                    setFilesOpen(false);
                  })
                }
              >
                <FilePlus className="h-3.5 w-3.5" />
                {t("new2")}
              </Button>
              <UploadButton icon={Upload} label={t("files3")} onPick={upload} />
              {/* A directory picker sends every file with its relative path,
                  which is exactly the name a resource takes - so a dropped
                  folder arrives as a folder with nothing to reconstruct. */}
              <UploadButton icon={Upload} label={t("folder2")} directory onPick={upload} />
            </div>
          )}

          <div className="bg-background min-h-0 flex-1 overflow-auto rounded-xl border p-1 max-md:max-h-36">
            <button
              type="button"
              onClick={() =>
                leaveResource(() => {
                  setOpenId(null);
                  setAdding(false);
                  setFilesOpen(false);
                })
              }
              aria-current={openId === null && !adding}
              className={cn(
                "flex w-full items-center gap-1.5 rounded px-2 py-1.5 text-left transition-colors",
                openId === null && !adding ? "bg-accent text-foreground" : "hover:bg-accent/60",
              )}
            >
              <BookOpen className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
              <span className="truncate text-xs">{t("instructions")}</span>
            </button>
            <FileTree
              nodes={tree}
              openId={openId}
              onOpen={(id) => {
                if (id === openId) return;
                leaveResource(() => {
                  setOpenId(id);
                  setAdding(false);
                  setFilesOpen(false);
                });
              }}
            />
          </div>
        </div>

        {/* The reader takes the remaining height; saving stays within reach below it. */}
        <div className="flex min-h-0 flex-1 flex-col">
          {adding ? (
            <NewFileForm
              busy={addResource.isPending}
              onCancel={() => setAdding(false)}
              onSubmit={async (draft) => {
                await addResource.mutateAsync(draft);
                onFilesWritten();
                setAdding(false);
                setFilesOpen(false);
              }}
            />
          ) : selected ? (
            <FilePane
              key={selected.id}
              skillId={skill.id}
              resource={selected}
              canEdit={canEdit && !fork}
              busy={saveResource.isPending}
              onSave={async (body) => {
                await saveResource.mutateAsync({ id: selected.id, content: body });
                onFilesWritten();
              }}
              onDelete={async () => {
                try {
                  await removeResource.mutateAsync(selected.id);
                  onFilesWritten();
                  setOpenId(null);
                } catch {
                  // The mutation reports the refusal; leave the open file and draft intact.
                }
              }}
            />
          ) : (
            <FileEditor
              name={BODY}
              label={t("instructions")}
              content={content}
              canEdit={canEdit}
              onChange={setContent}
            />
          )}
        </div>
      </div>

      {changed && (
        <Alert variant="warning">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{saveWarning}</AlertDescription>
        </Alert>
      )}

      <DialogFooter className="shrink-0 flex-row items-center max-md:pt-2">
        <div className="mr-auto flex items-center gap-2">
          <ShareResourceButton
            compact
            resourceType="skill"
            resourceId={skill.id}
            name={skill.name}
            canManage={canEdit}
          />
          {onOpenFull && (
            <Button
              variant="outline"
              aria-label={t("page.openFullView")}
              className="max-md:size-11 max-md:p-0"
              disabled={isSaving}
              onClick={onOpenFull}
            >
              <ExternalLink className="size-4" aria-hidden />
              <span className="max-md:sr-only">{t("page.openFullView")}</span>
            </Button>
          )}
          {canEdit && onDelete && (
            <ResourceActions
              name={skill.name}
              onDelete={onDelete}
              disabled={
                isSaving ||
                addResource.isPending ||
                saveResource.isPending ||
                removeResource.isPending ||
                uploadResources.isPending
              }
            />
          )}
        </div>
        <Button variant="outline" onClick={onCancel}>
          {canEdit ? t("cancel2") : t("close")}
        </Button>
        {canEdit && (
          <Button
            onClick={() => leaveResource(() => void save())}
            loading={isSaving}
            disabled={!changed || !description.trim()}
          >
            {t("save")}
          </Button>
        )}
      </DialogFooter>
    </div>
  );
}
