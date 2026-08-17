"use client";

import type { Dispatch, SetStateAction } from "react";
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
  type DraftAuth,
  type DraftState,
} from "@/components/mcp/mcp-server-list-types";

const AUTH_CHOICES: { value: DraftAuth; labelKey: string; hintKey: string }[] = [
  { value: "none", labelKey: "authChoiceNone", hintKey: "authNoneHint" },
  { value: "token", labelKey: "authApiToken", hintKey: "authTokenHint" },
  { value: "oauth", labelKey: "authOauth", hintKey: "authOauthHint" },
];

interface McpConnectionDialogProps {
  draft: DraftState | null;
  setDraft: Dispatch<SetStateAction<DraftState | null>>;
  draftName: string;
  setDraftName: Dispatch<SetStateAction<string>>;
  draftUrl: string;
  setDraftUrl: Dispatch<SetStateAction<string>>;
  draftToken: string;
  setDraftToken: Dispatch<SetStateAction<string>>;
  draftAuth: DraftAuth;
  setDraftAuth: Dispatch<SetStateAction<DraftAuth>>;
  clearToken: boolean;
  setClearToken: Dispatch<SetStateAction<boolean>>;
  submitting: boolean;
  canManageOrganization: boolean;
  onSubmit: () => void;
}

export function McpConnectionDialog({
  draft,
  setDraft,
  draftName,
  setDraftName,
  draftUrl,
  setDraftUrl,
  draftToken,
  setDraftToken,
  draftAuth,
  setDraftAuth,
  clearToken,
  setClearToken,
  submitting,
  canManageOrganization,
  onSubmit,
}: McpConnectionDialogProps) {
  const t = useTranslations("mcp");
  // The hint under the radio group. It used to be rendered as the *key* -
  // `authTokenHint` on screen, in every locale (#446).
  const hint = AUTH_CHOICES.find((choice) => choice.value === draftAuth)?.hintKey;

  return (
    <Dialog open={draft !== null} onOpenChange={(open) => !open && !submitting && setDraft(null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {draft === null
              ? ""
              : draft.existing
                ? t("editNamed", { name: draft.existing.name })
                : t("connectForScope", { name: draft.row.name, scope: draft.scope })}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label htmlFor="mcp-name">{t("name")}</Label>
            <Input
              id="mcp-name"
              value={draftName}
              onChange={(event) => setDraftName(event.target.value.toLowerCase())}
              placeholder={t("github")}
              maxLength={32}
              className="mt-1.5"
            />
            <p className="text-foreground/45 mt-1 text-[11px]">
              {t("namePrefixesToolNames", { scope: draft?.scope ?? "personal" })}
            </p>
          </div>
          <div>
            <Label htmlFor="mcp-url">{t("serverUrl")}</Label>
            <Input
              id="mcp-url"
              value={draftUrl}
              onChange={(event) => setDraftUrl(event.target.value)}
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
                .filter((scope) => scope !== "organization" || canManageOrganization)
                .map((scope) => {
                  const Icon = scope === "organization" ? Building2 : User;
                  return (
                    <button
                      key={scope}
                      type="button"
                      role="radio"
                      aria-checked={draft?.scope === scope}
                      disabled={draft?.existing !== null}
                      onClick={() =>
                        setDraft((previous) => (previous ? { ...previous, scope } : previous))
                      }
                      className={cn(
                        "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm transition-colors",
                        draft?.scope === scope
                          ? "border-foreground/30 bg-accent text-foreground"
                          : "border-input text-muted-foreground hover:text-foreground",
                        draft?.existing !== null && "cursor-not-allowed opacity-60",
                      )}
                    >
                      <Icon className="h-3.5 w-3.5" />
                      {t(SCOPE_LABEL[scope])}
                    </button>
                  );
                })}
            </div>
            <p className="text-muted-foreground mt-1.5 text-xs">
              {draft?.scope === "organization" ? t("everyAgentCanReach") : t("yoursAloneYourOwn")}
            </p>
            {draft?.existing !== null && (
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
                  aria-checked={draftAuth === choice.value}
                  onClick={() => setDraftAuth(choice.value)}
                  className={cn(
                    "rounded-md border px-3 py-1.5 text-sm transition-colors",
                    draftAuth === choice.value
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
            {draftAuth === "oauth" && draft?.scope === "organization" && (
              // Said once, where the choice is made. The grant is the
              // consenting person's at the provider, so revoking their access
              // there stops the organization's server working until somebody
              // authorizes it again - which is why a shared service account is
              // the right thing to consent with.
              <p className="text-muted-foreground mt-1.5 text-xs">{t("whoeverSignsGrantsIf")}</p>
            )}
          </div>

          <div className={cn(draftAuth !== "token" && "hidden")}>
            <Label htmlFor="mcp-token">{t("accessToken")}</Label>
            {/* The catalog's own advice for *this* server, which used to sit on
                the card. It is instructions for filling in the field below it,
                so it belongs next to the field and not in a list somebody is
                still browsing. Generic guidance is the main reason token setup
                fails, which is why the backend carries a per-entry hint. */}
            {draft?.row.tokenHint && (
              <p className="text-muted-foreground mt-1.5 text-xs">{draft.row.tokenHint}</p>
            )}
            <Input
              id="mcp-token"
              type="password"
              value={draftToken}
              onChange={(event) => {
                setDraftToken(event.target.value);
                if (event.target.value) setClearToken(false);
              }}
              placeholder={
                draft?.existing?.has_auth_token
                  ? "•••••• (stored - type to replace)"
                  : t("pasteHere")
              }
              maxLength={4096}
              className="mt-1.5 font-mono text-sm"
            />
            <p className="text-foreground/45 mt-1 text-[11px]">
              {draft?.scope === "organization"
                ? t("useServiceCredentialNot")
                : t("storedEncryptedNeverShown")}
            </p>
            {draft?.existing?.has_auth_token && !draftToken && (
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
          <Button variant="ghost" onClick={() => setDraft(null)} disabled={submitting}>
            {t("cancel")}
          </Button>
          <Button onClick={onSubmit} disabled={submitting}>
            {submitting ? t("saving") : draft?.existing ? t("save") : t("connectCheck")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
