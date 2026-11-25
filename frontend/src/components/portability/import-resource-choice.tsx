"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";
import {
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { ImportDestinationPicker } from "@/components/agents/import-destination-picker";
import { supportsImportDestination } from "@/lib/bundle-review";
import type { BundlePreview, BundleResource, ImportChoice } from "@/lib/portability-api";

export function ImportResourceChoice({
  resource,
  choice,
  option,
  root,
  busy,
  parentId,
  onChange,
}: {
  resource: BundleResource;
  choice: ImportChoice;
  option: BundlePreview["options"][number] | undefined;
  root: boolean;
  busy: boolean;
  parentId: string | undefined;
  onChange: (choice: ImportChoice) => void;
}) {
  const t = useTranslations("portability");
  const id = useId();
  const update = onChange;
  const supported = supportsImportDestination(resource.kind);
  return (
    <fieldset className="border-border min-w-0 space-y-3 rounded-xl border p-3">
      <legend className="max-w-full px-1 text-sm font-medium break-words">{resource.name}</legend>
      <Label className="sr-only" htmlFor={`${id}-action-item`}>
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
        <SelectTrigger id={`${id}-action-item`}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="create" disabled={!option?.can_create}>
            {t("createCopy")}
          </SelectItem>
          <SelectItem value="reuse" disabled={!supported}>
            {t("reuse")}
          </SelectItem>
          <SelectItem value="skip" disabled={root}>
            {t("skip")}
          </SelectItem>
        </SelectContent>
      </Select>
      {choice.action === "create" && (
        <div className="space-y-2">
          <Label htmlFor={`${id}-name-item`}>{t("newName")}</Label>
          <Input
            id={`${id}-name-item`}
            value={choice.name ?? resource.name}
            disabled={busy}
            onChange={(event) => update({ action: "create", name: event.target.value })}
          />
        </div>
      )}
      {resource.kind === "agent_version" && (
        <p className="text-muted-foreground text-xs">{t("publishedVersionHint")}</p>
      )}
      {!supported && <p className="text-muted-foreground text-xs">{t("unsupportedMapping")}</p>}
      {choice.action === "reuse" && supported && (
        <ImportDestinationPicker
          id={`${id}-destination-item`}
          kind={resource.kind}
          value={choice.destination_id ?? ""}
          selectedName={
            choice.destination_id === option?.reusable_id ? option?.reusable_name : undefined
          }
          key={`${resource.key}-${parentId ?? "none"}`}
          parentId={parentId}
          disabled={busy}
          onChange={(identity) => update({ action: "reuse", destination_id: identity })}
        />
      )}
      {choice.action === "skip" && <p className="text-muted-foreground text-xs">{t("skipHint")}</p>}
    </fieldset>
  );
}
