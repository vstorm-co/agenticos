"use client";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { InlineSecret } from "@/components/vault/inline-secret";
import { ProviderRow } from "@/components/vault/provider-row";
import { useSecrets } from "@/hooks";
import type { ObservabilitySpec } from "@/types/agents";
import { useTranslations } from "next-intl";

/**
 * The vault purpose a Logfire write token is stored under. Offering only these
 * keeps every Tavily and provider key out of a picker where each would be a
 * plausible-looking wrong answer.
 */
const TOKEN_PURPOSE = "logfire";

/** Chosen in the picker to mean "back to the deployment's own project". */
const NONE = "__none__";

interface ObservabilityCardProps {
  value: ObservabilitySpec | null | undefined;
  onChange: (next: ObservabilitySpec | null) => void;
  disabled?: boolean;
  /** Placeholder for the service name, which defaults to the agent's name. */
  agentName: string;
}

/**
 * Where this agent's traces go.
 *
 * Empty by default, and that is the normal state: the deployment configures
 * Logfire once and every run lands there. This exists for the agent built for
 * somebody else - whose traces belong in *their* project, with their retention
 * and their alerting, and none of the operator's other traffic in it.
 *
 * The token is picked from the vault rather than typed. A spec is exported as
 * YAML into a client's repository, so it carries the id of a secret and never
 * the secret; the same rule every capability credential follows.
 */
export function ObservabilityCard({
  value,
  onChange,
  disabled,
  agentName,
}: ObservabilityCardProps) {
  const t = useTranslations("agents");
  const { secrets } = useSecrets();
  const tokens = secrets.filter((secret) => secret.purpose === TOKEN_PURPOSE);
  const selected = value?.token_secret_id ?? null;

  // Clearing the token clears the block: a service name and environment with
  // nowhere to send are three stored fields that do nothing, and they read on
  // the next edit as though tracing were configured.
  const update = (patch: Partial<ObservabilitySpec>) => {
    const next = { ...(value ?? {}), ...patch };
    onChange(next.token_secret_id ? next : null);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("tracing")}</CardTitle>
        <CardDescription>{t("everyRunAlreadyTraced")}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-3">
        <div className="space-y-2">
          <Label htmlFor="logfire-token">{t("writeToken")}</Label>
          <Select
            value={tokens.find((secret) => secret.id === selected)?.id ?? NONE}
            disabled={disabled}
            onValueChange={(secretId) =>
              update({ token_secret_id: secretId === NONE ? null : secretId })
            }
          >
            <SelectTrigger id="logfire-token">
              <SelectValue placeholder={t("deploymentSProject")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>{t("deploymentSProject")}</SelectItem>
              {tokens.map((secret) => (
                <SelectItem key={secret.id} value={secret.id} textValue={secret.name}>
                  {/* Every token here is a Logfire token by construction - that
                      is the filter above - so the mark is the constant, not a
                      lookup. Logfire has no mark compiled in; the monogram is
                      the floor, and the row still reads like the others. */}
                  <ProviderRow provider={TOKEN_PURPOSE} name={secret.name} hint={secret.hint} />
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-muted-foreground text-xs">{t("storedVaultUnderTracing")}</p>
          {/* Here rather than as a sentence pointing at the Vault: the answer to
              "no tokens stored yet" is a form, and a picker with nothing in it and
              nowhere to go is a dead end. */}
          <InlineSecret
            kind="api_key"
            purpose={TOKEN_PURPOSE}
            suggestedName={t("logfireTokenName")}
            helpUrl="https://logfire.pydantic.dev/docs/how-to-guides/create-write-tokens/"
            disabled={disabled}
            onCreated={(secretId) => update({ token_secret_id: secretId })}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="logfire-service">{t("serviceName")}</Label>
          <Input
            id="logfire-service"
            value={value?.service_name ?? ""}
            disabled={disabled || selected === null}
            placeholder={agentName}
            onChange={(event) => update({ service_name: event.target.value || null })}
          />
          <p className="text-muted-foreground text-xs">{t("whatAgentCalledLogfire")}</p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="logfire-environment">{t("environment")}</Label>
          <Input
            id="logfire-environment"
            value={value?.environment ?? ""}
            disabled={disabled || selected === null}
            placeholder={t("production")}
            onChange={(event) => update({ environment: event.target.value || null })}
          />
          <p className="text-muted-foreground text-xs">{t("separatesStagingTrafficFrom")}</p>
        </div>
      </CardContent>
    </Card>
  );
}
