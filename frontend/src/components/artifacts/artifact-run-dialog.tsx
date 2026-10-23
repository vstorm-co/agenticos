"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Hourglass } from "lucide-react";
import { useTranslations } from "next-intl";

import { ViewerNotice } from "@/components/artifacts/live-data-controls";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import type { PausedRun, PendingAction } from "@/hooks/use-artifact-actions";
import { showValue } from "@/lib/artifact-actions";
import { DIALOG_COLUMN, DIALOG_CONFIRM } from "@/lib/dialog-sizes";

/**
 * How long Run stays disabled after the dialog opens: a page that opens it under
 * the cursor, a moment before a click, cannot have that click start a run.
 */
export const RUN_ENABLE_DELAY_MS = 500;

const FIRST_STRONG_ISOLATE = "\u2068";
const POP_ISOLATE = "\u2069";

/** A name inside a sentence of ours, written out as `showValue` does and set apart in its own direction. */
function isolated(name: string): string {
  return `${FIRST_STRONG_ISOLATE}${showValue(name)}${POP_ISOLATE}`;
}

interface ContentProps {
  pending: PendingAction;
  pageTitle: string;
  onCancel: () => void;
  onConfirm: () => void;
}

function RunDialogContent({ pending, pageTitle, onCancel, onConfirm }: ContentProps) {
  const t = useTranslations("artifacts");
  const tui = useTranslations("ui");
  const cancel = useRef<HTMLButtonElement>(null);
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setArmed(true), RUN_ENABLE_DELAY_MS);
    return () => clearTimeout(timer);
  }, []);

  const { action, request } = pending;
  // The request is whole by now: it fits the declared fields exactly, no stray key
  // among them, so these are the fields and nothing else.
  const rows = action.fields.map((field) => ({
    key: field.name,
    label: field.label ?? field.name,
  }));

  return (
    <DialogContent
      className={`${DIALOG_CONFIRM} ${DIALOG_COLUMN}`}
      // Focus lands on Cancel, never on Run: Enter is not a way to agree.
      onOpenAutoFocus={(event) => {
        event.preventDefault();
        cancel.current?.focus();
      }}
    >
      <DialogHeader>
        <DialogTitle>
          <bdi>{showValue(action.name)}</bdi>
        </DialogTitle>
        <DialogDescription>{t("actions.why", { page: isolated(pageTitle) })}</DialogDescription>
      </DialogHeader>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto text-sm">
        <div>
          <p className="text-muted-foreground text-xs">{t("actions.pageWording")}</p>
          <q dir="auto" className="text-foreground break-words [unicode-bidi:plaintext]">
            {showValue(action.label)}
          </q>
        </div>
        <div>
          <p className="text-muted-foreground mb-1 text-xs">{t("actions.sends")}</p>
          {rows.length === 0 ? (
            <p className="text-muted-foreground">{t("actions.sendsNothing")}</p>
          ) : (
            <dl className="space-y-2">
              {rows.map(({ key, label }) => (
                <div key={key}>
                  <dt
                    dir="auto"
                    className="text-muted-foreground text-xs break-words [unicode-bidi:plaintext]"
                  >
                    {showValue(label)}
                  </dt>
                  <dd
                    dir="auto"
                    className="bg-muted rounded-md px-2 py-1 font-mono text-xs break-words whitespace-pre-wrap [unicode-bidi:plaintext]"
                  >
                    {Object.hasOwn(request.input, key) && request.input[key] !== null
                      ? showValue(request.input[key])
                      : t("actions.notGiven")}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      </div>
      <DialogFooter>
        <Button ref={cancel} variant="outline" onClick={onCancel}>
          {tui("cancel")}
        </Button>
        <Button disabled={!armed} onClick={onConfirm}>
          {t("actions.run")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

interface ArtifactRunDialogProps {
  pending: PendingAction | null;
  /** The page's title in the console - what the person opened. */
  pageTitle: string;
  /** Declined, by Cancel, Escape or the backdrop: the page's request is rejected. */
  onCancel: () => void;
  onConfirm: () => void;
}

/**
 * The confirmation every run from a page needs, whatever came before.
 *
 * The title is the workflow's own name from the server; the page's word for it is
 * a quote and nothing more, and every value is text - a React child, never markup.
 * The workflow's name and the page's title, which an agent may have written, are
 * written out and isolated in their own direction like the values are.
 * Only a request that fits the workflow's fields gets here (the hook refuses the
 * rest), and values the eye cannot see are written out (`showValue`) and read in
 * their own direction, so a value cannot reorder what is next to it.
 */
export function ArtifactRunDialog({
  pending,
  pageTitle,
  onCancel,
  onConfirm,
}: ArtifactRunDialogProps) {
  return (
    <Dialog
      open={pending !== null}
      // Controlled by `pending`, so the only change ever asked for is a close:
      // Escape or the backdrop, which decline like Cancel does.
      onOpenChange={() => onCancel()}
    >
      {pending !== null && (
        <RunDialogContent
          key={pending.request.id}
          pending={pending}
          pageTitle={pageTitle}
          onCancel={onCancel}
          onConfirm={onConfirm}
        />
      )}
    </Dialog>
  );
}

/** A run that waits on someone, with the way to it: one line each, above the page. */
export function PausedRuns({ runs }: { runs: PausedRun[] }) {
  const t = useTranslations("artifacts");
  return (
    <>
      {runs.map((run) => (
        <ViewerNotice key={run.runId} tone="info" icon={Hourglass}>
          <span>{t("actions.waiting", { name: run.name })}</span>
          <Button size="sm" variant="outline" asChild>
            <Link href={run.path}>{t("actions.openRun")}</Link>
          </Button>
        </ViewerNotice>
      ))}
    </>
  );
}
