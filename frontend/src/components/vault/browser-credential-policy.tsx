"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Checkbox,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import {
  useBrowserCredentialAudience,
  useBrowserCredentialChoices,
  useBrowserCredentialPolicy,
} from "@/hooks/use-browser-credentials";
import { getErrorMessage } from "@/lib/api-error";
import type {
  BrowserCredentialPolicy as Policy,
  BrowserCredentialPolicyEdit,
} from "@/types/browser-credentials";
import type { Secret } from "@/types/secrets";
import { BrowserCredentialMetadata } from "./browser-credential-metadata";

export function BrowserCredentialPolicy({ secret }: { secret: Secret }) {
  const audience = useBrowserCredentialAudience();
  return (
    <ScopedBrowserCredentialPolicy
      key={`${audience.actor}:${audience.organization}:${secret.id}`}
      secret={secret}
    />
  );
}

function ScopedBrowserCredentialPolicy({ secret }: { secret: Secret }) {
  const t = useTranslations("browserCredentials");
  const tErrors = useTranslations("errors");
  const audience = useBrowserCredentialAudience();
  const owner =
    !!audience.actor && secret.owner_user_id === audience.actor && secret.can_edit === true;
  const query = useBrowserCredentialPolicy(secret.id, owner);
  if (!owner) return <p className="text-sm">{t("currentOwnerOnly")}</p>;
  if (query.error)
    return (
      <div role="alert" className="space-y-3">
        <p>{getErrorMessage(query.error, tErrors)}</p>
        <Button variant="outline" onClick={() => void query.refetch()}>
          {t("checkAgain")}
        </Button>
      </div>
    );
  if (!query.data || query.isFetching) return <p role="status">{t("loadingPolicy")}</p>;
  if (query.data.secret_id !== secret.id) return <p role="alert">{t("policyUnavailable")}</p>;
  return (
    <div className="space-y-4">
      <BrowserCredentialMetadata metadata={secret.browser} />
      <PolicyForm
        key={`${audience.actor}:${audience.organization}:${query.data.authorization_generation}`}
        policy={query.data}
        pending={query.update.isPending}
        error={query.update.error ? getErrorMessage(query.update.error, tErrors) : null}
        saved={query.update.isSuccess}
        save={query.update.mutate}
      />
    </div>
  );
}

function PolicyForm({
  policy,
  pending,
  error,
  saved,
  save,
}: {
  policy: Policy;
  pending: boolean;
  error: string | null;
  saved: boolean;
  save: (body: BrowserCredentialPolicyEdit) => void;
}) {
  const t = useTranslations("browserCredentials");
  const [mode, setMode] = useState(policy.mode);
  const [agentIds, setAgentIds] = useState(policy.agent_ids);
  const [memberIds, setMemberIds] = useState(policy.member_ids);
  const agents = useBrowserCredentialChoices("agents", mode === "shared");
  const members = useBrowserCredentialChoices("members", mode === "shared");
  const agentRows = (agents.data?.pages.flatMap((page) => page.items) ?? [])
    .filter((agent) => agent.status !== "archived" && agent.can_run)
    .map((agent) => ({ id: agent.id, name: agent.name }));
  const memberRows = (members.data?.pages.flatMap((page) => page.items) ?? []).map((member) => ({
    id: member.user_id,
    name: member.full_name || member.email,
  }));
  const complete =
    mode === "personal" ||
    (agentIds.length > 0 &&
      agentIds.length <= 50 &&
      memberIds.length > 0 &&
      memberIds.length <= 100 &&
      !agents.isPending &&
      !members.isPending &&
      !agents.error &&
      !members.error);
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="browser-policy-mode">{t("useMode")}</Label>
        <Select
          value={mode}
          disabled={pending}
          onValueChange={(value) => setMode(value as Policy["mode"])}
        >
          <SelectTrigger id="browser-policy-mode">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="personal">{t("personalUse")}</SelectItem>
            <SelectItem value="shared">{t("sharedUse")}</SelectItem>
          </SelectContent>
        </Select>
        <p className="text-muted-foreground text-xs">
          {t(mode === "shared" ? "sharedUseHelp" : "personalUseHelp")}
        </p>
      </div>
      {mode === "shared" && (
        <>
          <AudiencePicker
            kind="agents"
            rows={agentRows}
            selected={agentIds}
            setSelected={setAgentIds}
            max={50}
            disabled={pending}
            loading={agents.isPending}
            error={!!agents.error}
            hasMore={!!agents.hasNextPage}
            loadingMore={agents.isFetchingNextPage}
            loadMore={() => void agents.fetchNextPage()}
            retry={() => void agents.refetch()}
          />
          <AudiencePicker
            kind="members"
            rows={memberRows}
            selected={memberIds}
            setSelected={setMemberIds}
            max={100}
            disabled={pending}
            loading={members.isPending}
            error={!!members.error}
            hasMore={!!members.hasNextPage}
            loadingMore={members.isFetchingNextPage}
            loadMore={() => void members.fetchNextPage()}
            retry={() => void members.refetch()}
          />
        </>
      )}
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
      {saved && (
        <p role="status" className="text-sm">
          {t("policySaved")}
        </p>
      )}
      <Button
        loading={pending}
        disabled={!complete}
        onClick={() =>
          save({
            generation: policy.authorization_generation,
            mode,
            agent_ids: mode === "shared" ? [...new Set(agentIds)] : [],
            member_ids: mode === "shared" ? [...new Set(memberIds)] : [],
          })
        }
      >
        {t("savePolicy")}
      </Button>
    </div>
  );
}

