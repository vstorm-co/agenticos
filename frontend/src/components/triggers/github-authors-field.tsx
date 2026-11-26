"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";
import { FormField, NativeSelect } from "@/components/ui";

/** The missing event key means issues, just as it does in GithubTriggerConfig. */
export function GithubAuthorsField({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
}) {
  const t = useTranslations("portals");
  const id = useId();
  if (!["issues", "pull_request", "issue_comment"].includes(String(config.event ?? "issues")))
    return null;
  const authors =
    config.authors === "contributors" || config.authors === "anyone" ? config.authors : "members";
  return (
    <FormField
      htmlFor={id}
      label={t("githubAuthorsLabel")}
      description={t(`githubAuthorsHint.${authors}`)}
    >
      <NativeSelect
        name="authors"
        value={authors}
        onChange={(event) => onChange({ ...config, authors: event.target.value })}
      >
        <option value="members">{t("githubAuthors.members")}</option>
        <option value="contributors">{t("githubAuthors.contributors")}</option>
        <option value="anyone">{t("githubAuthors.anyone")}</option>
      </NativeSelect>
    </FormField>
  );
}
