"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, BookOpen, FilePlus, Upload } from "lucide-react";

import {
  Alert,
  AlertDescription,
  Button,
  DialogFooter,
  Input,
  Label,
  Switch,
} from "@/components/ui";
import {
  FilePane,
  FileTree,
  FileViewer,
  NewFileForm,
  UploadButton,
} from "@/components/skills/skill-files";
import { buildTree } from "@/lib/file-tree";
import { cn } from "@/lib/utils";
import { useSkill } from "@/hooks";
import type { SkillEdit } from "@/hooks/use-skills";
import type { Skill } from "@/types/providers";

/** The body's place in the tree. A skill is a folder, and this is its manifest. */
const BODY = "SKILL.md";

interface SkillWorkbenchProps {
  skill: Skill;
  /** Without it the body is still readable — the write controls are the part that goes. */
  canEdit: boolean;
  isSaving: boolean;
  onSave: (edit: SkillEdit) => void;
  onCancel: () => void;
}

/**
 * A skill, edited as the folder it is.
 *
 * One editor rather than two stacked forms. The body and the files were
 * separate panels with a footer between them, which put Save halfway down the
 * dialog and left the files looking like an afterthought bolted below it —
 * they are not, they are the same skill.
 *
 * So the body sits in the tree as `SKILL.md`, where a reader who has seen a
 * skill on disk expects it, and it gets the same pane every other file gets:
 * Markdown with a preview, because that is what it is. Everything below it is a
 * file. One footer, at the bottom, saving the skill.
 *
 * The body's own state is seeded once, so mount this keyed by skill id: the
 * unsaved diff is what decides whether to warn about the blast radius, and
 * reseeding it mid-edit would discard somebody's typing.
 */
export function SkillWorkbench({
  skill,
  canEdit,
  isSaving,
  onSave,
  onCancel,
}: SkillWorkbenchProps) {
  const { addResource, saveResource, removeResource, uploadResources } = useSkill(skill.id);

  const [description, setDescription] = useState(skill.description);
  const [content, setContent] = useState(skill.content);
  const [enabled, setEnabled] = useState(skill.enabled);
  // `null` is the body. Every other value is a resource id.
  const [openId, setOpenId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const files = useMemo(() => skill.resources ?? [], [skill.resources]);
  const tree = useMemo(() => buildTree(files), [files]);
  const selected = files.find((file) => file.id === openId) ?? null;

  const changed =
    description !== skill.description || content !== skill.content || enabled !== skill.enabled;

  const upload = async (list: FileList | null) => {
    if (!list || list.length === 0) return;
    await uploadResources.mutateAsync(Array.from(list)).catch(() => null);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      {/* Above the split rather than inside the body pane: the description and
          the switch are facts about the skill, not about the file being read,
          and they have to stay reachable while somebody is in `checklist.md`. */}
      <div className="flex flex-wrap items-end gap-4 rounded-md border p-3">
        <div className="min-w-0 flex-1 space-y-1.5">
          <Label htmlFor="skill-description">Description</Label>
          <Input
            id="skill-description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            readOnly={!canEdit}
          />
          <p className="text-muted-foreground text-xs">
            The only part the model reads before deciding whether to open the skill at all. Write
            when it applies, not what is inside it.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2 pb-6">
          <Label htmlFor="skill-enabled">Enabled</Label>
          <Switch
            id="skill-enabled"
            checked={enabled}
            onCheckedChange={setEnabled}
            disabled={!canEdit}
          />
        </div>
      </div>

      <div className="grid min-h-0 flex-1 gap-3 md:grid-cols-[minmax(0,15rem)_minmax(0,1fr)]">
        <div className="flex min-h-0 flex-col gap-2">
          {canEdit && (
            // One row of three, above the tree: stacked below it they wrapped
            // onto two lines and read as an afterthought under a tall empty box.
            <div className="grid grid-cols-3 gap-1">
              <Button
                variant="outline"
                size="sm"
                className="px-2"
                onClick={() => {
                  setAdding(true);
                  setOpenId(null);
                }}
              >
                <FilePlus className="h-3.5 w-3.5" />
                New
              </Button>
              <UploadButton icon={Upload} label="Files" onPick={upload} />
              {/* A directory picker sends every file with its relative path,
                  which is exactly the name a resource takes — so a dropped
                  folder arrives as a folder with nothing to reconstruct. */}
              <UploadButton icon={Upload} label="Folder" directory onPick={upload} />
            </div>
          )}

          <div className="min-h-0 flex-1 overflow-auto rounded-md border p-1">
            <button
              type="button"
              onClick={() => {
                setOpenId(null);
                setAdding(false);
              }}
              aria-current={openId === null && !adding}
              className={cn(
                "flex w-full items-center gap-1.5 rounded px-2 py-1.5 text-left transition-colors",
                openId === null && !adding ? "bg-accent text-foreground" : "hover:bg-accent/60",
              )}
            >
              <BookOpen className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
              <span className="truncate font-mono text-xs">{BODY}</span>
            </button>
            <FileTree
              nodes={tree}
              openId={openId}
              onOpen={(id) => {
                setOpenId(id);
                setAdding(false);
              }}
            />
          </div>
        </div>

        <div className="flex min-h-0 flex-col">
          {adding ? (
            <NewFileForm
              busy={addResource.isPending}
              onCancel={() => setAdding(false)}
              onSubmit={async (draft) => {
                await addResource.mutateAsync(draft);
                setAdding(false);
              }}
            />
          ) : selected ? (
            <FilePane
              key={selected.id}
              skillId={skill.id}
              resource={selected}
              canEdit={canEdit}
              busy={saveResource.isPending}
              onSave={(body) => saveResource.mutate({ id: selected.id, content: body })}
              onDelete={async () => {
                await removeResource.mutateAsync(selected.id).catch(() => null);
                setOpenId(null);
              }}
            />
          ) : (
            <FileViewer
              name={BODY}
              content={content}
              canEdit={canEdit}
              onChange={setContent}
              footer={
                <p className="text-muted-foreground text-xs">
                  Markdown. Loaded only after the description convinced the model to, so length
                  costs nothing until it is needed.
                </p>
              }
            />
          )}
        </div>
      </div>

      {changed && (
        <Alert variant="warning">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>
            Saving reaches every agent bound to this skill on its next run. There is no draft and no
            publish step.
          </AlertDescription>
        </Alert>
      )}

      <DialogFooter>
        <Button variant="outline" onClick={onCancel}>
          {canEdit ? "Cancel" : "Close"}
        </Button>
        {canEdit && (
          <Button
            onClick={() => onSave({ description, content, enabled })}
            disabled={!changed || !description.trim() || isSaving}
          >
            Save
          </Button>
        )}
      </DialogFooter>
    </div>
  );
}
