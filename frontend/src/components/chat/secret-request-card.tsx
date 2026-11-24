"use client";

import { useState } from "react";
import { KeyRound } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { ParkedSecretRequest } from "@/types/runs";

export interface SecretRequestCardProps {
  /** The requests still waiting, in the order they were asked. */
  requests: ParkedSecretRequest[];
  /** Disable all controls (e.g. while the socket is offline). */
  disabled?: boolean;
  /** Called with the request and the value the person typed. */
  onSubmit: (requestId: string, value: string) => void;
  /** Called when the person declines a request. */
  onDecline: (requestId: string) => void;
}

/**
 * The card for a secret a parked run asked for (#13).
 *
 * One request per row: the name the secret will be stored under, what it is
 * for, and a password input for the value. The value lives in this
 * component's local state until it is submitted, and is cleared the moment
 * it is: nothing here keeps it, and the fulfil endpoint seals it straight
 * into the vault. Declining ends the run failed, which the card says
 * plainly rather than leaving the run to stall.
 */
export function SecretRequestCard({
  requests,
  disabled = false,
  onSubmit,
  onDecline,
}: SecretRequestCardProps) {
  const t = useTranslations("chat.secretRequest");
  if (requests.length === 0) return null;
  return (
    <div className="bg-muted/40 border-foreground/10 space-y-3 rounded-2xl border px-3.5 py-3">
      <div className="flex items-center gap-2">
        <KeyRound className="text-muted-foreground h-4 w-4 shrink-0" aria-hidden="true" />
        <p className="text-foreground text-[13px] font-medium">{t("title")}</p>
      </div>
      {requests.map((request) => (
        <SecretRequestRow
          key={request.id}
          request={request}
          disabled={disabled}
          onSubmit={onSubmit}
          onDecline={onDecline}
        />
      ))}
    </div>
  );
}

function SecretRequestRow({
  request,
  disabled,
  onSubmit,
  onDecline,
}: {
  request: ParkedSecretRequest;
  disabled: boolean;
  onSubmit: (requestId: string, value: string) => void;
  onDecline: (requestId: string) => void;
}) {
  const t = useTranslations("chat.secretRequest");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const empty = value.trim() === "";
  const submit = () => {
    if (empty || busy || disabled) return;
    setBusy(true);
    // Cleared before the call returns: the value is the fulfil endpoint's
    // from here, and this input must not keep a copy of it.
    const given = value;
    setValue("");
    onSubmit(request.id, given);
    setBusy(false);
  };
  return (
    <div className="space-y-2">
      <p className="text-foreground text-[13px] font-medium">
        <span className="font-mono">{request.secret_name}</span>
      </p>
      <p className="text-muted-foreground text-[13px]">{request.what_for}</p>
      <label className="text-muted-foreground block text-[12px]" htmlFor={`secret-${request.id}`}>
        {t("valueLabel")}
      </label>
      <Input
        id={`secret-${request.id}`}
        type="password"
        autoComplete="off"
        autoCapitalize="off"
        autoCorrect="off"
        spellCheck={false}
        value={value}
        disabled={disabled || busy}
        placeholder={t("valuePlaceholder")}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") submit();
        }}
      />
      <div className="flex gap-2">
        <Button type="button" disabled={disabled || busy || empty} onClick={submit}>
          {t("provide")}
        </Button>
        <Button
          type="button"
          variant="ghost"
          disabled={disabled || busy}
          onClick={() => onDecline(request.id)}
        >
          {t("decline")}
        </Button>
      </div>
    </div>
  );
}
