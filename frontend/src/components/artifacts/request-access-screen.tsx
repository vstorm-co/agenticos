"use client";

import { useState } from "react";
import { Hourglass, Lock } from "lucide-react";
import { useTranslations } from "next-intl";

import { EmptyState } from "@/components/states";
import { Button, Label, Textarea } from "@/components/ui";
import { useRequestAccess } from "@/hooks/use-artifact-requests";

/** The server's cap on a request's note, in characters. */
const MAX_NOTE_LENGTH = 500;

interface RequestAccessScreenProps {
  artifactId: string;
  /** The server already holds a request from the caller. */
  requested: boolean;
}

/**
 * What a member of the page's organization sees when they open a page they may not.
 *
 * It says nothing about the page - no title, owner or agent, because the server
 * sent none - and offers the one thing the caller can do: ask, with a note if they
 * like. Once asked, or when the server says they already did, it says so instead.
 */
export function RequestAccessScreen({ artifactId, requested }: RequestAccessScreenProps) {
  const t = useTranslations("artifacts.access");
  const [note, setNote] = useState("");
  const request = useRequestAccess(artifactId);

  if (requested || request.isSuccess) {
    return <EmptyState icon={Hourglass} title={t("requested")} description={t("requestedWhy")} />;
  }
  return (
    <div className="flex w-full max-w-md flex-col items-center gap-4">
      <EmptyState icon={Lock} title={t("title")} description={t("why")} className="w-full" />
      <div className="w-full space-y-2">
        <Label htmlFor="artifact-access-note">{t("note")}</Label>
        <Textarea
          id="artifact-access-note"
          value={note}
          maxLength={MAX_NOTE_LENGTH}
          rows={3}
          placeholder={t("notePlaceholder")}
          onChange={(event) => setNote(event.target.value)}
        />
        <Button
          className="w-full"
          disabled={request.isPending}
          onClick={() => request.mutate(note.trim() === "" ? null : note.trim())}
        >
          {t("request")}
        </Button>
      </div>
    </div>
  );
}
