"use client";

import { useState } from "react";
import { Upload } from "lucide-react";
import { toast } from "sonner";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Input,
  Textarea,
} from "@/components/ui";
import { useSkills } from "@/hooks";
import { apiClient } from "@/lib/api-client";
import { submitFailure } from "@/lib/api-error";

/** What the backend accepts, so an over-long value is refused before it is sent. */
const MAX_NAME = 64;
const MAX_DESCRIPTION = 500;
const MAX_CATEGORY = 64;

type Field = "name" | "description" | "category" | "content";

interface CreateSkillDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * New skill: a name the model will refer to it by, and what it is for.
 *
 * The name is unique per organization and cannot be changed afterwards, so a
 * collision is both the likeliest refusal and the one that most needs to land
 * on the field rather than in a toast - everything the reader typed into a ten
 * row editor is still worth keeping.
 */
export function CreateSkillDialog({ open, onOpenChange }: CreateSkillDialogProps) {
  const { create } = useSkills();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("");
  const [content, setContent] = useState("");
  // Held until the skill exists. A dropped folder is the common way a skill
  // arrives, and making somebody create an empty one first to attach it is the
  // step this avoids.
  const [files, setFiles] = useState<File[]>([]);
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

  /** The same multipart write the editor's upload makes, once the id exists. */
  async function uploadFiles(skillId: string, picked: File[]) {
    await apiClient.uploadMany(
      `/skills/${skillId}/resources/upload`,
      picked,
      (file) => file.webkitRelativePath || file.name,
    );
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
      setErrors({});
      onOpenChange(false);
    } catch (error) {
      const failure = submitFailure(error, {
        fields: ["name", "description", "category", "content"],
        identifiedBy: "name",
      });
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>New skill</DialogTitle>
          <DialogDescription>
            It is available to every agent in this organization the moment you create it.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <FormField
            label="Name"
            htmlFor="new-skill-name"
            error={errors.name}
            description="How the model refers to this skill. Unique in this organization, and it cannot be changed later."
          >
            <Input
              value={name}
              onChange={(event) => edit("name", event.target.value)}
              placeholder="refund-policy"
              maxLength={MAX_NAME}
              className="font-mono"
            />
          </FormField>
          <FormField
            label="Description"
            htmlFor="new-skill-description"
            error={errors.description}
            description="The only part the model reads before deciding whether to open the skill. Write when it applies, not what is inside it."
          >
            <Textarea
              value={description}
              onChange={(event) => edit("description", event.target.value)}
              placeholder="How refunds and their exceptions are handled."
              maxLength={MAX_DESCRIPTION}
              rows={2}
            />
          </FormField>
          <FormField
            label="Category"
            htmlFor="new-skill-category"
            error={errors.category}
            description="Optional. A shelf for the listing to group and filter by - it never reaches the model."
          >
            <Input
              value={category}
              onChange={(event) => edit("category", event.target.value)}
              placeholder="support"
              maxLength={MAX_CATEGORY}
            />
          </FormField>
          <FormField
            label="Content"
            htmlFor="new-skill-content"
            error={errors.content}
            description="Markdown. You can fill this in later."
          >
            <Textarea
              value={content}
              onChange={(event) => edit("content", event.target.value)}
              placeholder="## When a customer asks for a refund…"
              rows={10}
              className="font-mono text-xs"
            />
          </FormField>

          <div className="space-y-1.5">
            <p className="text-sm font-medium">Files</p>
            <p className="text-muted-foreground text-xs">
              Optional. Drop the folder a skill came in - `references/`, `scripts/` and the rest
              keep their paths, and the agent loads one only when it decides it needs it.
            </p>
            <div className="flex flex-wrap items-center gap-1.5">
              <FilePicker
                label="Add files"
                onPick={(picked) => setFiles((f) => [...f, ...picked])}
              />
              <FilePicker
                label="Add folder"
                directory
                onPick={(picked) => setFiles((f) => [...f, ...picked])}
              />
              {files.length > 0 && (
                <button
                  type="button"
                  onClick={() => setFiles([])}
                  className="text-muted-foreground hover:text-foreground text-xs underline-offset-2 hover:underline"
                >
                  Clear {files.length}
                </button>
              )}
            </div>
            {files.length > 0 && (
              <ul className="max-h-32 overflow-auto rounded-md border p-2">
                {files.map((file) => (
                  <li
                    key={file.webkitRelativePath || file.name}
                    className="text-muted-foreground truncate font-mono text-xs"
                  >
                    {file.webkitRelativePath || file.name}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleCreate}
            disabled={!name.trim() || !description.trim() || create.isPending}
          >
            Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function FilePicker({
  label,
  directory,
  onPick,
}: {
  label: string;
  directory?: boolean;
  onPick: (files: File[]) => void;
}) {
  return (
    <label className="border-input hover:bg-accent inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-md border px-3 text-sm transition-colors">
      <Upload className="h-4 w-4" />
      {label}
      <input
        type="file"
        multiple
        // Not in React's JSX types - a real attribute every browser that matters
        // implements, and the only way to pick a folder.
        {...(directory ? ({ webkitdirectory: "" } as Record<string, string>) : {})}
        className="hidden"
        onChange={(event) => {
          onPick(Array.from(event.target.files ?? []));
          event.target.value = "";
        }}
      />
    </label>
  );
}
