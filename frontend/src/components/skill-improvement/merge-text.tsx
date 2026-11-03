"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Badge, Button, Textarea } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { MergeText as MergeTextValue } from "@/types/skill-merge";

/**
 * One text of a merge. A part only one side changed says which; a conflict shows both
 * sides beside what the merge says, marked when nobody has settled it yet, and a person
 * may rewrite it - the assistant's proposal stays visible beside the rewrite.
 */
export function MergeText({
  label,
  text,
  editable,
  saving,
  onSave,
}: {
  /** What the text is: the description, or a part of the instructions. */
  label: string;
  text: MergeTextValue;
  editable: boolean;
  saving: boolean;
  /** Resolves to whether the text was saved; a refusal keeps the rewrite on screen. */
  onSave: (result: string) => Promise<boolean>;
}) {
  const t = useTranslations("skillImprovement.merge");
  const [draft, setDraft] = useState<string | null>(null);
  const conflict = text.state === "conflict";
  const open = conflict && text.result === null;
  const value = draft ?? text.result ?? text.proposed ?? "";
  return (
    <section
      aria-label={label}
      className={cn(
        "space-y-2 rounded-lg border p-3",
        open && "border-destructive/60 bg-destructive/5",
      )}
    >
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-medium">{label}</span>
        <Badge variant={open ? "destructive" : "outline"}>{t(`state.${text.state}`)}</Badge>
        {conflict && <span className="text-muted-foreground">{t(`settled.${settled(text)}`)}</span>}
      </div>
      {conflict || text.result === null ? (
        <div className="grid gap-2 md:grid-cols-3">
          <Side title={t("forkSide")} text={text.fork} />
          <Side title={t("mainSide")} text={text.main} />
          <div className="space-y-1">
            <p className="text-muted-foreground text-xs">{t("resultSide")}</p>
            {editable ? (
              <>
                <Textarea
                  aria-label={t("resultOf", { label })}
                  className="min-h-24 font-mono text-xs"
                  value={value}
                  onChange={(event) => setDraft(event.target.value)}
                />
                <Button
                  size="sm"
                  disabled={draft === null || draft === (text.result ?? "")}
                  loading={saving}
                  onClick={() => void onSave(value).then((saved) => saved && setDraft(null))}
                >
                  {t("save")}
                </Button>
              </>
            ) : (
              <Body text={text.result ?? t("unsettled")} />
            )}
          </div>
        </div>
      ) : (
        <Body text={text.result} />
      )}
    </section>
  );
}

/** Who wrote a conflict's text: nobody yet, the assistant, or a person. */
function settled(text: MergeTextValue): "open" | "proposed" | "edited" {
  if (text.result === null) return "open";
  return text.edited ? "edited" : "proposed";
}

function Side({ title, text }: { title: string; text: string }) {
  return (
    <div className="space-y-1">
      <p className="text-muted-foreground text-xs">{title}</p>
      <Body text={text} />
    </div>
  );
}

function Body({ text }: { text: string }) {
  return (
    <pre className="bg-muted/40 rounded-md p-2 font-mono text-xs break-words whitespace-pre-wrap">
      {text}
    </pre>
  );
}
