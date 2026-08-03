"use client";

import { useState } from "react";

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
import type { SandboxRuntime } from "@/lib/sandbox-connections-api";

interface RuntimeFieldProps {
  value: string;
  onChange: (alias: string) => void;
  /** What the service said it accepts, or null before anybody asked it. */
  runtimes: SandboxRuntime[] | null;
  /** Ask the service. Absent when there is nothing to ask with yet. */
  onTest: (() => Promise<void>) | null;
  testing: boolean;
}

/** The empty option's value. A `Select` cannot hold `""`, but it can hold this. */
const SERVICE_DEFAULT = "__service__";

/**
 * Which image an agent gets when its own spec names none.
 *
 * A list once the service has been asked, and free text before that — because the
 * aliases are the service's own configuration and there is no way to know them
 * without asking it. Free text alone is what this replaces: a typo there is stored
 * happily, and refused at the first tool call inside somebody's conversation,
 * where the person who can fix it is not the one reading the error.
 *
 * The free-text field stays reachable even with a list, and that is not
 * indecision. The list is a snapshot: an operator who has just added an alias to
 * the service's configuration and not yet restarted it is describing something
 * true that this cannot see yet.
 */
export function RuntimeField({ value, onChange, runtimes, onTest, testing }: RuntimeFieldProps) {
  const [typing, setTyping] = useState(false);
  const listed = runtimes !== null && runtimes.length > 0;
  const known = listed && runtimes.some((runtime) => runtime.alias === value);

  return (
    <div className="space-y-2">
      <Label htmlFor="connection-runtime">Default runtime</Label>

      {listed && !typing ? (
        <Select
          value={value === "" ? SERVICE_DEFAULT : value}
          onValueChange={(alias) => onChange(alias === SERVICE_DEFAULT ? "" : alias)}
        >
          <SelectTrigger id="connection-runtime">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={SERVICE_DEFAULT}>Whatever the service defaults to</SelectItem>
            {runtimes.map((runtime) => (
              <SelectItem key={runtime.alias} value={runtime.alias}>
                {runtime.alias}
                {runtime.description ? ` — ${runtime.description}` : ""}
              </SelectItem>
            ))}
            {/* An alias the form is already carrying but the service did not
                name. Kept in the list rather than dropped: silently clearing a
                stored value while somebody edits an unrelated field is how a
                connection changes runtime without anybody deciding to. */}
            {value !== "" && !known && <SelectItem value={value}>{value}</SelectItem>}
          </SelectContent>
        </Select>
      ) : (
        <Input
          id="connection-runtime"
          value={value}
          placeholder="the service's own"
          onChange={(event) => onChange(event.target.value)}
        />
      )}

      <p className="text-muted-foreground text-xs">
        The image alias an agent gets when its own spec names none. Leave empty to take whatever the
        service defaults to.
      </p>

      <div className="flex items-center gap-3">
        {onTest !== null && (
          <Button variant="outline" size="sm" onClick={() => void onTest()} disabled={testing}>
            {testing ? "Asking the service…" : listed ? "Ask again" : "Test and list runtimes"}
          </Button>
        )}
        {listed && (
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground text-xs underline"
            onClick={() => setTyping(!typing)}
          >
            {typing ? "Pick from the list" : "Type an alias instead"}
          </button>
        )}
      </div>
    </div>
  );
}
