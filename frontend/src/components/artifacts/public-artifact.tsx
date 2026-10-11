"use client";

import { useState } from "react";
import { Lock } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import { ArtifactFrameView } from "@/components/artifacts/artifact-frame";
import { Button, FormField, Input } from "@/components/ui";
import { usePublicArtifactUnlock } from "@/hooks/use-artifacts";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import type { OpenPublicArtifact, PublicArtifact as PublicArtifactData } from "@/types/artifact";

/**
 * What a stranger holding the link sees: the page, its title, and when it was
 * last published. Nothing about who made it or which organization it is from.
 */
export function OpenedArtifact({ artifact }: { artifact: OpenPublicArtifact }) {
  const t = useTranslations("artifacts");
  const format = useFormatter();
  return (
    <main className="bg-background flex min-h-dvh flex-col gap-3 p-4">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-foreground text-lg font-semibold">{artifact.title}</h1>
        <p className="text-muted-foreground text-xs">
          {t("publicUpdated", {
            when: format.dateTime(new Date(artifact.published_at), {
              dateStyle: "medium",
              timeStyle: "short",
            }),
          })}
        </p>
      </header>
      <div className="flex min-h-0 flex-1 flex-col">
        <ArtifactFrameView url={artifact.view.url} title={artifact.title} />
      </div>
    </main>
  );
}

/**
 * A link behind a password: one field, and the page once it is right.
 *
 * Nothing is shown before - not the title, not when it was published - because
 * the server sent nothing. A wrong password is said in the form, not in a toast,
 * and every attempt counts against the link's own limit on the server.
 */
function PasswordGate({ publicKey }: { publicKey: string }) {
  const t = useTranslations("artifacts");
  const tErrors = useTranslations("errors");
  const unlock = usePublicArtifactUnlock(publicKey);
  const [password, setPassword] = useState("");

  if (unlock.data !== undefined) return <OpenedArtifact artifact={unlock.data} />;
  const refusal =
    unlock.error instanceof ApiError && unlock.error.status === 403
      ? t("wrongPassword")
      : unlock.error
        ? getErrorMessage(unlock.error, tErrors)
        : null;

  return (
    <main className="bg-background flex min-h-dvh items-center justify-center p-4">
      <form
        className="w-full max-w-sm space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          unlock.mutate(password);
        }}
      >
        <div className="space-y-1 text-center">
          <Lock className="text-muted-foreground mx-auto h-5 w-5" aria-hidden />
          <h1 className="text-foreground text-lg font-semibold">{t("passwordTitle")}</h1>
          <p className="text-muted-foreground text-sm">{t("passwordWhy")}</p>
        </div>
        <FormField htmlFor="public-artifact-password" label={t("linkPassword")} error={refusal}>
          <Input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </FormField>
        <Button type="submit" className="w-full" disabled={password === "" || unlock.isPending}>
          {t("openPage")}
        </Button>
      </form>
    </main>
  );
}

/** The public link's page: the artifact, or the password it asks for first. */
export function PublicArtifact({
  artifact,
  publicKey,
}: {
  artifact: PublicArtifactData;
  publicKey: string;
}) {
  if (artifact.password_required) return <PasswordGate publicKey={publicKey} />;
  return <OpenedArtifact artifact={artifact} />;
}
