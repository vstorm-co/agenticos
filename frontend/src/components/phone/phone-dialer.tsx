"use client";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Checkbox, Label, Textarea } from "@/components/ui";
import { useAgents } from "@/hooks/use-agents";
import type { PhoneCallCreate, PhoneChoice } from "@/lib/phone-api";
import { PhoneSelect } from "./phone-select";
export function PhoneDialer({
  endpoints,
  pending,
  onCall,
}: {
  endpoints: PhoneChoice[];
  pending: boolean;
  onCall: (data: PhoneCallCreate) => void;
}) {
  const t = useTranslations("phone");
  const [key] = useState(() => crypto.randomUUID());
  const [endpoint, setEndpoint] = useState("");
  const [agent, setAgent] = useState("");
  const [reportMode, setReportMode] = useState(false);
  const [report, setReport] = useState("");
  const { agents } = useAgents({ enabled: !reportMode });
  return (
    <form
      className="space-y-3"
      data-tour="phone-dial"
      onSubmit={(event) => {
        event.preventDefault();
        onCall({
          request_key: key,
          endpoint_id: endpoint,
          mode: reportMode ? "report" : "conversation",
          agent_id: reportMode ? null : agent,
          report: reportMode ? report.trim() : null,
        });
      }}
    >
      <PhoneSelect
        label={t("route")}
        value={endpoint}
        onChange={setEndpoint}
        choices={endpoints}
        disabled={pending}
      />
      <label className="flex items-center gap-2 text-sm">
        <Checkbox
          checked={reportMode}
          disabled={pending}
          onCheckedChange={(value) => setReportMode(value === true)}
        />
        {t("reportMode")}
      </label>
      {reportMode ? (
        <div className="space-y-1">
          <Label htmlFor="phone-report">{t("reportText")}</Label>
          <Textarea
            id="phone-report"
            value={report}
            onChange={(event) => setReport(event.target.value)}
            maxLength={5000}
            disabled={pending}
            required
          />
        </div>
      ) : (
        <PhoneSelect
          label={t("agent")}
          value={agent}
          onChange={setAgent}
          choices={agents
            .filter(
              (entry) =>
                entry.can_run &&
                entry.status === "published" &&
                entry.current_version_id !== null &&
                !entry.workflow_id,
            )
            .map((entry) => ({ id: entry.id, label: entry.name }))}
          disabled={pending}
        />
      )}
      <p className="text-muted-foreground text-xs">{t("dialHint")}</p>
      <Button
        type="submit"
        disabled={pending || !endpoint || (reportMode ? !report.trim() : !agent)}
      >
        {t("callMe")}
      </Button>
    </form>
  );
}
