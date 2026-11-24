"use client";

import { toast } from "sonner";
import { useTranslations } from "next-intl";

import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";
import { Button, Input, Label } from "@/components/ui";

interface SecretRevealFieldProps {
  /** The secret to reveal, returned exactly once. */
  secret: string;
  /** The field label - a portal's or a trigger's own "signing secret" wording. */
  label: string;
  /** The one-time warning under the field, spelling out what to do with it. */
  note: string;
  /** A stable id so the label binds to the input; unique per mounting surface. */
  id?: string;
}

/**
 * A reveal-once secret: a read-only field, a copy button, and a warning that it
 * will not be shown again.
 *
 * The signing secret a webhook is verified against is returned by the server
 * exactly once - on create for a manual preset, and on a rotate - so the copy is
 * offered here rather than left to be read back later, which the server refuses.
 * Shared by the portal create flow and the rotate action so both reveal it the
 * same way.
 */
export function SecretRevealField({
  secret,
  label,
  note,
  id = "revealed-secret",
}: SecretRevealFieldProps) {
  const t = useTranslations("triggers");
  const tc = useTranslations("common");
  const { copy: write, copied } = useCopyToClipboard();

  async function copy() {
    if (!(await write(secret))) toast.error(tc("copyFailed"));
  }

  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex gap-2">
        <Input
          id={id}
          value={secret}
          readOnly
          className="min-w-0 flex-1 font-mono text-base md:text-xs"
        />
        <Button type="button" variant="outline" onClick={copy}>
          {copied ? t("copied") : t("copy")}
        </Button>
      </div>
      <p className="text-muted-foreground text-xs">{note}</p>
    </div>
  );
}
