"use client";

import { useMemo, useRef, useState } from "react";
import { FolderPlus, FolderUp, MoreHorizontal, Upload } from "lucide-react";
import { useTranslations } from "next-intl";

import { ProjectFileEditor } from "./project-file-editor";
import { FileDropZone } from "@/components/rag/file-drop-zone";
import { UploadProgressList } from "@/components/rag/upload-progress-list";
import { FileExplorer } from "@/components/sandboxes/workspace-explorer";
import {
  Button,
  ConfirmDialog,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  FormField,
  Input,
} from "@/components/ui";
import { useProjectFiles } from "@/hooks/use-projects";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";
import type { FileSource } from "@/lib/workspace-files";
import type { Project } from "@/types/projects";
import { useShell } from "@/hooks/use-shell";
import { isDesktopShell } from "@/lib/desktop/shell";
import { useProjectFolder } from "@/hooks/use-project-folder";
import { ProjectFolderChoice } from "./project-folder-choice";
import { ProjectFolderExplorer } from "./project-folder-explorer";

/**
 * The project's container, browsable - and, for whoever may work in it, the
 * place to put files and folders every agent in the project then finds.
 */
export function ProjectFiles({ project }: { project: Project }) {
  const shell = useShell();
  const local = useProjectFolder(project.id);
  if (!project.can_use || !isDesktopShell(shell) || !local.available) {
    return <SharedProjectFiles project={project} />;
  }
  return <DesktopProjectFiles key={project.id} project={project} />;
}

function DesktopProjectFiles({ project }: { project: Project }) {
  const t = useTranslations("projects.localFolder");
  const local = useProjectFolder(project.id);
  const [view, setView] = useState<"local" | "shared">("local");
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-4">
      <ProjectFolderChoice
        value={local.target}
        onChange={(target) => {
          local.bind(project.id, target);
          setView(target ? "local" : "shared");
        }}
      />
      {local.target && (
        <div className="flex flex-wrap gap-2" role="group" aria-label={t("fileLocation")}>
          <Button
            variant={view === "local" ? "secondary" : "ghost"}
            aria-pressed={view === "local"}
            onClick={() => setView("local")}
          >
            {t("localFiles")}
          </Button>
          <Button
            variant={view === "shared" ? "secondary" : "ghost"}
            aria-pressed={view === "shared"}
            onClick={() => setView("shared")}
          >
            {t("sharedFiles")}
          </Button>
        </div>
      )}
      {local.target && view === "local" ? (
        <ProjectFolderExplorer root={local.target.folder} />
      ) : (
        <SharedProjectFiles project={project} />
      )}
    </div>
  );
}

