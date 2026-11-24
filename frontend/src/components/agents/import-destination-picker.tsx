"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  Button,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useImportDestinations } from "@/hooks/use-portability";
import { getErrorMessage } from "@/lib/api-error";

const PAGE_SIZE = 25;

export function ImportDestinationPicker({
  id,
  kind,
  parentId,
  value,
  selectedName,
  disabled,
  onChange,
}: {
  id: string;
  kind: string;
  parentId?: string;
  value: string;
  selectedName?: string | null;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  const t = useTranslations("portability");
  const errors = useTranslations("errors");
  const [search, setSearch] = useState("");
  const [skip, setSkip] = useState(0);
  const [chosenName, setChosenName] = useState(selectedName);
  const needsOwner = ["agent_version", "skill_version", "skill_fork"].includes(kind) && !parentId;
  const query = useImportDestinations(
    { kind, parent_id: parentId, search, skip, limit: PAGE_SIZE },
    !needsOwner,
  );
  const rows = query.data?.items ?? [];
  const searchable = !["agent", "agent_version", "skill_version"].includes(kind);
  if (needsOwner)
    return <p className="text-muted-foreground text-xs">{t("chooseExistingOwner")}</p>;
  return (
    <div className="space-y-2">
      {searchable && (
        <Input
          type="search"
          aria-label={t("searchDestinations")}
          placeholder={t("searchDestinations")}
          value={search}
          disabled={disabled}
          onChange={(event) => {
            setSearch(event.target.value);
            setSkip(0);
          }}
        />
      )}
      <Label htmlFor={id}>{t("destinationResource")}</Label>
      <Select
        value={value}
        disabled={disabled || query.isPending}
        onValueChange={(identity) => {
          setChosenName(rows.find((row) => row.id === identity)?.name);
          onChange(identity);
        }}
      >
        <SelectTrigger id={id}>
          <SelectValue placeholder={query.isPending ? t("loading") : t("chooseDestination")} />
        </SelectTrigger>
        <SelectContent>
          {value && !rows.some((row) => row.id === value) && (
            <SelectItem value={value}>{chosenName ?? t("selectedDestination")}</SelectItem>
          )}
          {rows.map((row) => (
            <SelectItem key={row.id} value={row.id}>
              {row.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {query.error && (
        <p role="alert" className="text-destructive text-sm">
          {getErrorMessage(query.error, errors, t("operationError"))}
        </p>
      )}
      {query.data && rows.length === 0 && (
        <p className="text-muted-foreground text-xs">{t("noDestinations")}</p>
      )}
      {query.data && query.data.total > PAGE_SIZE && (
        <div className="flex items-center justify-end gap-2">
          <Button
            variant="outline"
            size="icon"
            aria-label={t("previousDestinations")}
            disabled={disabled || skip === 0}
            onClick={() => setSkip(skip - PAGE_SIZE)}
          >
            <ChevronLeft className="size-4" />
          </Button>
          <Button
            variant="outline"
            size="icon"
            aria-label={t("nextDestinations")}
            disabled={disabled || skip + PAGE_SIZE >= query.data.total}
            onClick={() => setSkip(skip + PAGE_SIZE)}
          >
            <ChevronRight className="size-4" />
          </Button>
        </div>
      )}
    </div>
  );
}