function AudiencePicker({
  kind,
  rows,
  selected,
  setSelected,
  max,
  disabled,
  loading,
  error,
  hasMore,
  loadingMore,
  loadMore,
  retry,
}: {
  kind: "agents" | "members";
  rows: { id: string; name: string }[];
  selected: string[];
  setSelected: (ids: string[]) => void;
  max: number;
  disabled: boolean;
  loading: boolean;
  error: boolean;
  hasMore: boolean;
  loadingMore: boolean;
  loadMore: () => void;
  retry: () => void;
}) {
  const t = useTranslations("browserCredentials");
  const unique = [...new Map(rows.map((row) => [row.id, row])).values()];
  const missing = selected.filter((id) => !unique.some((row) => row.id === id));
  const choices = [
    ...missing.map((id) => ({ id, name: t("selectedUnavailable", { id }) })),
    ...unique,
  ];
  return (
    <fieldset className="space-y-2 rounded-lg border p-3" disabled={disabled}>
      <legend className="px-1 text-sm font-medium">{t(kind)}</legend>
      {loading && <p role="status">{t("loadingChoices")}</p>}
      {error && (
        <div role="alert" className="space-y-2">
          <p>{t("choicesUnavailable")}</p>
          <Button variant="outline" onClick={retry}>
            {t("checkAgain")}
          </Button>
        </div>
      )}
      <div className="max-h-60 space-y-2 overflow-y-auto">
        {choices.map((row) => {
          const checked = selected.includes(row.id);
          return (
            <div className="flex items-center gap-2" key={row.id}>
              <Checkbox
                id={`browser-policy-${kind}-${row.id}`}
                checked={checked}
                disabled={disabled || (!checked && selected.length >= max)}
                onCheckedChange={(value) =>
                  setSelected(
                    value === true
                      ? [...new Set([...selected, row.id])]
                      : selected.filter((id) => id !== row.id),
                  )
                }
              />
              <Label className="min-w-0 break-words" htmlFor={`browser-policy-${kind}-${row.id}`}>
                {row.name}
              </Label>
            </div>
          );
        })}
      </div>
      {!loading && !error && choices.length === 0 && (
        <p className="text-muted-foreground text-xs">{t("noChoices")}</p>
      )}
      {hasMore && (
        <Button variant="outline" loading={loadingMore} onClick={loadMore}>
          {t("loadMore")}
        </Button>
      )}
      <p className="text-muted-foreground text-xs">
        {t("selectionCount", { count: selected.length, max })}
      </p>
    </fieldset>
  );
}
