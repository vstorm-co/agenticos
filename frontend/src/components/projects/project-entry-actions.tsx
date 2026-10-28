"use client";

import { useState } from "react";
import { FolderInput, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  FormField,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";

export const PROJECT_PATH_DRAG = "application/x-agenticos-project-path";

export function ProjectEntryActions({
  path,
  folders,
  onMove,
  onRemove,
}: {
  path: string;
  folders: string[];
  onMove: (source: string, destination: string) => Promise<void>;
  onRemove?: (path: string) => void;
}) {
  const t = useTranslations("projects.fileManager");
  const segments = path.split("/").filter(Boolean);
  const normalized = segments.join("/");
  const name = segments.at(-1) ?? path;
  const parent = segments.slice(0, -1).join("/");
  const [mode, setMode] = useState<"rename" | "move" | null>(null);
  const [value, setValue] = useState("");
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);
  const invalid =
    mode === "rename" &&
    (!value.trim() || /[\/\\\x00-\x1f]/.test(value) || value === "." || value === "..");
  const destination =
    mode === "rename"
      ? [parent, value.trim()].filter(Boolean).join("/")
      : [value === "/" ? "" : value, name].filter(Boolean).join("/");
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            aria-label={t("actions", { name })}
            className="text-muted-foreground hover:text-foreground rounded-md p-1.5"
          >
            <MoreHorizontal className="h-4 w-4" aria-hidden />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem
            onSelect={() => {
              setMode("rename");
              setValue(name);
              setFailed(false);
            }}
          >
            <Pencil className="h-4 w-4" />
            {t("rename")}
          </DropdownMenuItem>
          <DropdownMenuItem
            onSelect={() => {
              setMode("move");
              setValue(parent || "/");
              setFailed(false);
            }}
          >
            <FolderInput className="h-4 w-4" />
            {t("move")}
          </DropdownMenuItem>
          {onRemove && (
            <DropdownMenuItem className="text-destructive" onSelect={() => onRemove(path)}>
              <Trash2 className="h-4 w-4" />
              {t("delete")}
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <Dialog
        open={mode !== null}
        onOpenChange={(open) => {
          if (!open && !pending) setMode(null);
        }}
      >
        <DialogContent className={DIALOG_CONFIRM}>
          <DialogHeader>
            <DialogTitle>{mode === "rename" ? t("rename") : t("move")}</DialogTitle>
            <DialogDescription className="break-all">{path}</DialogDescription>
          </DialogHeader>
          <FormField
            label={mode === "rename" ? t("name") : t("destination")}
            htmlFor={`entry-${normalized}`}
          >
            {mode === "rename" ? (
              <Input
                id={`entry-${normalized}`}
                value={value}
                maxLength={255}
                onChange={(event) => setValue(event.target.value)}
              />
            ) : (
              <Select value={value} onValueChange={setValue}>
                <SelectTrigger id={`entry-${normalized}`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="/">{t("root")}</SelectItem>
                  {folders
                    .filter(
                      (folder) => folder !== normalized && !folder.startsWith(normalized + "/"),
                    )
                    .map((folder) => (
                      <SelectItem key={folder} value={folder}>
                        {folder}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            )}
          </FormField>
          {failed && (
            <p role="alert" className="text-destructive text-sm">
              {t("moveFailed")}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" disabled={pending} onClick={() => setMode(null)}>
              {t("cancel")}
            </Button>
            <Button
              disabled={pending || invalid || destination === normalized}
              onClick={async () => {
                setPending(true);
                setFailed(false);
                try {
                  await onMove(path, destination);
                  setMode(null);
                } catch {
                  setFailed(true);
                } finally {
                  setPending(false);
                }
              }}
            >
              {pending ? t("saving") : t("confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
