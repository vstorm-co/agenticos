"use client";

import { useState } from "react";
import { KeyRound } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { CopyButton } from "@/components/chat/copy-button";
import {
  Button,
  FormField,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
import { fieldProblems, getErrorMessage } from "@/lib/api-error";
import type {
  ArtifactPublicLink,
  ArtifactPublicLinkUpdate,
  ArtifactVersion,
} from "@/types/artifact";

/** Stands for "the newest version" in the select, which a version id never is. */
const LATEST = "latest";

// i18n-exempt: an example origin, the same in every language.
const ORIGIN_EXAMPLE = "https://intranet.example.com";

/** `YYYY-MM-DD` in the reader's own time zone, which is what a date input holds. */
export function localDate(iso: string | null): string {
  if (iso === null) return "";
  const date = new Date(iso);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** The end of that day, in the reader's time zone: a link "until the 14th" opens on the 14th. */
export function endOfDay(value: string): string | null {
  return value === "" ? null : new Date(`${value}T23:59:59`).toISOString();
}

/** One site per line, blanks dropped - the server normalises and refuses the rest. */
export function originLines(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "");
}

interface PublicLinkSettingsProps {
  link: ArtifactPublicLink;
  /** The kept versions, newest first - what the link may be pinned to. */
  versions: ArtifactVersion[];
  saving: boolean;
  onSave: (changes: ArtifactPublicLinkUpdate) => Promise<unknown>;
}

/**
 * What else a manager decides about the public link: until when it opens, which
 * version it shows, whether it asks for a password, and which sites may frame it.
 *
 * A refusal names its field, so it is shown under that field rather than as a
 * toast somebody has to match to a box.
 */
export function PublicLinkSettings({ link, versions, saving, onSave }: PublicLinkSettingsProps) {
  const t = useTranslations("artifacts");
  const tErrors = useTranslations("errors");
  const [expiry, setExpiry] = useState(localDate(link.expires_at));
  const [pinned, setPinned] = useState(link.pinned_version_id ?? LATEST);
  const [password, setPassword] = useState("");
  const [origins, setOrigins] = useState(link.embed_origins.join("\n"));
  const [problems, setProblems] = useState<Record<string, string>>({});

  const save = async (changes: ArtifactPublicLinkUpdate) => {
    setProblems({});
    try {
      await onSave(changes);
      return true;
    } catch (error) {
      const named = fieldProblems(error);
      if (named.length === 0) toast.error(getErrorMessage(error, tErrors));
      setProblems(Object.fromEntries(named.map((problem) => [problem.field, problem.message])));
      return false;
    }
  };

  return (
    <div className="space-y-4 border-t pt-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <FormField
          htmlFor="public-link-expiry"
          label={t("linkExpiry")}
          description={t("linkExpiryWhy")}
          error={problems.expires_at}
        >
          <Input type="date" value={expiry} onChange={(event) => setExpiry(event.target.value)} />
        </FormField>
        <FormField
          htmlFor="public-link-version"
          label={t("linkVersion")}
          description={t("linkVersionWhy")}
          error={problems.pinned_version_id}
        >
          <Select value={pinned} onValueChange={setPinned}>
            <SelectTrigger id="public-link-version">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={LATEST}>{t("latestVersion")}</SelectItem>
              {versions.map((version) => (
                <SelectItem key={version.id} value={version.id}>
                  {t("versionBadge", { version: version.number })}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
      </div>
      <FormField
        htmlFor="public-link-origins"
        label={t("embedSites")}
        description={link.password_protected ? t("embedNeedsNoPassword") : t("embedSitesWhy")}
        error={problems.embed_origins}
      >
        <Textarea
          rows={2}
          value={origins}
          onChange={(event) => setOrigins(event.target.value)}
          placeholder={ORIGIN_EXAMPLE}
          className="font-mono text-xs"
        />
      </FormField>
      <Button
        size="sm"
        disabled={saving}
        onClick={() =>
          void save({
            expires_at: endOfDay(expiry),
            pinned_version_id: pinned === LATEST ? null : pinned,
            embed_origins: originLines(origins),
          })
        }
      >
        {t("saveLinkSettings")}
      </Button>

      <div className="space-y-2">
        <FormField
          htmlFor="public-link-password"
          label={t("linkPassword")}
          description={link.password_protected ? t("linkPasswordOn") : t("linkPasswordWhy")}
          error={problems.password}
        >
          <Input
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="sm:w-56"
          />
        </FormField>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={saving || password === ""}
            onClick={async () => {
              if (await save({ password })) setPassword("");
            }}
          >
            <KeyRound className="h-3.5 w-3.5" />
            {link.password_protected ? t("changePassword") : t("setPassword")}
          </Button>
          {link.password_protected && (
            <Button
              size="sm"
              variant="outline"
              disabled={saving}
              onClick={() => void save({ password: null })}
            >
              {t("removePassword")}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

/** The `<iframe>` to paste into an allowed site, while the link is on and embeddable. */
export function EmbedSnippet({ link }: { link: ArtifactPublicLink }) {
  const t = useTranslations("artifacts");
  if (link.embed_url === null || link.embed_origins.length === 0 || link.password_protected) {
    return null;
  }
  const snippet = `<iframe src="${link.embed_url}" width="100%" height="600" style="border:0" loading="lazy"></iframe>`;
  return (
    <div className="space-y-1.5">
      <p className="text-sm font-medium">{t("embedSnippet")}</p>
      <div className="flex items-start gap-2">
        <code className="bg-muted block flex-1 rounded p-2 font-mono text-xs break-all">
          {snippet}
        </code>
        <CopyButton text={snippet} className="h-8 w-8 opacity-100" />
      </div>
    </div>
  );
}
