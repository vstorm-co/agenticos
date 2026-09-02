"use client";

import { useState } from "react";
import { Building2, User } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Switch,
} from "@/components/ui";
import { cn } from "@/lib/utils";
import {
  SCOPE_LABEL,
  type ConnectionFormValues,
  type DraftAuth,
  type DraftState,
  type Scope,
} from "@/components/mcp/mcp-server-list-types";
import { DIALOG_FORM } from "@/lib/dialog-sizes";

const AUTH_CHOICES: { value: DraftAuth; labelKey: string; hintKey: string }[] = [
  { value: "none", labelKey: "authChoiceNone", hintKey: "authNoneHint" },
  { value: "token", labelKey: "authApiToken", hintKey: "authTokenHint" },
  { value: "oauth", labelKey: "authOauth", hintKey: "authOauthHint" },
];

/** How the dialog's fields start, read off the row and any connection being edited. */
function initialAuth(draft: DraftState): DraftAuth {
  if (draft.existing?.auth_type === "oauth") return "oauth";
  if (draft.row.entry?.auth === "oauth") return "oauth";
  if (draft.row.entry?.auth === "none") return "none";
  return "token";
}

interface McpConnectionDialogProps {
  draft: DraftState | null;
  onClose: () => void;
  submitting: boolean;
  canManageOrganization: boolean;
  onSubmit: (values: ConnectionFormValues) => void;
}

/**
 * Connect or edit one MCP server.
 *
 * The form fields live here rather than in the list: the list opens the dialog
 * with a `DraftState` (the row, and the connection if editing) and reads back a
 * `ConnectionFormValues` on submit. The inner form is keyed on the draft, so
 * switching from one server to another remounts it with fresh seeded state
 * rather than carrying the last one's name and token across.
 */