function SharedProjectFiles({ project }: { project: Project }) {
  const t = useTranslations("projects");
  const tc = useTranslations("common");
  const { files, isLoading, error, upload, uploads, addFolder, move, remove } = useProjectFiles(
    project.id,
  );
  const source = useMemo<FileSource>(() => ({ kind: "project", id: project.id }), [project.id]);
  const filesInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const [folderOpen, setFolderOpen] = useState(false);
  const [folderName, setFolderName] = useState("");
  const [pendingRemove, setPendingRemove] = useState<string | null>(null);

  function picked(list: FileList | null) {
    const chosen = Array.from(list ?? []);
    if (chosen.length > 0) upload.mutate({ files: chosen, folder: "" });
  }

  const writable =
    project.can_use && !["queued", "running"].includes(project.workspace_move?.status ?? "");
  const toolbar = writable ? (
    <span className="mr-auto flex flex-wrap items-center gap-1.5" data-tour="project-files-add">
      <Button size="sm" onClick={() => filesInput.current?.click()} disabled={upload.isPending}>
        <Upload className="h-4 w-4" />
        {t("uploadFiles")}
      </Button>
      <Button
        size="sm"
        variant="outline"
        className="hidden sm:inline-flex"
        onClick={() => folderInput.current?.click()}
        disabled={upload.isPending}
      >
        <FolderUp className="h-4 w-4" />
        {t("uploadFolder")}
      </Button>
      <Button
        size="sm"
        variant="outline"
        className="hidden sm:inline-flex"
        onClick={() => setFolderOpen(true)}
      >
        <FolderPlus className="h-4 w-4" />
        {t("newFolder")}
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="sm" variant="outline" className="sm:hidden" aria-label={tc("showMore")}>
            <MoreHorizontal className="h-4 w-4" />
            {tc("showMore")}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem
            disabled={upload.isPending}
            onSelect={() => folderInput.current?.click()}
          >
            <FolderUp className="h-4 w-4" />
            {t("uploadFolder")}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setFolderOpen(true)}>
            <FolderPlus className="h-4 w-4" />
            {t("newFolder")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <input
        ref={filesInput}
        type="file"
        multiple
        hidden
        aria-label={t("uploadFiles")}
        onChange={(event) => {
          picked(event.target.files);
          event.target.value = "";
        }}
      />
      <input
        ref={folderInput}
        type="file"
        hidden
        aria-label={t("uploadFolder")}
        // A folder picker: each file carries its path inside the folder.
        {...{ webkitdirectory: "", directory: "" }}
        onChange={(event) => {
          picked(event.target.files);
          event.target.value = "";
        }}
      />
    </span>
  ) : undefined;

  // A project with nothing in it is a place to put the first files, not two
  // empty panes - a folder tree saying it is empty beside a viewer with nothing
  // to show.
  const empty = files !== null && files.total === 0 && uploads.length === 0;

  const explorer = empty ? (
    <div className="border-border flex min-h-0 flex-1 flex-col items-center justify-center gap-4 rounded-xl border-2 border-dashed px-6 py-12 text-center">
      <span className="bg-muted text-foreground grid h-14 w-14 place-items-center rounded-xl">
        <Upload className="h-6 w-6" aria-hidden />
      </span>
      <div className="max-w-md space-y-1">
        <p className="text-foreground text-base font-semibold">{t("noFilesYet")}</p>
        <p className="text-muted-foreground text-sm">
          {writable ? (
            <>
              <span className="sm:hidden">{t("noFilesMobileHint")}</span>
              <span className="hidden sm:inline">{t("noFilesHint")}</span>
            </>
          ) : (
            t("noFilesViewer")
          )}
        </p>
      </div>
      {toolbar && (
        <div className="flex w-full max-w-sm justify-center sm:w-auto sm:max-w-none [&>span]:mr-0">
          {toolbar}
        </div>
      )}
    </div>
  ) : (
    <div className="flex min-h-0 flex-1 flex-col">
      <UploadProgressList uploads={uploads} />
      <FileExplorer
        source={source}
        files={files}
        isLoading={isLoading}
        error={error}
        toolbar={toolbar}
        onRemove={writable ? setPendingRemove : undefined}
        onMove={
          writable
            ? async (source, destination) => {
                await move.mutateAsync({ source, destination });
              }
            : undefined
        }
        renderEditor={
          writable ? (path) => <ProjectFileEditor projectId={project.id} path={path} /> : undefined
        }
      />
    </div>
  );

  return (
    // Down to the bottom of the screen, as the folder page's reader is: the files
    // are what the tab is for, and a fixed floor left half the screen empty.
    <div className="flex min-h-0 flex-1 flex-col">
      {project.can_use && !writable && (
        <p
          role="status"
          className="text-muted-foreground bg-muted/50 mb-3 rounded-xl px-4 py-3 text-sm"
        >
          {t("sandbox.paused")}
        </p>
      )}
      {/* A file dropped anywhere on the tab lands in the project, as one dropped
          on a knowledge base lands in it - for whoever may add files. */}
      {writable ? (
        <FileDropZone
          collectionName={project.name}
          onFiles={picked}
          className="flex min-h-0 flex-1 flex-col"
        >
          {explorer}
        </FileDropZone>
      ) : (
        explorer
      )}

      <Dialog open={folderOpen} onOpenChange={setFolderOpen}>
        <DialogContent className={DIALOG_CONFIRM}>
          <DialogHeader>
            <DialogTitle>{t("newFolder")}</DialogTitle>
          </DialogHeader>
          <FormField label={t("folderName")} htmlFor="project-folder-name">
            <Input
              id="project-folder-name"
              value={folderName}
              onChange={(event) => setFolderName(event.target.value)}
              placeholder={t("folderPlaceholder")}
            />
          </FormField>
          <DialogFooter>
            <Button variant="outline" onClick={() => setFolderOpen(false)}>
              {t("cancel")}
            </Button>
            <Button
              disabled={!folderName.trim() || addFolder.isPending}
              onClick={async () => {
                await addFolder.mutateAsync(folderName.trim());
                setFolderName("");
                setFolderOpen(false);
              }}
            >
              {t("create")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {pendingRemove !== null && (
        <ConfirmDialog
          open
          onOpenChange={(open) => !open && setPendingRemove(null)}
          title={t("removeTitle", { path: pendingRemove })}
          description={t("removeBody")}
          confirmLabel={t("remove")}
          destructive
          loading={remove.isPending}
          onConfirm={async () => {
            await remove.mutateAsync(pendingRemove);
            setPendingRemove(null);
          }}
        />
      )}
    </div>
  );
}
