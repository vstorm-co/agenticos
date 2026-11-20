"use client";

import { useState } from "react";
import Link from "next/link";
import { KeyRound } from "lucide-react";
import { useTranslations } from "next-intl";

import { AddModel } from "@/components/agents/add-model";
import { SectionCard } from "@/components/settings/settings-section";
import { ClaudeSubscriptionConnection } from "@/components/settings/claude-subscription-connection";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui";
import { PersonalApiConnection } from "@/components/vault/personal-api-connection";
import { ProviderIcon } from "@/components/vault/provider-icon";
import { useModelProviders, usePermissions, useSecretPurposes, useSecrets } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { useAuthStore } from "@/stores";
import { Perm } from "@/types/permissions";
import type { ModelProfile } from "@/types/providers";
import type { Secret } from "@/types/secrets";

export function PersonalModelConnections() {
  const t = useTranslations("personalModels");
  const { can } = usePermissions();
  const user = useAuthStore((state) => state.user);
  return (
    <SectionCard
      title={t("title")}
      description={t("description")}
      icon={KeyRound}
      tour="personal-model-connections"
    >
      <div className="space-y-6" data-tour="personal-model-setup">
        <p className="text-muted-foreground text-sm">{t("personalUse")}</p>
        <ClaudeSubscriptionConnection />
        {user && can(Perm.secretsView) && can(Perm.agentsView) ? (
          <PersonalModelConnectionsContent userId={user.id} />
        ) : (
          <p className="text-muted-foreground text-sm">{t("readPermission")}</p>
        )}
      </div>
    </SectionCard>
  );
}

function PersonalModelConnectionsContent({ userId }: { userId: string }) {
  const t = useTranslations("personalModels");
  const tErrors = useTranslations("errors");
  const { can } = usePermissions();
  const { secrets, isLoading, listError, refetchSecrets } = useSecrets();
  const { purposes, error: purposesError, refetch: refetchPurposes } = useSecretPurposes();
  const { profiles, profilesStatus, refetchProfiles } = useModelProviders();
  const [connection, setConnection] = useState<Secret | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const own = secrets.filter(
    (secret) => secret.usage_scope === "personal" && secret.owner_user_id === userId,
  );
  const providers = purposes.filter(
    (provider) =>
      provider.category === "model_provider" && ["anthropic", "openai"].includes(provider.id),
  );
  const canAddModel = can(Perm.connectionsManage);
  const failure = listError || purposesError;

  if (isLoading) return <LoadingState variant="skeleton-list" rows={2} />;
  if (failure) {
    return (
      <ErrorState
        description={getErrorMessage(failure, tErrors)}
        cta={{
          label: t("retry"),
          onClick: () => void Promise.all([refetchSecrets(), refetchPurposes()]),
        }}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2" data-tour="personal-model-connect">
        {providers.map((provider) => (
          <section key={provider.id} className="border-border space-y-3 rounded-xl border p-4">
            <h3 className="flex items-center gap-2 text-sm font-medium">
              <ProviderIcon provider={provider.id} />
              {provider.label}
            </h3>
            <p className="text-muted-foreground text-xs">
              {t(provider.id === "anthropic" ? "anthropicCredits" : "openaiApi")}
            </p>
            {provider.id === "anthropic" && (
              <a
                href="https://platform.claude.com/docs/en/about-claude/api-credits-for-subscribers"
                target="_blank"
                rel="noopener noreferrer"
                className="text-muted-foreground block text-xs underline underline-offset-4"
              >
                {t("learnCredits")}
              </a>
            )}
            <PersonalApiConnection
              provider={provider}
              onCreated={(secret) => {
                setSaved(t("connectionSaved"));
                if (canAddModel) setConnection(secret);
              }}
            />
          </section>
        ))}
      </div>
      {!can(Perm.secretsEdit) && (
        <p className="text-muted-foreground text-sm">{t("writePermission")}</p>
      )}
      {!canAddModel && <p className="text-muted-foreground text-sm">{t("modelPermission")}</p>}
      {saved && (
        <p role="status" className="text-muted-foreground text-sm">
          {saved}
        </p>
      )}
      {connection && canAddModel && (
        <div className="space-y-2" data-tour="personal-model-create">
          <h3 className="text-sm font-medium">{t("chooseModelFor", { name: connection.name })}</h3>
          <AddModel
            key={connection.id}
            connection={connection}
            onCancel={() => setConnection(null)}
            onCreated={(profile) => {
              setSaved(t("modelSaved", { label: profile.label }));
              setConnection(null);
            }}
          />
        </div>
      )}
      <div className="space-y-3">
        <h3 className="text-sm font-medium">{t("savedConnections")}</h3>
        {own.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("noneSaved")}</p>
        ) : (
          <ul className="divide-border divide-y">
            {own.map((secret) => (
              <PersonalConnectionRow
                key={secret.id}
                secret={secret}
                profiles={profiles.filter((profile) => profile.secret_id === secret.id)}
                canAddModel={canAddModel}
                onChoose={() => setConnection(secret)}
              />
            ))}
          </ul>
        )}
        {profilesStatus === "failed" && (
          <p role="alert" className="text-destructive text-xs">
            {t("modelsUnavailable")}{" "}
            <Button type="button" size="sm" variant="ghost" onClick={() => void refetchProfiles()}>
              {t("retry")}
            </Button>
          </p>
        )}
        <Link
          href={ROUTES.VAULT}
          className="text-muted-foreground text-xs underline underline-offset-4"
        >
          {t("manageInVault")}
        </Link>
      </div>
    </div>
  );
}

function PersonalConnectionRow({
  secret,
  profiles,
  canAddModel,
  onChoose,
}: {
  secret: Secret;
  profiles: ModelProfile[];
  canAddModel: boolean;
  onChoose: () => void;
}) {
  const t = useTranslations("personalModels");
  return (
    <li className="flex flex-wrap items-start gap-3 py-3">
      <ProviderIcon provider={secret.purpose ?? ""} className="mt-0.5 size-5" />
      <div className="min-w-0 flex-1 space-y-1">
        <p className="text-sm font-medium break-words">{secret.name}</p>
        <p className="text-muted-foreground text-xs">{t("savedNotTested")}</p>
        {profiles.map((profile) => (
          <p key={profile.id} className="text-muted-foreground text-xs break-words">
            {profile.label}
          </p>
        ))}
      </div>
      {canAddModel && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onChoose}
          aria-label={t("chooseModelFor", { name: secret.name })}
        >
          {t("chooseModel")}
        </Button>
      )}
    </li>
  );
}
