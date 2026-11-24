"use client";

import { useId, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, CheckCircle2, Upload } from "lucide-react";
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { ImportDestinationPicker } from "./import-destination-picker";
import { CodeArea } from "@/components/ui/code-area";
import { useAgentImport } from "@/hooks/use-portability";
import { useConsoleRouter } from "@/hooks/use-console-router";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import type { BundlePreview, ImportChoice, ImportReceipt } from "@/lib/portability-api";

function initialChoices(preview: BundlePreview): Record<string, ImportChoice> {
  const options = new Map(preview.options.map((option) => [option.key, option]));
  return Object.fromEntries(
    preview.bundle.resources.map((item) => {
      const option = options.get(item.key);
      const choice: ImportChoice =
        preview.bundle.roots.includes(item.key) || (!option?.reusable_id && option?.can_create)
          ? { action: "create" }
          : option?.reusable_id
            ? { action: "reuse", destination_id: option.reusable_id }
            : { action: "skip" };
      return [item.key, choice];
    }),
  );
}

export function ImportAgentDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("portability");
  const tErrors = useTranslations("errors");
  const id = useId();
  const fileInput = useRef<HTMLInputElement>(null);
  const router = useConsoleRouter();
  const { preview, apply } = useAgentImport();
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [document, setDocument] = useState<BundlePreview | null>(null);
  const [choices, setChoices] = useState<Record<string, ImportChoice>>({});
  const [operationId, setOperationId] = useState(() => crypto.randomUUID());
  const [receipt, setReceipt] = useState<ImportReceipt | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const busy = preview.isPending || apply.isPending;
  const reusedOwners = new Map(
    document?.bundle.resources.flatMap((resource) => {
      const choice = choices[resource.key];
      return resource.source_id && choice?.action === "reuse" && choice.destination_id
        ? [[`${resource.kind}/${resource.source_id}`, choice.destination_id] as const]
        : [];
    }),
  );
  const destinationParent = (kind: string, sourceParentId: string | null) =>
    sourceParentId
      ? reusedOwners.get(`${kind === "agent_version" ? "agent" : "skill"}/${sourceParentId}`)
      : undefined;
  const incomplete = document?.bundle.resources.some((resource) => {
    const choice = choices[resource.key];
    return (
      choice?.action === "reuse" &&
      (!choice.destination_id ||
        (resource.source_parent_id !== null &&
          !destinationParent(resource.kind, resource.source_parent_id)))
    );
  });
  const close = (next: boolean) => {
    if (busy) return;
    if (!next) {
      setText("");
      setFileName(null);
      setDocument(null);
      setChoices({});
      setReceipt(null);
      setProblem(null);
      preview.reset();
      apply.reset();
      setOperationId(crypto.randomUUID());
    }
    onOpenChange(next);
  };
  const readFile = async (file: File) => {
    if (file.size > 4 * 1024 * 1024) {
      setProblem(t("fileTooLarge"));
      return;
    }
    try {
      setText(await file.text());
      setFileName(file.name);
      setProblem(null);
    } catch {
      setProblem(t("readError"));
    }
  };
  const review = () => {
    setProblem(null);
    preview.mutate(text, {
      onSuccess: (data) => {
        setDocument(data);
        setChoices(initialChoices(data));
        setOperationId(crypto.randomUUID());
      },
    });
  };
  const submit = () => {
    if (document)
      apply.mutate(
        { operation_id: operationId, bundle: document.bundle, choices },
        { onSuccess: setReceipt },
      );
  };
  const error =
    problem ??
    (preview.error || apply.error
      ? getErrorMessage(preview.error ?? apply.error, tErrors, t("operationError"))
      : null);
  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className={`${DIALOG_FORM} ${DIALOG_COLUMN}`}>
        <DialogHeader>
          <DialogTitle>{receipt ? t("importComplete") : t("importTitle")}</DialogTitle>
          <DialogDescription>
            {receipt
              ? t("importCompleteHint")
              : document
                ? t("mappingHint")
                : t("importDescription")}
          </DialogDescription>
        </DialogHeader>
        <div className={`${DIALOG_BODY} space-y-4`}>
          {receipt ? (
            <div className="space-y-4">
              <CheckCircle2 className="text-success size-8" aria-hidden="true" />
              <p>
                {t("importCounts", {
                  created: Object.keys(receipt.created).length,
                  reused: Object.keys(receipt.reused).length,
                  skipped: receipt.skipped.length,
                })}
              </p>
              {receipt.skipped.length > 0 && (
                <p className="text-muted-foreground text-sm">{t("skippedHint")}</p>
              )}
            </div>
          ) : document ? (
            <div className="space-y-3">
              {document.bundle.resources.map((resource, index) => {
                const choice = choices[resource.key] ?? { action: "skip" as const };
                const option = document.options.find((item) => item.key === resource.key);
                const root = document.bundle.roots.includes(resource.key);
                const update = (next: ImportChoice) =>
                  setChoices((previous) => {
                    const updated = { ...previous, [resource.key]: next };
                    const before = previous[resource.key];
                    if (
                      before?.action !== next.action ||
                      before?.destination_id !== next.destination_id
                    ) {
                      for (const child of document.bundle.resources) {
                        const ownerKind = child.kind === "agent_version" ? "agent" : "skill";
                        if (
                          resource.source_id &&
                          child.source_parent_id === resource.source_id &&
                          resource.kind === ownerKind &&
                          previous[child.key]?.action === "reuse"
                        ) {
                          updated[child.key] = { action: "reuse", destination_id: "" };
                        }
                      }
                    }
                    return updated;
                  });
                return (
                  <fieldset
                    key={resource.key}
                    className="border-border min-w-0 space-y-3 rounded-xl border p-3"
                  >
                    <legend className="max-w-full px-1 text-sm font-medium break-words">
                      {resource.name}
                    </legend>
                    <Label className="sr-only" htmlFor={`${id}-action-${index}`}>
                      {t("actionFor", { name: resource.name })}
                    </Label>
                    <Select
                      value={choice.action}
                      disabled={busy || root}
                      onValueChange={(value) =>
                        update(
                          value === "reuse"
                            ? { action: "reuse", destination_id: option?.reusable_id ?? "" }
                            : { action: value === "create" ? "create" : "skip" },
                        )
                      }
                    >
                      <SelectTrigger id={`${id}-action-${index}`}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="create" disabled={!option?.can_create && !root}>
                          {t("createCopy")}
                        </SelectItem>
                        <SelectItem value="reuse">{t("reuse")}</SelectItem>
                        <SelectItem value="skip" disabled={root}>
                          {t("skip")}
                        </SelectItem>
                      </SelectContent>
                    </Select>
                    {choice.action === "create" && (
                      <div className="space-y-2">
                        <Label htmlFor={`${id}-name-${index}`}>{t("newName")}</Label>
                        <Input
                          id={`${id}-name-${index}`}
                          value={choice.name ?? resource.name}
                          disabled={busy}
                          onChange={(event) =>
                            update({ action: "create", name: event.target.value })
                          }
                        />
                      </div>
                    )}
                    {choice.action === "reuse" && (
                      <ImportDestinationPicker
                        id={`${id}-destination-${index}`}
                        kind={resource.kind}
                        value={choice.destination_id ?? ""}
                        selectedName={
                          choice.destination_id === option?.reusable_id
                            ? option?.reusable_name
                            : undefined
                        }
                        key={`${resource.key}-${destinationParent(resource.kind, resource.source_parent_id) ?? "none"}`}
                        parentId={destinationParent(resource.kind, resource.source_parent_id)}
                        disabled={busy}
                        onChange={(identity) =>
                          update({ action: "reuse", destination_id: identity })
                        }
                      />
                    )}
                    {choice.action === "skip" && (
                      <p className="text-muted-foreground text-xs">{t("skipHint")}</p>
                    )}
                  </fieldset>
                );
              })}
            </div>
          ) : (
            <>
              <Button
                type="button"
                variant="outline"
                className="min-h-24 w-full gap-3 whitespace-normal"
                onClick={() => fileInput.current?.click()}
              >
                <Upload className="size-5 shrink-0" />
                <span className="break-words">{fileName ?? t("chooseFile")}</span>
              </Button>
              <Input
                ref={fileInput}
                type="file"
                accept=".yaml,.yml,.json,application/json,application/yaml"
                className="sr-only"
                aria-label={t("chooseFile")}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void readFile(file);
                }}
              />
              <Label htmlFor={`${id}-text`}>{t("pasteConfiguration")}</Label>
              <CodeArea
                id={`${id}-text`}
                value={text}
                onChange={setText}
                name="agent.yaml"
                aria-label={t("pasteConfiguration")}
                placeholder={t("pasteConfiguration")}
                className="border-input bg-field min-h-48 rounded-xl border"
                maxLength={4 * 1024 * 1024}
              />
            </>
          )}
          {error && (
            <p role="alert" className="text-destructive text-sm">
              {error}
            </p>
          )}
        </div>
        <DialogFooter>
          {receipt ? (
            <Button
              onClick={() => {
                const target = Object.values(receipt.roots)[0];
                if (!target) {
                  setProblem(t("missingRoot"));
                  return;
                }
                close(false);
                router.push(ROUTES.AGENT_DETAIL(target));
              }}
            >
              {t("openDraft")}
              <ArrowRight className="size-4" />
            </Button>
          ) : (
            <>
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => {
                  if (document) {
                    setDocument(null);
                    apply.reset();
                  } else close(false);
                }}
              >
                {document && <ArrowLeft className="size-4" />}
                {document ? t("back") : t("close")}
              </Button>
              <Button
                disabled={busy || !text.trim() || Boolean(incomplete)}
                onClick={document ? submit : review}
              >
                {busy ? t("working") : document ? t("importDrafts") : t("review")}
                <ArrowRight className="size-4" />
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
