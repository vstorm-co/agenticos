"use client";

import { useTranslations } from "next-intl";
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
} from "@/components/ui";
import { usePublishVisual } from "@/hooks/use-publish-visual";
import { submitFailure } from "@/lib/api-error";
import { useRouter } from "@/lib/locale-navigation";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";
import { appName } from "@/lib/visuals";
import { rememberSavedVisual } from "@/stores/visual-stream-store";

interface VisualSaveDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  conversationId: string;
  visualId: string;
  title: string;
  /** The app an earlier version of this visual was saved as, which this updates. */
  updates: string | null;
}

/**
 * Save a visual as an app: its title and its name, both filled in.
 *
 * Enter is enough - the dialog exists so the name can be changed, not to make
 * somebody type one. Saved under a name the person already has, it becomes the
 * next version of that app, which is how a revision updates the page it was
 * shared as.
 */
export function VisualSaveDialog({
  open,
  onOpenChange,
  conversationId,
  visualId,
  title: initialTitle,
  updates,
}: VisualSaveDialogProps) {
  const t = useTranslations("chat.visuals");
  const tErrors = useTranslations("errors");
  const publish = usePublishVisual();
  const router = useRouter();
  const [title, setTitle] = useState(initialTitle);
  const [name, setName] = useState(updates ?? appName(initialTitle));
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  async function save() {
    try {
      const app = await publish.mutateAsync({
        conversationId,
        visualId,
        data: { name: name.trim(), title: title.trim() || undefined },
      });
      rememberSavedVisual(visualId, {
        artifactId: app.artifact_id,
        name: app.name,
        version: app.version,
        url: app.url,
      });
      toast.success(
        app.unchanged ? t("savedUnchanged") : t("savedToast", { version: app.version }),
        { action: { label: t("openApp"), onClick: () => router.push(app.url) } },
      );
      onOpenChange(false);
    } catch (error) {
      const failure = submitFailure(
        error,
        { fields: ["name", "title"], identifiedBy: "name" },
        tErrors,
      );
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={DIALOG_CONFIRM}>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
          className="flex flex-col gap-4"
        >
          <DialogHeader>
            <DialogTitle>{updates ? t("updateApp") : t("saveToApps")}</DialogTitle>
            <DialogDescription>{t("saveDescription")}</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="visual-app-title">{t("saveTitleLabel")}</Label>
            <Input
              id="visual-app-title"
              value={title}
              maxLength={200}
              onChange={(event) => setTitle(event.target.value)}
              aria-invalid={Boolean(errors.title)}
            />
            {errors.title && <p className="text-destructive text-xs">{errors.title}</p>}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="visual-app-name">{t("saveName")}</Label>
            <Input
              id="visual-app-name"
              value={name}
              maxLength={64}
              autoFocus
              onChange={(event) => {
                setName(event.target.value);
                setErrors(({ name: _removed, ...rest }) => rest);
              }}
              aria-invalid={Boolean(errors.name)}
              className="font-mono"
            />
            {errors.name ? (
              <p className="text-destructive text-xs">{errors.name}</p>
            ) : (
              <p className="text-muted-foreground text-xs">{t("saveNameHint")}</p>
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={publish.isPending || name.trim() === ""}>
              {publish.isPending ? t("saving") : t("save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
