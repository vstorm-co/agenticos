"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { SectionCard } from "@/components/settings/settings-section";
import { Button, Input, Label } from "@/components/ui";
import { useLocalServices } from "@/hooks/use-desktop";
import type { LocalService } from "@/lib/desktop/commands";

/** Local service access is approved by the native app, independently of this page. */
export function LocalServiceSettings() {
  const t = useTranslations("desktop.settings.services");
  const { state, save, remove } = useLocalServices();
  const [kind, setKind] = useState<LocalService["kind"]>("model");
  const [name, setName] = useState("");
  const [endpoint, setEndpoint] = useState("http://127.0.0.1:11434/v1");
  const [model, setModel] = useState("");
  const error = state.error ?? save.error ?? remove.error;
  return (
    <SectionCard title={t("title")} description={t("description")}>
      <ul className="mb-4 space-y-2">
        {(state.data ?? []).map((service) => (
          <li key={service.id} className="flex items-center justify-between gap-3 text-sm">
            <span className="min-w-0">
              <span className="block truncate font-medium">{service.name}</span>
              <span className="text-muted-foreground block truncate text-xs">
                {service.model ?? service.endpoint}
              </span>
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={remove.isPending}
              onClick={() => remove.mutate(service.id)}
              aria-label={t("removeNamed", { name: service.name })}
            >
              {t("remove")}
            </Button>
          </li>
        ))}
      </ul>
      <form
        className="grid gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate(
            {
              id: crypto.randomUUID().replaceAll("-", ""),
              name,
              endpoint,
              kind,
              model: kind === "model" ? model : null,
            },
            {
              onSuccess: () => {
                setName("");
                setModel("");
              },
            },
          );
        }}
      >
        <div>
          <Label htmlFor="local-service-kind">{t("kind")}</Label>
          <select
            id="local-service-kind"
            className="border-input bg-background mt-1 h-10 w-full rounded-md border px-3 text-sm"
            value={kind}
            onChange={(event) => {
              const next = event.target.value;
              if (next !== "model" && next !== "mcp") return;
              setKind(next);
              setEndpoint(
                next === "model" ? "http://127.0.0.1:11434/v1" : "http://127.0.0.1:8000/mcp",
              );
            }}
          >
            <option value="model">{t("modelKind")}</option>
            <option value="mcp">{t("mcpKind")}</option>
          </select>
        </div>
        <div>
          <Label htmlFor="local-service-name">{t("name")}</Label>
          <Input
            id="local-service-name"
            required
            maxLength={120}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </div>
        <div>
          <Label htmlFor="local-service-endpoint">{t("endpoint")}</Label>
          <Input
            id="local-service-endpoint"
            type="url"
            required
            value={endpoint}
            onChange={(event) => setEndpoint(event.target.value)}
          />
        </div>
        {kind === "model" && (
          <div>
            <Label htmlFor="local-service-model">{t("model")}</Label>
            <Input
              id="local-service-model"
              required
              maxLength={200}
              value={model}
              onChange={(event) => setModel(event.target.value)}
            />
          </div>
        )}
        {error && (
          <p role="alert" className="text-destructive text-sm">
            {error.message}
          </p>
        )}
        <Button type="submit" disabled={save.isPending}>
          {t(save.isPending ? "confirm" : "add")}
        </Button>
      </form>
    </SectionCard>
  );
}
