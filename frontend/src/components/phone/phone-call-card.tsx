"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations, useFormatter } from "next-intl";
import { Phone } from "lucide-react";
import { toast } from "sonner";
import { Badge, Button, Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui";
import { usePhoneCall } from "@/hooks/use-phone";
import { getErrorMessage } from "@/lib/api-error";
import { phoneApi, endedPhoneStatuses, type PhoneCall } from "@/lib/phone-api";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";
import Link from "next/link";
import { PhoneSelect } from "./phone-select";
export function PhoneCallCard({ callId }: { callId: string }) {
  const t = useTranslations("phone");
  const query = usePhoneCall(callId);
  if (query.isLoading) return <p className="text-muted-foreground text-xs">{t("loading")}</p>;
  if (!query.data || query.error)
    return <p className="text-muted-foreground text-xs">{t("receiptUnavailable")}</p>;
  return <PhoneReceiptCard call={query.data} />;
}
export function PhoneReceiptCard({ call }: { call: PhoneCall }) {
  const t = useTranslations("phone");
  const errors = useTranslations("errors");
  const format = useFormatter();
  const client = useQueryClient();
  const org = useOrgStore((state) => state.activeOrgId) ?? "current";
  const [transferring, setTransferring] = useState(false);
  const stop = useMutation({
    mutationFn: () => phoneApi.hangup(call.id),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.phone.all(org) }),
    onError: (cause) => toast.error(getErrorMessage(cause, errors)),
  });
  return (
    <div className="bg-card space-y-2 rounded-xl border p-3">
      <div className="flex items-center gap-2">
        <Phone className="size-4" aria-hidden />
        <span className="text-sm font-medium">{t("call")}</span>
        <Badge variant="outline">
          {t.has(`status.${call.status}`) ? t(`status.${call.status}`) : t("status.unknown")}
        </Badge>
      </div>
      <p className="text-muted-foreground text-xs">
        {t("estimatedCost", {
          cost: format.number(Number(call.estimated_cost_usd), {
            style: "currency",
            currency: "USD",
          }),
        })}
      </p>
      {call.status === "queued" && call.not_before ? (
        <p className="text-muted-foreground text-xs">
          {t("notBefore", {
            time: format.dateTime(new Date(call.not_before), {
              dateStyle: "short",
              timeStyle: "short",
            }),
          })}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        {call.conversation_id ? (
          <Link href={`/chat?id=${call.conversation_id}`} className="text-sm underline">
            {call.mode === "report" ? t("preparedReport") : t("transcript")}
          </Link>
        ) : null}
        {!endedPhoneStatuses.has(call.status) ? (
          <Button
            size="sm"
            variant="outline"
            disabled={stop.isPending}
            onClick={() => stop.mutate()}
          >
            {t("hangup")}
          </Button>
        ) : null}
        {call.status === "active" ? (
          <Button size="sm" variant="outline" onClick={() => setTransferring(true)}>
            {t("transfer")}
          </Button>
        ) : null}
      </div>
      {transferring ? (
        <TransferDialog callId={call.id} onClose={() => setTransferring(false)} />
      ) : null}
    </div>
  );
}
function TransferDialog({ callId, onClose }: { callId: string; onClose: () => void }) {
  const t = useTranslations("phone");
  const errors = useTranslations("errors");
  const org = useOrgStore((state) => state.activeOrgId) ?? "current";
  const client = useQueryClient();
  const [selected, setSelected] = useState("");
  const choices = useQuery({
    queryKey: qk.phone.transfers(org, callId),
    queryFn: () => phoneApi.transferOptions(callId),
  });
  const move = useMutation({
    mutationFn: () => phoneApi.transfer(callId, selected),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: qk.phone.all(org) });
      onClose();
    },
    onError: (cause) => toast.error(getErrorMessage(cause, errors)),
  });
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !move.isPending) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("transfer")}</DialogTitle>
        </DialogHeader>
        <p className="text-muted-foreground text-sm">{t("transferHint")}</p>
        <PhoneSelect
          label={t("transferTargets")}
          value={selected}
          onChange={setSelected}
          choices={choices.data ?? []}
          disabled={move.isPending || choices.isLoading}
        />
        {choices.error ? <p role="alert">{getErrorMessage(choices.error, errors)}</p> : null}
        <Button
          disabled={!selected || move.isPending || choices.isFetching}
          onClick={() => move.mutate()}
        >
          {t("transfer")}
        </Button>
      </DialogContent>
    </Dialog>
  );
}
