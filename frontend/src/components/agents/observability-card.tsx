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
import { useSecrets } from "@/hooks";
import type { ObservabilitySpec } from "@/types/agents";

/** The one kind of secret a Logfire write token can be stored as. */
const TOKEN_KIND = "api_key";

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
  const { secrets } = useSecrets();
  const tokens = secrets.filter((secret) => secret.kind === TOKEN_KIND);
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
        <CardTitle>Tracing</CardTitle>
        <CardDescription>
          Send this agent&apos;s runs to a Logfire project of its own - an agent built for a client
          traces into the client&apos;s project rather than yours. Leave it empty and runs go where
          the deployment already sends everything.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-3">
        <div className="space-y-2">
          <Label htmlFor="logfire-token">Write token</Label>
          <Select
            value={tokens.find((secret) => secret.id === selected)?.id ?? NONE}
            disabled={disabled}
            onValueChange={(secretId) =>
              update({ token_secret_id: secretId === NONE ? null : secretId })
            }
          >
            <SelectTrigger id="logfire-token">
              <SelectValue placeholder="The deployment's project" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>The deployment&apos;s project</SelectItem>
              {tokens.map((secret) => (
                <SelectItem key={secret.id} value={secret.id}>
                  {secret.name} <span className="font-mono">····{secret.hint}</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-muted-foreground text-xs">
            Stored in the vault as an API key. The spec keeps the reference, never the token.
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="logfire-service">Service name</Label>
          <Input
            id="logfire-service"
            value={value?.service_name ?? ""}
            disabled={disabled || selected === null}
            placeholder={agentName}
            onChange={(event) => update({ service_name: event.target.value || null })}
          />
          <p className="text-muted-foreground text-xs">What the agent is called in Logfire.</p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="logfire-environment">Environment</Label>
          <Input
            id="logfire-environment"
            value={value?.environment ?? ""}
            disabled={disabled || selected === null}
            placeholder="production"
            onChange={(event) => update({ environment: event.target.value || null })}
          />
          <p className="text-muted-foreground text-xs">
            Separates staging traffic from the real thing in the same project.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
