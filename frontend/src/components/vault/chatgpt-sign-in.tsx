"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, Copy, ExternalLink, KeyRound, LogIn } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button, FormField, IconButton, Input, NativeDisclosure } from "@/components/ui";
import { useChatGPTSignIn, usePermissions } from "@/hooks";
import { apiClient } from "@/lib/api-client";
import { getErrorMessage, submitFailure } from "@/lib/api-error";
import { useAuthStore } from "@/stores";
import { Perm } from "@/types/permissions";

import type { ChatGPTSignInKind } from "@/types/secrets";

interface DeviceStart {
  state: string;
  user_code: string;
  verification_url: string;
  interval_seconds: number;
}

/**
 * Codex's device sign-in: show a short code, let the person approve it on
 * ChatGPT, and poll until they have - nothing to copy back. `endpoint` is the
 * start route; polling posts to `${endpoint}/${state}`.
 */
export function CodexDeviceCode({
  endpoint,
  onAuthorized,
  disabled,
}: {
  endpoint: string;
  onAuthorized: (state: string) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("vault");
  const tErrors = useTranslations("errors");
  const [started, setStarted] = useState<DeviceStart | null>(null);
  const [copied, setCopied] = useState(false);
  const start = useMutation({ mutationFn: () => apiClient.post<DeviceStart>(endpoint) });
  const poll = useQuery({
    queryKey: ["codex-device", endpoint, started?.state],
    queryFn: () => apiClient.post<{ authorized: boolean }>(`${endpoint}/${started?.state ?? ""}`),
    enabled: started !== null,
    refetchInterval: (query) =>
      query.state.data?.authorized || query.state.error
        ? false
        : (started?.interval_seconds ?? 5) * 1000,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const authorized = poll.data?.authorized === true;
  // The latest callback, so a parent re-rendering does not finish the sign-in twice.
  const finish = useRef(onAuthorized);
  useEffect(() => {
    finish.current = onAuthorized;
  });
  const approvedState = authorized ? (started?.state ?? null) : null;
  useEffect(() => {
    if (approvedState !== null) finish.current(approvedState);
  }, [approvedState]);

  function begin() {
    const tab = window.open("", "_blank");
    start.mutate(undefined, {
      onSuccess: (device) => {
        setStarted(device);
        if (tab) {
          tab.opener = null;
          tab.location.href = device.verification_url;
        }
      },
      onError: (failure) => {
        tab?.close();
        toast.error(getErrorMessage(failure, tErrors));
      },
    });
  }

  if (started === null || poll.isError) {
    return (
      <div className="space-y-1.5">
        <p className="text-muted-foreground text-xs">{t("chatgptDeviceHelp")}</p>
        {poll.isError && (
          <p role="alert" className="text-destructive text-xs">
            {getErrorMessage(poll.error, tErrors)}
          </p>
        )}
        <Button
          type="button"
          size="sm"
          disabled={disabled || start.isPending}
          onClick={() => {
            setStarted(null);
            begin();
          }}
        >
          <KeyRound className="h-3.5 w-3.5" />
          {t("chatgptDeviceStart")}
        </Button>
      </div>
    );
  }
  return (
    <div className="space-y-2" aria-live="polite">
      <p className="text-muted-foreground text-xs">{t("chatgptDeviceEnter")}</p>
      <div className="flex flex-wrap items-center gap-3">
        <code className="bg-muted rounded-md px-3 py-1.5 font-mono text-lg tracking-[0.2em] tabular-nums">
          {started.user_code}
        </code>
        <IconButton
          type="button"
          variant="ghost"
          aria-label={t("chatgptDeviceCopy")}
          onClick={() => {
            void navigator.clipboard?.writeText(started.user_code);
            setCopied(true);
          }}
        >
          {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
        </IconButton>
        <a
          href={started.verification_url}
          target="_blank"
          rel="noreferrer noopener"
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs underline underline-offset-4"
        >
          <ExternalLink className="h-3 w-3" aria-hidden />
          {t("chatgptDeviceOpen")}
        </a>
      </div>
      <p className="text-muted-foreground text-xs">
        {authorized ? t("chatgptDeviceApproved") : t("chatgptDeviceWaiting")}
      </p>
    </div>
  );
}

interface ChatGPTSignInStepsProps {
  kind?: ChatGPTSignInKind;
  /** Codex only: where a device sign-in starts; offering it makes pasting the fallback. */
  deviceEndpoint?: string;
  /** Called with the approved device sign-in's state, or null when it is reset. */
  onDeviceAuthorized?: (state: string) => void;
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
export function ChatGPTSignInSteps(props: ChatGPTSignInStepsProps) {
  const { start } = useChatGPTSignIn(props.kind ?? "openai_codex");
  return (
    <ChatGPTCallbackSteps {...props} startSignIn={start.mutateAsync} starting={start.isPending} />
  );
}

export function ChatGPTCallbackSteps({
  kind = "openai_codex",
  deviceEndpoint,
  onDeviceAuthorized,
  callbackUrl,
  onCallbackUrlChange,
  error,
  disabled,
  idPrefix,
  startSignIn,
  starting,
}: ChatGPTSignInStepsProps & {
  startSignIn: () => Promise<{ authorization_url: string }>;
  starting: boolean;
}) {
  const t = useTranslations("vault");
  const tErrors = useTranslations("errors");
  const [authorizationUrl, setAuthorizationUrl] = useState<string | null>(null);

  function begin() {
    const tab = window.open("", "_blank");
    void startSignIn()
      .then(({ authorization_url }) => {
        setAuthorizationUrl(authorization_url);
        if (tab) {
          tab.opener = null;
          tab.location.href = authorization_url;
        }
      })
      .catch((failure: unknown) => {
        tab?.close();
        toast.error(getErrorMessage(failure, tErrors));
      });
  }

  const paste = (
    <div className="space-y-3">
      {kind === "openai_chatgpt" && (
        <p className="text-muted-foreground text-xs">{t("chatgptOfficialHelp")}</p>
      )}
      <div className="space-y-1.5">
        <p className="text-muted-foreground text-xs">{t("chatgptStepOne")}</p>
        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled || starting}
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
          placeholder={
            kind === "openai_chatgpt"
              ? "http://127.0.0.1:1455/auth/callback?code=…"
              : "http://localhost:1455/auth/callback?code=…"
          }
          autoComplete="off"
          disabled={disabled}
          className="font-mono"
        />
      </FormField>
    </div>
  );
  if (kind !== "openai_codex" || deviceEndpoint === undefined || onDeviceAuthorized === undefined)
    return paste;
  return (
    <div className="space-y-3">
      <CodexDeviceCode
        endpoint={deviceEndpoint}
        onAuthorized={onDeviceAuthorized}
        disabled={disabled}
      />
      <NativeDisclosure className="text-xs">
        <summary className="text-muted-foreground hover:text-foreground cursor-pointer">
          {t("chatgptPasteInstead")}
        </summary>
        <div className="pt-3">{paste}</div>
      </NativeDisclosure>
    </div>
  );
}

interface InlineChatGPTSignInProps {
  kind?: ChatGPTSignInKind;
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
  kind = "openai_codex",
  suggestedName,
  onCreated,
  disabled,
}: InlineChatGPTSignInProps) {
  const t = useTranslations("vault");
  const tErrors = useTranslations("errors");
  const { create } = useChatGPTSignIn(kind);
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

  const submit = (deviceState?: string) => {
    create.mutate(
      deviceState !== undefined
        ? { name, device_state: deviceState, visibility: "private" }
        : { name, callback_url: callbackUrl.trim(), visibility: "private" },
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
        key={kind}
        kind={kind}
        deviceEndpoint="/secrets/openai-codex/device"
        onDeviceAuthorized={(state) => submit(state)}
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
        onClick={() => submit()}
      >
        {t("chatgptSave")}
      </Button>
    </div>
  );
}
