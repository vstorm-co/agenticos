"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

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
  Textarea,
} from "@/components/ui";
import { useWorkflows } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { DIALOG_FORM } from "@/lib/dialog-sizes";
import type { WorkflowImported } from "@/lib/workflows/types";

/**
 * **Import** on the workflows list: a `.workflow.json` file, chosen or pasted,
 * made into a new draft. The server takes every id out of it, so the answer is
 * the draft and the pins its builder has to choose again, listed here before
 * the editor opens.
 */
export function ImportWorkflowDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("pages.workflows");
  const router = useRouter();
  const { importFile } = useWorkflows({ enabled: false });
  const [text, setText] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [imported, setImported] = useState<WorkflowImported | null>(null);

  const close = (next: boolean) => {
    if (!next) {
      setText("");
      setProblem(null);
      setImported(null);
    }
    onOpenChange(next);
  };

  const submit = () => {
    let file: unknown;
    try {
      file = JSON.parse(text);
    } catch {
      setProblem(t("importNotJson"));
      return;
    }
    importFile.mutate(file, { onSuccess: setImported });
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className={DIALOG_FORM}>
        <DialogHeader>
          <DialogTitle>{t("importTitle")}</DialogTitle>
          <DialogDescription>
            {imported === null ? t("importDescription") : t("importDone")}
          </DialogDescription>
        </DialogHeader>
        {imported === null ? (
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="workflow-import-file">{t("importFile")}</Label>
              <Input
                id="workflow-import-file"
                type="file"
                accept="application/json,.json"
                onChange={async (event) => {
                  const chosen = event.target.files?.[0];
                  if (chosen === undefined) return;
                  setText(await chosen.text());
                  setProblem(null);
                }}
              />
            </div>
            <Textarea
              aria-label={t("importPaste")}
              placeholder={t("importPaste")}
              value={text}
              onChange={(event) => {
                setText(event.target.value);
                setProblem(null);
              }}
              className="min-h-40 font-mono text-xs"
            />
            {problem !== null && <p className="text-destructive text-xs">{problem}</p>}
          </div>
        ) : imported.unresolved.length > 0 ? (
          <div className="space-y-2">
            <p className="text-sm">{t("importUnresolved")}</p>
            <ul className="border-border divide-border divide-y rounded-lg border text-sm">
              {imported.unresolved.map((item) => (
                <li
                  key={`${item.node_id}-${item.field}`}
                  className="flex justify-between gap-3 px-3 py-2"
                >
                  <span className="font-medium">{item.step}</span>
                  <span className="text-muted-foreground font-mono text-xs">
                    {item.field} · {item.kind}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-muted-foreground text-sm">{t("importNothingToChoose")}</p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => close(false)}>
            {t("importClose")}
          </Button>
          {imported === null ? (
            <Button onClick={submit} disabled={text.trim() === "" || importFile.isPending}>
              {t("importAction")}
            </Button>
          ) : (
            <Button onClick={() => router.push(ROUTES.WORKFLOW_DETAIL(imported.workflow.id))}>
              {t("importOpen")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
