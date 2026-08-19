"use client";

import { useState, type KeyboardEvent } from "react";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Input } from "@/components/ui";

/**
 * The domains that may register, as chips rather than a comma-separated string.
 *
 * A text field would be shorter and would let an operator save `acme.com,`
 * or `@acme.com` and find out at the 422. Each entry is committed one at a time,
 * so a malformed one is visible as its own chip before the form is saved - and the
 * server still normalises and validates, because this is a convenience and not the
 * rule.
 *
 * An empty list is a real state and not an unfinished one: it means every domain is
 * allowed, which is what most deployments want.
 */
export function DomainListField({
  domains,
  onChange,
  disabled,
}: {
  domains: string[];
  onChange: (next: string[]) => void;
  disabled: boolean;
}) {
  const t = useTranslations("pages.admin");
  const [draft, setDraft] = useState("");

  const add = () => {
    const domain = draft.trim().toLowerCase().replace(/^@/, "");
    if (!domain || domains.includes(domain)) {
      setDraft("");
      return;
    }
    onChange([...domains, domain]);
    setDraft("");
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    // Enter and comma both commit. A comma is what somebody types when they think
    // this is a list field, and swallowing it is kinder than storing it.
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      add();
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <Input
          id="allowed-domains"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={t("domainsPlaceholder")}
          disabled={disabled}
        />
        <Button type="button" variant="outline" onClick={add} disabled={disabled || !draft.trim()}>
          {t("domainsAdd")}
        </Button>
      </div>

      {domains.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {domains.map((domain) => (
            <li
              key={domain}
              className="border-border bg-muted text-foreground inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs"
            >
              <span className="font-mono">{domain}</span>
              <button
                type="button"
                disabled={disabled}
                onClick={() => onChange(domains.filter((d) => d !== domain))}
                aria-label={t("domainsRemove", { domain })}
                className="text-muted-foreground hover:text-foreground transition-colors"
              >
                <X className="h-3 w-3" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
