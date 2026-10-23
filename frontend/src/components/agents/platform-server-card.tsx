"use client";

import { useState } from "react";
import { ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";

import { BrandMark } from "@/components/branding/brand-mark";
import { useBranding } from "@/components/branding/branding-provider";
import { CardStatus, McpServerCard } from "@/components/mcp/mcp-server-card";
import { ErrorState } from "@/components/states";
import {
  Badge,
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Label,
  Skeleton,
  Switch,
} from "@/components/ui";
import { usePlatformMcpTools } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type { McpApproval, PlatformMcpServerRef } from "@/types/agents";

/** What a new binding starts as: every tool, and every one that changes something held. */
export const NEW_PLATFORM_BINDING: PlatformMcpServerRef = {
  account: "platform",
  allowed_tools: null,
  approval: "writes",
};

/**
 * This deployment's own MCP server, first in the Builder's gallery (#2190).
 *
 * It needs no connection - it is the platform - and its tools act as whoever the
 * agent runs for, so the card says that rather than whose account it uses. Writes
 * wait for approval from the moment it is switched on; `none` is not offered,
 * because the server holds it to `writes` anyway.
 */
export function PlatformServerCard({
  binding,
  onChange,
  disabled,
}: {
  binding: PlatformMcpServerRef | null;
  onChange: (next: PlatformMcpServerRef | null) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("agents");
  const { appName } = useBranding();
  const [open, setOpen] = useState(false);
  const isOn = binding !== null;

  return (
    <>
      <McpServerCard
        name={appName}
        icon={null}
        mark={<BrandMark size={24} />}
        url={null}
        description={t("platformServerDescription")}
        badge={<Badge variant="outline">{t("platformServerBadge")}</Badge>}
        headerAction={
          <Switch
            checked={isOn}
            disabled={disabled}
            onCheckedChange={(on) => {
              onChange(on ? NEW_PLATFORM_BINDING : null);
              if (on) setOpen(true);
            }}
            aria-label={t("useServerInAgent", { name: appName })}
          />
        }
        status={
          <CardStatus
            tone={isOn ? "live" : "off"}
            onClick={disabled ? undefined : () => setOpen(true)}
            label={t("serverSettingsNamed", { name: appName })}
          >
            {isOn
              ? binding.approval === "all"
                ? t("platformAsksEveryCall")
                : t("platformAsksBeforeWrites")
              : t("platformAsWhoeverAsks")}
          </CardStatus>
        }
        selected={isOn}
        onOpen={disabled ? undefined : () => setOpen(true)}
        dataTour="agent-platform-mcp"
      />
      {/* Mounted only while open: its tool list is a request, and a gallery of
          closed cards should not make one. */}
      {open && (
        <PlatformBindingDialog
          onOpenChange={setOpen}
          name={appName}
          binding={binding}
          onChange={onChange}
          disabled={disabled}
        />
      )}
    </>
  );
}

function PlatformBindingDialog({
  onOpenChange,
  name,
  binding,
  onChange,
  disabled,
}: {
  onOpenChange: (open: boolean) => void;
  name: string;
  binding: PlatformMcpServerRef | null;
  onChange: (next: PlatformMcpServerRef | null) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("agents");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const { tools, isLoading, error } = usePlatformMcpTools();
  const current = binding ?? NEW_PLATFORM_BINDING;
  const allowed = current.allowed_tools ?? null;
  const isAllowed = (tool: string) => allowed === null || allowed.includes(tool);

  const setTool = (tool: string, on: boolean) => {
    const base = allowed ?? tools.map((entry) => entry.name);
    const next = on ? [...base, tool] : base.filter((name) => name !== tool);
    // Every tool chosen is "no limit", so a tool added to the server later is
    // offered to an agent whose author never narrowed the list.
    const everything = tools.every((entry) => next.includes(entry.name));
    onChange({ ...current, allowed_tools: everything ? null : next });
  };
  const setApproval = (approval: McpApproval) => onChange({ ...current, approval });

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className={cn(DIALOG_FORM, DIALOG_SCROLL)}>
        <DialogHeader>
          <DialogTitle>{name}</DialogTitle>
          <DialogDescription>{t("platformServerDescription")}</DialogDescription>
        </DialogHeader>

        <p className="bg-muted text-muted-foreground flex items-start gap-2 rounded-lg p-3 text-sm">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          {t("platformActsAsWhoeverAsks")}
        </p>

        {binding === null ? (
          <Button onClick={() => onChange(NEW_PLATFORM_BINDING)} disabled={disabled}>
            {t("platformUseIt")}
          </Button>
        ) : (
          <>
            <div className="space-y-2">
              <p id="platform-approval" className="text-sm font-medium">
                {t("platformApproval")}
              </p>
              <div role="radiogroup" aria-labelledby="platform-approval" className="space-y-1.5">
                {(["writes", "all"] as const).map((mode) => {
                  const chosen = (current.approval ?? "writes") === mode;
                  return (
                    <button
                      key={mode}
                      type="button"
                      role="radio"
                      aria-checked={chosen}
                      onClick={() => setApproval(mode)}
                      disabled={disabled}
                      className={cn(
                        "w-full rounded-lg border px-3 py-2 text-left text-sm transition-colors",
                        chosen ? "border-foreground/40 bg-accent" : "hover:bg-accent/60",
                      )}
                    >
                      <span className="block font-medium">
                        {mode === "writes"
                          ? t("platformAsksBeforeWrites")
                          : t("platformAsksEveryCall")}
                      </span>
                      <span className="text-muted-foreground block text-xs">
                        {mode === "writes" ? t("platformWritesHint") : t("platformAllHint")}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="space-y-2">
              <Label>{t("platformTools")}</Label>
              {error ? (
                // A request that failed is said, never drawn as a server with no tools.
                <ErrorState description={getErrorMessage(error, tErrors)} className="py-6" />
              ) : isLoading ? (
                <Skeleton className="h-32 w-full" />
              ) : (
                <ul className="divide-border divide-y rounded-lg border">
                  {tools.map((tool) => (
                    <li key={tool.name} className="flex items-start gap-3 px-3 py-2">
                      <Checkbox
                        id={`platform-tool-${tool.name}`}
                        checked={isAllowed(tool.name)}
                        onCheckedChange={(on) => setTool(tool.name, on === true)}
                        disabled={disabled}
                        className="mt-0.5"
                      />
                      <label htmlFor={`platform-tool-${tool.name}`} className="min-w-0 flex-1">
                        <span className="flex items-center gap-2">
                          <span className="font-mono text-xs">{tool.name}</span>
                          {tool.writes ? (
                            <Badge variant="outline">
                              {tool.ungated ? t("platformUngatedBadge") : t("platformWritesBadge")}
                            </Badge>
                          ) : (
                            tool.held && <Badge variant="outline">{t("platformHeldBadge")}</Badge>
                          )}
                        </span>
                        <span className="text-muted-foreground block text-xs">
                          {tool.description}
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </>
        )}

        <DialogFooter>
          {binding !== null && (
            <Button
              variant="outline"
              className="mr-auto"
              onClick={() => {
                onChange(null);
                onOpenChange(false);
              }}
              disabled={disabled}
            >
              {t("platformRemove")}
            </Button>
          )}
          <Button onClick={() => onOpenChange(false)}>{tc("done")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
