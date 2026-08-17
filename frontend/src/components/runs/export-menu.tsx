"use client";

import { useState } from "react";
import { Download } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import { usePermissions } from "@/hooks";
import { apiClient } from "@/lib/api-client";
import { saveBlob } from "@/lib/file-access";
import type { Permission } from "@/types/permissions";

/** What one endpoint calls the two bounds of the window it exports. */
export interface RangeParams {
  from: string;
  to: string;
}

interface ExportMenuProps {
  /** The permission the tab is gated on. Without it the control is not rendered. */
  permission: Permission;
  /** The export endpoint, e.g. `/runs/export`. */
  endpoint: string;
  /** The download's filename prefix, when the server sends none. */
  kind: string;
  /** The filters currently applied on the tab, sent verbatim so the file is what
   * is on screen. Pairs allow a repeated key - the approvals export takes
   * `status` several times. */
  params?: Record<string, string> | [string, string][];
  /** What this endpoint names the window's start and end. */
  rangeParams: RangeParams;
  /** The page's window, as instants - the mandatory range the endpoint demands. */
  range: { from: string; to: string };
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
 * filters plus the page's window, because the export refuses a request with no
 * date range and caps the rows above a ceiling; both refusals are surfaced as a
 * toast, so a range too wide to serialise is said out loud rather than
 * downloaded empty.
 *
 * The window is the page's period control, not a preset of its own: the file
 * is the table, and a control that exported a different window than the one on
 * screen would be the #763 defect with dates instead of filters.
 */
export function ExportMenu({
  permission,
  endpoint,
  kind,
  params,
  rangeParams,
  range,
}: ExportMenuProps) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("pages.runs");
  const { can } = usePermissions();
  const [busy, setBusy] = useState(false);

  if (!can(permission)) return null;

  const download = async () => {
    setBusy(true);
    try {
      const window: [string, string][] = [
        [rangeParams.from, range.from],
        [rangeParams.to, range.to],
      ];
      const query = Array.isArray(params)
        ? [...params, ...window]
        : { ...params, ...Object.fromEntries(window) };
      const response = await apiClient.raw(endpoint, { params: query });
      saveBlob(await response.blob(), filenameFrom(response, `${kind}_export.csv`));
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors, t("exportFailed")));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Button
      variant="outline"
      size="sm"
      className="gap-1.5"
      disabled={busy}
      onClick={() => void download()}
    >
      <Download className="size-3.5" aria-hidden />
      {t("exportCsv")}
    </Button>
  );
}
