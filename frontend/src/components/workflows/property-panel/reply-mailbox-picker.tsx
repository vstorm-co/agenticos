"use client";

import { useTranslations } from "next-intl";
import {
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Skeleton,
} from "@/components/ui";
import type { ReplyMailboxSelection } from "@/lib/workflows/types";
import { usePortals } from "@/hooks/use-portals";

/** Only the connected organization's mailboxes are choices; never the default account by inference. */
export function ReplyMailboxPicker({
  value,
  disabled,
  onChange,
}: {
  value: unknown;
  disabled?: boolean;
  onChange: (config: ReplyMailboxSelection) => void;
}) {
  const t = useTranslations("pages.workflows");
  const { items, isLoading, error } = usePortals();
  if (isLoading) return <Skeleton className="h-10 w-full" />;
  if (error) return <p role="alert">{t("replyMailboxFailed")}</p>;
  const choices = items.filter(
    (item) =>
      ["google", "microsoft"].includes(item.portal.key) &&
      item.action === "create" &&
      item.connectionId !== null,
  );
  const selected = typeof value === "string" ? value : "";
  return (
    <div className="space-y-1">
      <Label>{t("replyMailbox")}</Label>
      <Select
        disabled={disabled}
        value={selected}
        onValueChange={(id) => {
          const item = choices.find((one) => one.connectionId === id);
          if (item)
            onChange({
              connection_id: id,
              provider: item.portal.key === "google" ? "google" : "outlook",
              mailbox: null,
            });
        }}
      >
        <SelectTrigger aria-label={t("replyMailbox")}>
          <SelectValue placeholder={t("replyMailboxChoose")} />
        </SelectTrigger>
        <SelectContent>
          {selected && !choices.some((item) => item.connectionId === selected) && (
            <SelectItem value={selected} disabled>
              {t("replyMailboxUnavailable")}
            </SelectItem>
          )}
          {choices.map((item) => (
            <SelectItem key={item.connectionId} value={item.connectionId ?? ""}>
              {item.portal.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {choices.length === 0 && (
        <p className="text-muted-foreground text-xs">{t("replyMailboxConnect")}</p>
      )}
    </div>
  );
}
