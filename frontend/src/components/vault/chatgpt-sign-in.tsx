"use client";

import { useState } from "react";
import { ExternalLink, LogIn } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button, FormField, Input } from "@/components/ui";
import { useChatGPTSignIn, usePermissions } from "@/hooks";
import { getErrorMessage, submitFailure } from "@/lib/api-error";
import { useAuthStore } from "@/stores";
import { Perm } from "@/types/permissions";

interface ChatGPTSignInStepsProps {
  /** The pasted address, owned by the form that submits it. */
  callbackUrl: string;
  onCallbackUrlChange: (value: string) => void;
  error?: string;
  disabled?: boolean;
  idPrefix: string;
}

/**
 * The two steps of a ChatGPT sign-in: open it, then paste back where it ended.
 *
 * ChatGPT redirects only to `localhost:1455`, so on any deployment but a laptop
 * the sign-in ends on an address that does not load - which is the address this
 * asks for. Saying so up front is the whole design: a person who is not told
 * expects the page to load, and closes the tab that holds the code.
 *
 * The tab is opened inside the click and pointed at ChatGPT once the server has
 * minted the sign-in. Opened after the request instead, a popup blocker eats it;
 * the link that stays behind is for when one does anyway.
 */
export function ChatGPTSignInSteps({
  callbackUrl,
  onCallbackUrlChange,
  error,
  disabled,
  idPrefix,
}: ChatGPTSignInStepsProps) {
  const t = useTranslations("vault");
  const tErrors = useTranslations("errors");
  const { start } = useChatGPTSignIn();
  const [authorizationUrl, setAuthorizationUrl] = useState<string | null>(null);

  function begin() {
    const tab = window.open("", "_blank");
    start.mutate(undefined, {
      onSuccess: ({ authorization_url }) => {
        setAuthorizationUrl(authorization_url);
        if (tab) {
          tab.opener = null;
          tab.location.href = authorization_url;
        }
      },
      onError: (failure) => {
        tab?.close();
        toast.error(getErrorMessage(failure, tErrors));
      },
    });
  }

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <p className="text-muted-foreground text-xs">{t("chatgptStepOne")}</p>
        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled || start.isPending}
            onClick={begin}
          >
            <LogIn className="h-3.5 w-3.5" />
            {t("chatgptSignIn")}
          </Button>
          {authorizationUrl && (
            <a
              href={authorizationUrl}
              target="_blank"
              rel="noreferrer noopener"
              className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs underline underline-offset-4"
            >
              <ExternalLink className="h-3 w-3" aria-hidden />
              {t("chatgptOpenAgain")}
            </a>
          )}
        </div>
      </div>

      <FormField
        label={t("chatgptCallbackLabel")}
        htmlFor={`${idPrefix}-callback-url`}
        error={error}
        description={t("chatgptStepTwo")}
      >
        <Input
          value={callbackUrl}
          onChange={(event) => onCallbackUrlChange(event.target.value)}
          // i18n-exempt: an example address, the same in every language
          placeholder="http://localhost:1455/auth/callback?code=…"
          autoComplete="off"
          disabled={disabled}
          className="font-mono"
        />
      </FormField>
    </div>
  );
}

interface InlineChatGPTSignInProps {
  /** What the stored sign-in is called. */
  suggestedName: string;
  /** Called with the new secret's id once it is stored. */
  onCreated: (secretId: string) => void;
  disabled?: boolean;
}

/**
 * `InlineSecret` for the one provider whose credential nobody types. The
 * server records every sign-in under the `openai_codex` purpose, so a model
 * picker filtering keys by provider finds it without being told.
 *
 * Stored private: it is somebody's own subscription, and an organization-wide
 * sign-in would let every agent here spend it. Checks `secrets:edit` itself for
 * the reason `InlineSecret` does - the permission belongs to the write.
 */
export function InlineChatGPTSignIn({
  suggestedName,
  onCreated,
  disabled,
}: InlineChatGPTSignInProps) {
  const t = useTranslations("vault");
  const tErrors = useTranslations("errors");
  const { create } = useChatGPTSignIn();
  const { can } = usePermissions();
  const [callbackUrl, setCallbackUrl] = useState("");
  const [error, setError] = useState<string | undefined>(undefined);
  // Named for whose it is: a secret's name is unique across the organization,
  // so the second person signing in under the bare suggestion was refused, with
  // no field here to choose another.
  const user = useAuthStore((state) => state.user);
  const person = user?.full_name || user?.email;
  const name = person ? t("chatgptNameOf", { name: suggestedName, person }) : suggestedName;

  if (!can(Perm.secretsEdit)) {
    return <p className="text-muted-foreground text-xs">{t("storingNeedsPermission")}</p>;
  }

  const submit = () => {
    create.mutate(
      { name, callback_url: callbackUrl.trim(), visibility: "private" },
      {
        onSuccess: (secret) => {
          setCallbackUrl("");
          setError(undefined);
          onCreated(secret.id);
        },
        onError: (failure) => {
          const refused = submitFailure(failure, { fields: ["callback_url"] }, tErrors);
          setError(refused.fields.callback_url);
          if (refused.toast) toast.error(refused.toast);
        },
      },
    );
  };

  return (
    <div className="border-border space-y-3 rounded-lg border border-dashed p-3">
      <p className="text-muted-foreground text-xs">{t("chatgptPersonal")}</p>
      <ChatGPTSignInSteps
        callbackUrl={callbackUrl}
        onCallbackUrlChange={(value) => {
          setCallbackUrl(value);
          setError(undefined);
        }}
        error={error}
        disabled={disabled || create.isPending}
        idPrefix="inline-chatgpt"
      />
      <Button
        type="button"
        size="sm"
        disabled={disabled || create.isPending || !callbackUrl.trim()}
        onClick={submit}
      >
        {t("chatgptSave")}
      </Button>
    </div>
  );
}
