import { Mail } from "lucide-react";

import { BrandIcon, type BrandName } from "@/components/icons/brand-icon";

type IntegrationIllustration = BrandName | "mail";

const PRODUCT_MARKS: Readonly<Record<string, IntegrationIllustration>> = {
  gmail: "gmail",
  google_calendar: "googlecalendar",
  google_drive: "gdrive",
  google_docs: "gdocs",
  google_sheets: "gsheets",
  google_slides: "gslides",
  outlook_mail: "outlook",
  outlook_calendar: "outlookcalendar",
  microsoft_files: "onedrive",
  excel: "excel",
  word: "word",
  teams: "microsoftteams",
  slack: "slack",
  // IMAP is a protocol, so it has no product logo.
  imap_mail: "mail",
  odoo_contacts: "odoo",
  odoo_crm: "odoo",
  odoo_sales: "odoo",
  odoo_accounting: "odoo",
  odoo_inventory: "odoo",
  odoo_projects: "odoo",
};

export function integrationIllustration(id: string): IntegrationIllustration | undefined {
  return PRODUCT_MARKS[id];
}

/** The product's real mark on the existing account-and-operation stage. */
export function IntegrationArt({ illustration }: { illustration: IntegrationIllustration }) {
  return (
    <svg viewBox="0 0 240 135" aria-hidden="true">
      <polygon className="ishb" points="120,46 196,90 120,134 44,90" />
      <polygon className="ict" points="120,33 196,77 120,121 44,77" />
      <rect className="inr" x="67" y="18" width="67" height="73" rx="6" />
      <rect className="int" x="63" y="14" width="67" height="73" rx="6" />
      <rect x="68" y="19" width="57" height="63" rx="4" fill="#fff" />
      {illustration === "mail" ? (
        <Mail x="75" y="29" width="43" height="43" color="#475569" />
      ) : (
        <BrandIcon name={illustration} x="75" y="29" width="43" height="43" />
      )}
      <path className="ln w2 draw" d="M132 55H151M144 49L151 55L144 61" />
      <rect className="inr" x="153" y="46" width="28" height="42" rx="4" />
      <path className="ln w2" d="M160 58H174M160 65H174M160 72H168" />
    </svg>
  );
}
