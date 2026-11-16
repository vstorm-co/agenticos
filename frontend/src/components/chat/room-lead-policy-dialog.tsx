"use client";

import { useId, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
} from "@/components/ui";
import { useAgents } from "@/hooks/use-agents";
import { useRoomRoutingActions } from "@/hooks/use-room-routing";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import type { RoomLeadPolicy } from "@/types/room-routing";
import { roomResponders } from "./team-room-responder";

export function RoomLeadPolicyDialog({
  conversationId,
  policy,
  onClose,
}: {
  conversationId: string;
  policy: RoomLeadPolicy;
  onClose: () => void;
}) {
  const t = useTranslations("chat.roomRouting");
  const errors = useTranslations("errors");
  const id = useId();
  const { agents, isLoading, error: agentsError } = useAgents();
  const eligible = roomResponders(agents);
  const actions = useRoomRoutingActions(conversationId);
  const [enabled, setEnabled] = useState(policy.enabled);
  const [lead, setLead] = useState(policy.lead?.agent_id ?? "none");
  const [specialists, setSpecialists] = useState(policy.specialists.map((agent) => agent.agent_id));
  const [maxItems, setMaxItems] = useState(policy.max_items);
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const busy = useRef(false);
  const available = eligible.some((agent) => agent.id === lead);
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (busy.current || conflict || !policy.can_edit || (enabled && !available)) return;
    busy.current = true;
    setPending(true);
    setFailure(null);
    try {
      const result = await actions.savePolicy({
        expected_revision: policy.revision,
        enabled,
        lead_agent_id: lead === "none" ? null : lead,
        specialist_agent_ids: specialists,
        max_items: maxItems,
      });
      if (result) {
        actions.changed();
        onClose();
      }
    } catch (error) {
      const stale = error instanceof ApiError && error.status === 409;
      setConflict(stale);
      setFailure(stale ? t("policyChanged") : getErrorMessage(error, errors, t("saveFailed")));
    } finally {
      busy.current = false;
      if (actions.isCurrent()) setPending(false);
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !pending) onClose();
      }}
    >
      <DialogContent className="max-h-[90dvh] overflow-y-auto">
        <form onSubmit={(event) => void save(event)} className="space-y-5">
          <DialogHeader>
            <DialogTitle>{t("configure")}</DialogTitle>
            <DialogDescription>{t("policyHint")}</DialogDescription>
          </DialogHeader>
          <label className="flex items-center justify-between gap-3" htmlFor={`${id}-enabled`}>
            <span className="text-sm font-medium">{t("enabled")}</span>
            <Switch
              id={`${id}-enabled`}
              checked={enabled}
              onCheckedChange={setEnabled}
              disabled={pending || conflict}
            />
          </label>
          <FormField label={t("lead")} htmlFor={`${id}-lead`}>
            <Select
              value={lead}
              onValueChange={setLead}
              disabled={pending || conflict || isLoading}
            >
              <SelectTrigger id={`${id}-lead`}>
                <SelectValue placeholder={t("chooseLead")} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">{t("chooseLead")}</SelectItem>
                {!available && lead !== "none" && (
                  <SelectItem value={lead} disabled>
                    {t("agentUnavailable")}
                  </SelectItem>
                )}
                {eligible.map((agent) => (
                  <SelectItem key={agent.id} value={agent.id}>
                    {agent.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <fieldset className="space-y-2" disabled={pending || conflict}>
            <legend className="mb-2 text-sm font-medium">{t("specialists")}</legend>
            <p className="text-muted-foreground text-xs">{t("specialistsHint")}</p>
            <div className="max-h-44 space-y-2 overflow-y-auto rounded-lg border p-3">
              {eligible.map((agent) => (
                <label key={agent.id} className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={specialists.includes(agent.id)}
                    disabled={
                      pending ||
                      conflict ||
                      (!specialists.includes(agent.id) && specialists.length >= 12)
                    }
                    onCheckedChange={(checked) =>
                      setSpecialists((held) =>
                        checked === true
                          ? [...held, agent.id]
                          : held.filter((id) => id !== agent.id),
                      )
                    }
                  />
                  <span className="min-w-0 break-words">{agent.name}</span>
                </label>
              ))}
              {eligible.length === 0 && (
                <p className="text-muted-foreground text-xs">{t("noSpecialists")}</p>
              )}
            </div>
          </fieldset>
          <FormField label={t("maxItems")} htmlFor={`${id}-max`}>
            <Select
              value={String(maxItems)}
              onValueChange={(value) => setMaxItems(Number(value))}
              disabled={pending || conflict}
            >
              <SelectTrigger id={`${id}-max`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {[1, 2, 3].map((value) => (
                  <SelectItem key={value} value={String(value)}>
                    {t("itemLimit", { count: value })}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          {agentsError && (
            <p className="text-destructive text-sm" role="alert">
              {t("agentsUnavailable")}
            </p>
          )}
          {failure && (
            <p className="text-destructive text-sm" role="alert">
              {failure}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" disabled={pending} onClick={onClose}>
              {t("cancel")}
            </Button>
            {conflict ? (
              <Button type="button" onClick={() => void actions.refresh().then(onClose)}>
                {t("reloadPolicy")}
              </Button>
            ) : (
              <Button
                type="submit"
                disabled={pending || (enabled && (!available || Boolean(agentsError)))}
              >
                {t(pending ? "saving" : "save")}
              </Button>
            )}
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
