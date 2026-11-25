"use client";

import { useEffect, useId, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, CheckCircle2, Upload } from "lucide-react";
import { useAuthStore, useOrgStore } from "@/stores";
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
} from "@/components/ui";
import { ImportResourceChoice } from "./import-resource-choice";
import { OmissionNotice } from "./omission-notice";
import { plannedOmissions, updateImportChoice } from "@/lib/bundle-review";
import { CodeArea } from "@/components/ui/code-area";
import { useBundleTransfer } from "@/hooks/use-bundle-transfer";
import { useResourceImport } from "@/hooks/use-portability";
import { useConsoleRouter } from "@/hooks/use-console-router";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import type {
  BundlePreview,
  BundleRootKind,
  ImportChoice,
  ImportReceipt,
} from "@/lib/portability-api";

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

function ImportResourceContent({
  rootKind,
  onLegacy,
  open,
  onOpenChange,
}: {
  rootKind: BundleRootKind;
  onLegacy?: () => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("portability");
  const tErrors = useTranslations("errors");
  const id = useId();
  const fileInput = useRef<HTMLInputElement>(null);
  const router = useConsoleRouter();
  const { preview, apply } = useResourceImport(rootKind);
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [documentTransferId, setDocumentTransferId] = useState<string | null>(null);
  const [document, setDocument] = useState<BundlePreview | null>(null);
  const [choices, setChoices] = useState<Record<string, ImportChoice>>({});
  const [operationId, setOperationId] = useState(() => crypto.randomUUID());
  const [inlineReceipt, setReceipt] = useState<ImportReceipt | null>(null);
  const [zipFile, setZipFile] = useState<File | null>(null);
  const zip = useBundleTransfer(open, `import:${rootKind}`);
  const reviewedZip = useRef<string | null>(null);
  const receipt = inlineReceipt ?? zip.transfer.data?.receipt ?? null;
  useEffect(() => {
    const row = zip.transfer.data;
    if (row?.status === "review" && row.preview && reviewedZip.current !== row.id) {
      reviewedZip.current = row.id;
      setDocument(row.preview);
      setDocumentTransferId(row.id);
      setChoices(initialChoices(row.preview));
    }
  }, [zip.transfer.data]);
  const omissions = document ? plannedOmissions(document, choices) : {};
  const [problem, setProblem] = useState<string | null>(null);
  const busy = preview.isPending || apply.isPending || zip.busy;
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
      !choice ||
      (choice.action === "create" &&
        !document.options.find((item) => item.key === resource.key)?.can_create) ||
      (choice.action === "reuse" &&
        (!choice.destination_id ||
          (resource.source_parent_id !== null &&
            !destinationParent(resource.kind, resource.source_parent_id))))
    );
  });
  const close = (next: boolean) => {
    if (busy) return;
    if (!next) {
      setText("");
      setZipFile(null);
      zip.reset();
      reviewedZip.current = null;
      setFileName(null);
      setDocument(null);
      setDocumentTransferId(null);
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
    preview.reset();
    apply.reset();
    const resumable =
      file.name.toLowerCase().endsWith(".zip") &&
      zip.transfer.data?.status === "awaiting_upload" &&
      zip.transfer.data.total_bytes === file.size &&
      (!zipFile || zipFile.name === file.name);
    if (!resumable) zip.reset();
    reviewedZip.current = null;
    setOperationId(crypto.randomUUID());
    if (file.name.toLowerCase().endsWith(".zip")) {
      if (file.size > 512 * 1024 * 1024) {
        setProblem(t("zipTooLarge"));
        return;
      }
      setZipFile(file);
      setFileName(file.name);
      setText("");
      setProblem(null);
      return;
    }
    setZipFile(null);
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
    if (zipFile) {
      zip.uploadZip.mutate({ file: zipFile, requestId: operationId });
      return;
    }
    preview.mutate(text, {
      onSuccess: (data) => {
        setDocument(data);
        setDocumentTransferId(null);
        setChoices(initialChoices(data));
        setOperationId(crypto.randomUUID());
      },
    });
  };
  const submit = () => {
    if (documentTransferId !== null) {
      if (zip.transfer.data?.id !== documentTransferId) {
        setProblem(t("noReviewedTransfer"));
        return;
      }
      zip.apply.mutate(choices);
      return;
    }
    if (document)
      apply.mutate(
        { operation_id: operationId, bundle: document.bundle, choices },
        { onSuccess: setReceipt },
      );
  };
  const error =
    problem ??
    (zip.transfer.data?.status === "failed" ? t("transferFailed") : null) ??
    (preview.error || apply.error || zip.error
      ? getErrorMessage(preview.error ?? apply.error ?? zip.error, tErrors, t("operationError"))
      : null);
  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className={`${DIALOG_FORM} ${DIALOG_COLUMN}`}>
        <DialogHeader>
          <DialogTitle>
            {receipt
              ? t("importComplete")
              : t(rootKind === "workflow" ? "importWorkflowTitle" : "importTitle")}
          </DialogTitle>
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
              <OmissionNotice
                omissions={receipt.omitted_bindings ?? {}}
                resources={
                  document?.bundle.resources ?? zip.transfer.data?.preview?.bundle.resources ?? []
                }
                completed
              />
              {receipt.skipped.length > 0 && (
                <p className="text-muted-foreground text-sm">{t("skippedHint")}</p>
              )}
            </div>
          ) : document ? (
            <div className="space-y-3">
              <OmissionNotice omissions={omissions} resources={document.bundle.resources} />
              {document.bundle.resources.map((resource) => (
                <ImportResourceChoice
                  key={resource.key}
                  resource={resource}
                  choice={choices[resource.key] ?? { action: "skip" }}
                  option={document.options.find((item) => item.key === resource.key)}
                  root={document.bundle.roots.includes(resource.key)}
                  busy={busy}
                  parentId={destinationParent(resource.kind, resource.source_parent_id)}
                  onChange={(next) =>
                    setChoices((previous) => updateImportChoice(document, previous, resource, next))
                  }
                />
              ))}
            </div>
          ) : (
            <>
              <Button
                type="button"
                variant="outline"
                className="min-h-24 w-full gap-3 whitespace-normal"
                disabled={busy}
                onClick={() => fileInput.current?.click()}
              >
                <Upload className="size-5 shrink-0" />
                <span className="break-words">{fileName ?? t("chooseFile")}</span>
              </Button>
              <Input
                ref={fileInput}
                type="file"
                disabled={busy}
                accept=".yaml,.yml,.json,.zip,application/json,application/yaml,application/zip"
                className="sr-only"
                aria-label={t("chooseFile")}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void readFile(file);
                }}
              />
              {onLegacy && (
                <Button variant="ghost" disabled={busy} onClick={onLegacy}>
                  {t("importLegacy")}
                </Button>
              )}
              <Label htmlFor={`${id}-text`}>{t("pasteConfiguration")}</Label>
              <CodeArea
                id={`${id}-text`}
                value={text}
                disabled={busy}
                onChange={(value) => {
                  zip.reset();
                  preview.reset();
                  apply.reset();
                  reviewedZip.current = null;
                  setText(value);
                  setZipFile(null);
                  setFileName(null);
                }}
                name={`${rootKind}.yaml`}
                aria-label={t("pasteConfiguration")}
                placeholder={t("pasteConfiguration")}
                className="border-input bg-field min-h-48 rounded-xl border"
                maxLength={4 * 1024 * 1024}
              />
            </>
          )}
          {zip.transfer.data?.status === "awaiting_upload" && !zipFile && (
            <p role="status" className="text-muted-foreground text-sm">
              {t("reselectZip")}
            </p>
          )}
          {zip.busy && (
            <p role="status" className="text-muted-foreground text-sm">
              {t("transferWorking")}
            </p>
          )}
          {(zip.restoreFailed ||
            zip.transfer.data?.status === "failed" ||
            zip.transfer.data?.status === "expired") && (
            <Button
              variant="outline"
              onClick={() => {
                zip.reset();
                preview.reset();
                apply.reset();
                setProblem(null);
                setDocument(null);
                setDocumentTransferId(null);
                setChoices({});
                setReceipt(null);
                reviewedZip.current = null;
                setZipFile(null);
                setFileName(null);
                setText("");
                setOperationId(crypto.randomUUID());
              }}
            >
              {t("startNewTransfer")}
            </Button>
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
                router.push(
                  rootKind === "agent"
                    ? ROUTES.AGENT_DETAIL(target)
                    : ROUTES.WORKFLOW_DETAIL(target),
                );
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
                    setDocumentTransferId(null);
                    zip.reset();
                    reviewedZip.current = null;
                    setOperationId(crypto.randomUUID());
                    apply.reset();
                  } else close(false);
                }}
              >
                {document && <ArrowLeft className="size-4" />}
                {document ? t("back") : t("close")}
              </Button>
              <Button
                disabled={busy || (!document && !text.trim() && !zipFile) || Boolean(incomplete)}
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

export function ImportResourceDialog(props: Parameters<typeof ImportResourceContent>[0]) {
  const user = useAuthStore((state) => state.user?.id ?? null);
  const org = useOrgStore((state) => state.activeOrgId);
  return <ImportResourceContent key={JSON.stringify([user, org, props.rootKind])} {...props} />;
}