export function McpConnectionDialog({
  draft,
  onClose,
  submitting,
  canManageOrganization,
  onSubmit,
}: McpConnectionDialogProps) {
  return (
    <Dialog open={draft !== null} onOpenChange={(open) => !open && !submitting && onClose()}>
      <DialogContent className={DIALOG_FORM}>
        {draft !== null && (
          <ConnectionForm
            key={draft.existing?.id ?? draft.row.key}
            draft={draft}
            submitting={submitting}
            canManageOrganization={canManageOrganization}
            onCancel={onClose}
            onSubmit={onSubmit}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function ConnectionForm({
  draft,
  submitting,
  canManageOrganization,
  onCancel,
  onSubmit,
}: {
  draft: DraftState;
  submitting: boolean;
  canManageOrganization: boolean;
  onCancel: () => void;
  onSubmit: (values: ConnectionFormValues) => void;
}) {
  const t = useTranslations("mcp");
  const [label, setLabel] = useState(draft.existing?.label ?? "");
  const [name, setName] = useState(
    draft.existing?.name ?? draft.suggestedName ?? draft.row.entry?.key ?? "",
  );
  const [url, setUrl] = useState(draft.existing?.url ?? draft.row.entry?.url ?? "");
  const [token, setToken] = useState("");
  const [auth, setAuth] = useState<DraftAuth>(() => initialAuth(draft));
  const [clearToken, setClearToken] = useState(false);
  const [scope, setScope] = useState<Scope>(draft.scope);

  // The hint under the radio group. It used to be rendered as the *key* -
  // `authTokenHint` on screen, in every locale (#446).
  const hint = AUTH_CHOICES.find((choice) => choice.value === auth)?.hintKey;

  return (
    <>
      <DialogHeader>
        <DialogTitle>
          {draft.existing
            ? t("editNamed", { name: draft.existing.name })
            : t("connectForScope", { name: draft.row.name, scope })}
        </DialogTitle>
      </DialogHeader>
      <div className="space-y-4" data-tour="mcp-dialog-form">
        {/* First, because it is the field a person is actually choosing. The
            slug below it is a technical name with a constraint to explain, and
            leading with that is what left two Notion accounts called `notion`
            and `notion-2`. */}
        <div>
          <Label htmlFor="mcp-label">{t("displayName")}</Label>
          <Input
            id="mcp-label"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            placeholder={t("displayNamePlaceholder")}
            maxLength={64}
            className="mt-1.5"
          />
          <p className="text-foreground/45 mt-1 text-[11px]">{t("displayNameHint")}</p>
        </div>
        <div>
          <Label htmlFor="mcp-name">{t("name")}</Label>
          <Input
            id="mcp-name"
            value={name}
            onChange={(event) => setName(event.target.value.toLowerCase())}
            placeholder={t("github")}
            maxLength={32}
            className="mt-1.5"
          />
          <p className="text-foreground/45 mt-1 text-[11px]">
            {t("namePrefixesToolNames", { scope })}
          </p>
        </div>
        <div>
          <Label htmlFor="mcp-url">{t("serverUrl")}</Label>
          <Input
            id="mcp-url"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://example.com/mcp"
            maxLength={2048}
            className="mt-1.5 font-mono text-sm"
          />
        </div>
        <div>
          <Label>{t("connectAction")}</Label>
          <div
            className="mt-1.5 flex flex-wrap gap-1.5"
            role="radiogroup"
            aria-label={t("connect2")}
          >
            {(["organization", "personal"] as const)
              .filter((option) => option !== "organization" || canManageOrganization)
              .map((option) => {
                const Icon = option === "organization" ? Building2 : User;
                return (
                  <button
                    key={option}
                    type="button"
                    role="radio"
                    aria-checked={scope === option}
                    disabled={draft.existing !== null}
                    onClick={() => setScope(option)}
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm transition-colors",
                      scope === option
                        ? "border-foreground/30 bg-accent text-foreground"
                        : "border-input text-muted-foreground hover:text-foreground",
                      draft.existing !== null && "cursor-not-allowed opacity-60",
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" />
                    {t(SCOPE_LABEL[option])}
                  </button>
                );
              })}
          </div>
          <p className="text-muted-foreground mt-1.5 text-xs">
            {scope === "organization" ? t("everyAgentCanReach") : t("yoursAloneYourOwn")}
          </p>
          {draft.existing !== null && (
            // Moving a live connection between owners would mean re-sealing
            // its credential under another envelope and changing who may
            // revoke it. Disconnect and connect again is the honest path.
            <p className="text-muted-foreground mt-1 text-xs">
              {t("existingConnectionCannotChange")}
            </p>
          )}
        </div>

        <div>
          <Label>{t("authentication")}</Label>
          <div
            className="mt-1.5 flex flex-wrap gap-1.5"
            role="radiogroup"
            aria-label={t("authentication2")}
          >
            {AUTH_CHOICES.map((choice) => (
              <button
                key={choice.value}
                type="button"
                role="radio"
                aria-checked={auth === choice.value}
                onClick={() => setAuth(choice.value)}
                className={cn(
                  "rounded-md border px-3 py-1.5 text-sm transition-colors",
                  auth === choice.value
                    ? "border-foreground/30 bg-accent text-foreground"
                    : "border-input text-muted-foreground hover:text-foreground",
                )}
              >
                {t(choice.labelKey)}
              </button>
            ))}
          </div>
          <p className="text-muted-foreground mt-1.5 text-xs">
            {hint === undefined ? null : t(hint)}
          </p>
          {auth === "oauth" && scope === "organization" && (
            // Said once, where the choice is made. The grant is the
            // consenting person's at the provider, so revoking their access
            // there stops the organization's server working until somebody
            // authorizes it again - which is why a shared service account is
            // the right thing to consent with.
            <p className="text-muted-foreground mt-1.5 text-xs">{t("whoeverSignsGrantsIf")}</p>
          )}
        </div>

        <div className={cn(auth !== "token" && "hidden")}>
          <Label htmlFor="mcp-token">{t("accessToken")}</Label>
          {/* The catalog's own advice for *this* server, which used to sit on
              the card. It is instructions for filling in the field below it,
              so it belongs next to the field and not in a list somebody is
              still browsing. Generic guidance is the main reason token setup
              fails, which is why the backend carries a per-entry hint. */}
          {draft.row.tokenHint && (
            <p className="text-muted-foreground mt-1.5 text-xs">{draft.row.tokenHint}</p>
          )}
          <Input
            id="mcp-token"
            type="password"
            value={token}
            onChange={(event) => {
              setToken(event.target.value);
              if (event.target.value) setClearToken(false);
            }}
            placeholder={
              draft.existing?.has_auth_token ? "•••••• (stored - type to replace)" : t("pasteHere")
            }
            maxLength={4096}
            className="mt-1.5 font-mono text-sm"
          />
          <p className="text-foreground/45 mt-1 text-[11px]">
            {scope === "organization"
              ? t("useServiceCredentialNot")
              : t("storedEncryptedNeverShown")}
          </p>
          {draft.existing?.has_auth_token && !token && (
            <div className="mt-2 flex items-center gap-2">
              <Switch id="mcp-clear-token" checked={clearToken} onCheckedChange={setClearToken} />
              <Label htmlFor="mcp-clear-token" className="text-xs font-normal">
                {t("removeStoredCredential")}
              </Label>
            </div>
          )}
        </div>
      </div>
      <DialogFooter>
        <Button variant="ghost" onClick={onCancel} disabled={submitting}>
          {t("cancel")}
        </Button>
        <Button
          onClick={() => onSubmit({ label, name, url, token, auth, clearToken, scope })}
          disabled={submitting}
          data-tour="mcp-dialog-connect"
        >
          {submitting ? t("saving") : draft.existing ? t("save") : t("connectCheck")}
        </Button>
      </DialogFooter>
    </>
  );
}
