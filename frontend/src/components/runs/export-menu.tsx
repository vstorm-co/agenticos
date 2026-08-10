"use client";

import { useState } from "react";
import { Download } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui";
import { usePermissions } from "@/hooks";
import { apiClient } from "@/lib/api-client";
import { saveBlob } from "@/lib/file-access";
import { getErrorMessage } from "@/lib/utils";
import type { Permission } from "@/types/permissions";

/** What one endpoint calls the two bounds of the window it exports. */
export interface RangeParams {
  from: string;
  to: string;
}

/** The windows offered, in days. The export refuses a request with no range, so
 * a control that could send none would be a button that only ever 422s. */
const PRESET_DAYS = [7, 30, 90] as const;

interface ExportMenuProps {
  /** The permission the tab is gated on. Without it the control is not rendered. */
  permission: Permission;
  /** The export endpoint, e.g. `/runs/export`. */
  endpoint: string;
  /** The download's filename prefix, when the server sends none. */
  kind: string;
  /** The filters currently applied on the tab, sent verbatim so the file is what
   * is on screen. */
  params?: Record<string, string>;
  /** What this endpoint names the window's start and end. */
  rangeParams: RangeParams;
}

function filenameFrom(response: Response, fallback: string): string {
  const match = response.headers.get("content-disposition")?.match(/filename="([^"]+)"/);
  return match?.[1] ?? fallback;
}

/**
 * The download control on an Activity tab.
 *
 * **Absent, not disabled, without the permission** - the same rule the tab it
 * sits on follows: a control somebody may not use is not shown greyed out and
 * then answered 403, it is not drawn at all. It carries the tab's current
 * filters plus a window, because the export refuses a request with no date range
 * and caps the rows above a ceiling; both refusals are surfaced as a toast, so a
 * range too wide to serialise is said out loud rather than downloaded empty.
 *
 * The window is a preset here rather than the tab's own range picker, which the
 * Activity page does not have: the export needs a bounded window by design, and
 * the presets are the smallest control that always sends one.
 */
export function ExportMenu({ permission, endpoint, kind, params, rangeParams }: ExportMenuProps) {
  const t = useTranslations("pages.runs");
  const { can } = usePermissions();
  const [busy, setBusy] = useState(false);

  if (!can(permission)) return null;

  const download = async (days: number) => {
    setBusy(true);
    try {
      const now = new Date();
      const from = new Date(now.getTime() - days * 24 * 60 * 60 * 1000);
      const query: Record<string, string> = {
        ...params,
        [rangeParams.from]: from.toISOString(),
        [rangeParams.to]: now.toISOString(),
      };
      const response = await apiClient.raw(endpoint, { params: query });
      saveBlob(await response.blob(), filenameFrom(response, `${kind}_export.csv`));
    } catch (error) {
      toast.error(getErrorMessage(error, t("exportFailed")));
    } finally {
      setBusy(false);
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5" disabled={busy}>
          <Download className="size-3.5" aria-hidden />
          {t("exportCsv")}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {PRESET_DAYS.map((days) => (
          <DropdownMenuItem key={days} onSelect={() => void download(days)}>
            {t("exportRange", { days })}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
