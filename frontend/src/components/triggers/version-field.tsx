"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";

import {
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useAllAgentVersions } from "@/hooks/use-agents";

function PublishedVersion({
  agentId,
  value,
  onChange,
}: {
  agentId: string;
  value: string | null;
  onChange: (value: string | null) => void;
}) {
  const t = useTranslations("triggers");
  const { versions, isLoading } = useAllAgentVersions(agentId);
  return (
    <Select value={value ?? ""} onValueChange={onChange} disabled={isLoading}>
      <SelectTrigger aria-label={t("pinnedVersion")}>
        <SelectValue placeholder={t("chooseVersion")} />
      </SelectTrigger>
      <SelectContent>
        {value && !versions.some((version) => version.id === value) && (
          <SelectItem value={value}>{t("selectedVersionUnavailable")}</SelectItem>
        )}
        {versions.map((version) => (
          <SelectItem key={version.id} value={version.id}>
            v{version.version}
            {version.note ? ` — ${version.note}` : ""}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export function VersionField({
  agentId,
  value,
  onChange,
  onValidChange,
}: {
  agentId: string;
  value: string | null;
  onChange: (value: string | null) => void;
  onValidChange: (valid: boolean) => void;
}) {
  const t = useTranslations("triggers");
  const id = useId();
  const [pinning, setPinning] = useState(value !== null);
  return (
    <FormField
      label={t("versionPolicy")}
      htmlFor={id}
      description={t(pinning ? "versionPinHelp" : "versionFollowHelp")}
    >
      <Select
        value={pinning ? "pinned" : "latest"}
        onValueChange={(policy) => {
          const pin = policy === "pinned";
          setPinning(pin);
          if (!pin) onChange(null);
          onValidChange(!pin || value !== null);
        }}
      >
        <SelectTrigger id={id} aria-label={t("versionPolicy")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="latest">{t("followPublishedVersion")}</SelectItem>
          <SelectItem value="pinned">{t("pinPublishedVersion")}</SelectItem>
        </SelectContent>
      </Select>
      {pinning && (
        <PublishedVersion
          agentId={agentId}
          value={value}
          onChange={(version) => {
            onChange(version);
            onValidChange(version !== null);
          }}
        />
      )}
    </FormField>
  );
}
