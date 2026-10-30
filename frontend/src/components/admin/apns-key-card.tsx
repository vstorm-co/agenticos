"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  Button,
  FormField,
  Input,
  ListCard,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import {
  apnsSetup,
  clearApnsKey,
  setApnsKey,
  type ApnsEnvironment,
  type ApnsSetup,
} from "@/lib/mobile/apns";

const QUERY = ["push", "apns"] as const;

/**
 * The organization's APNs key (#2097): push to the iPhone app goes through
 * Apple with the key of the developer account the company signs its build
 * with. Saved on its own, not with the page's draft - it is a credential,
 * sealed by the server the moment it arrives, and never shown again: the card
 * says whose key it is and offers to replace or remove it.
 */
export function ApnsKeyCard() {
  const t = useTranslations("pages.adminApns");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: QUERY, queryFn: apnsSetup });
  const [replacing, setReplacing] = useState(false);
  const [keyId, setKeyId] = useState("");
  const [teamId, setTeamId] = useState("");
  const [topic, setTopic] = useState("");
  const [environment, setEnvironment] = useState<ApnsEnvironment>("production");
  const [privateKey, setPrivateKey] = useState("");

  const settled = (setup: ApnsSetup) => {
    queryClient.setQueryData(QUERY, setup);
    setReplacing(false);
    setPrivateKey("");
  };
  const save = useMutation({
    mutationFn: () =>
      setApnsKey({
        key_id: keyId.trim(),
        team_id: teamId.trim(),
        topic: topic.trim(),
        environment,
        private_key: privateKey,
      }),
    onSuccess: (setup) => {
      settled(setup);
      toast.success(t("saved"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors, t("failed"))),
  });
  const remove = useMutation({
    mutationFn: clearApnsKey,
    onSuccess: (setup) => {
      settled(setup);
      toast.success(t("removed"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors, t("failed"))),
  });

  if (data === undefined) return null;
  const editing = !data.configured || replacing;
  const busy = save.isPending || remove.isPending;
  const complete = keyId.trim() && teamId.trim() && topic.trim() && privateKey;

  return (
    <ListCard title={t("title")} counted={t("hint")}>
      {data.configured && !replacing ? (
        <div className="border-border flex flex-wrap items-center justify-between gap-3 rounded-xl border p-4">
          <div className="min-w-0">
            <p className="text-foreground text-sm font-medium">{data.topic}</p>
            <p className="text-muted-foreground mt-0.5 text-xs">
              {t("whose", {
                key: data.key_id ?? "",
                team: data.team_id ?? "",
                environment: t(`environment.${data.environment ?? "production"}`),
              })}
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" disabled={busy} onClick={() => setReplacing(true)}>
              {t("replace")}
            </Button>
            <Button variant="ghost" disabled={busy} onClick={() => remove.mutate()}>
              {t("remove")}
            </Button>
          </div>
        </div>
      ) : null}
      {editing ? (
        <form
          className="grid gap-4 sm:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate();
          }}
        >
          <FormField label={t("keyId")} htmlFor="apns-key-id" description={t("keyIdHint")}>
            <Input
              value={keyId}
              onChange={(event) => setKeyId(event.target.value.toUpperCase())}
              maxLength={10}
              autoComplete="off"
            />
          </FormField>
          <FormField label={t("teamId")} htmlFor="apns-team-id" description={t("teamIdHint")}>
            <Input
              value={teamId}
              onChange={(event) => setTeamId(event.target.value.toUpperCase())}
              maxLength={10}
              autoComplete="off"
            />
          </FormField>
          <FormField label={t("topic")} htmlFor="apns-topic" description={t("topicHint")}>
            <Input
              value={topic}
              onChange={(event) => setTopic(event.target.value)}
              // i18n-exempt: a bundle identifier, the same in every language
              placeholder="com.example.agenticos"
              autoComplete="off"
            />
          </FormField>
          <FormField label={t("environmentLabel")} htmlFor="apns-environment">
            <Select
              value={environment}
              onValueChange={(value) =>
                setEnvironment(value === "sandbox" ? "sandbox" : "production")
              }
            >
              <SelectTrigger id="apns-environment">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="production">{t("environment.production")}</SelectItem>
                <SelectItem value="sandbox">{t("environment.sandbox")}</SelectItem>
              </SelectContent>
            </Select>
          </FormField>
          <FormField
            label={t("file")}
            htmlFor="apns-file"
            description={t("fileHint")}
            className="sm:col-span-2"
          >
            <Input
              type="file"
              accept=".p8"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void file.text().then(setPrivateKey);
              }}
            />
          </FormField>
          <div className="flex gap-2 sm:col-span-2">
            <Button type="submit" disabled={busy || !complete}>
              {t("save")}
            </Button>
            {replacing ? (
              <Button type="button" variant="ghost" onClick={() => setReplacing(false)}>
                {t("cancel")}
              </Button>
            ) : null}
          </div>
        </form>
      ) : null}
    </ListCard>
  );
}
