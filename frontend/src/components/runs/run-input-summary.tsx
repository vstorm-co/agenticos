"use client";
import { useLocale, useTranslations } from "next-intl";
import { Badge } from "@/components/ui";
import type { RunManifest } from "@/types/runs";

/** Model policy and aggregate usage of the recorded requests, not an estimate of context. */
export function RunInputSummary({ manifest }: { manifest: RunManifest }) {
  const t = useTranslations("pages.runs");
  const locale = useLocale();
  const requests = manifest.requests;
  const totals = requests.reduce(
    (sum, request) => ({
      input: sum.input + request.input_tokens,
      output: sum.output + request.output_tokens,
      read: sum.read + request.cache_read_tokens,
      write: sum.write + (request.cache_write_tokens ?? 0),
    }),
    { input: 0, output: 0, read: 0, write: 0 },
  );
  const writeKnown = requests.every((request) => request.cache_write_tokens != null);
  const format = (value: number) => value.toLocaleString(locale);
  if (Object.keys(manifest.settings).length === 0 && requests.length === 0) return null;
  return (
    <section className="space-y-3 rounded-xl border p-4">
      {Object.keys(manifest.settings).length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 className="text-sm font-medium">{t("modelSettings")}</h4>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(manifest.settings).map(([key, value]) => (
              <Badge key={key} variant="secondary" className="font-mono text-xs">
                {t("settingPair", { key, value: String(value) })}
              </Badge>
            ))}
          </div>
        </div>
      )}
      {requests.length > 0 && (
        <>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 @[420px]:grid-cols-4">
            {(
              [
                ["inputTokenInput", format(totals.input)],
                ["inputTokenOutput", format(totals.output)],
                ["inputTokenCacheRead", format(totals.read)],
                ["inputTokenCacheWrite", writeKnown ? format(totals.write) : t("inputUnknown")],
              ] as const
            ).map(([label, value]) => (
              <div key={label}>
                <dt className="text-muted-foreground text-xs">{t(label)}</dt>
                <dd className="mt-1 text-sm font-semibold tabular-nums">{value}</dd>
              </div>
            ))}
          </dl>
          <p className="text-muted-foreground text-xs leading-relaxed">{t("inputTokenHint")}</p>
        </>
      )}
    </section>
  );
}
