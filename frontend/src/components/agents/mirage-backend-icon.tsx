import { HardDrive, Mail, MemoryStick, Plug, Terminal, type LucideIcon } from "lucide-react";

import { BrandIcon, isBrandName, type BrandName } from "@/components/icons/brand-icon";
import { CONNECTOR_LOGOS } from "@/lib/connector-logos.generated";

const BRANDS: Readonly<Partial<Record<string, BrandName>>> = {
  databricks_volume: "databricks",
  gcal: "googlecalendar",
  gridfs: "mongodb",
  hf_buckets: "huggingface",
  hf_datasets: "huggingface",
  hf_models: "huggingface",
  hf_spaces: "huggingface",
  tidb_filesystem: "tidb",
  r2: "cloudflare",
};

const SYSTEM_ICONS: Readonly<Partial<Record<string, LucideIcon>>> = {
  email: Mail,
  ram: MemoryStick,
  ssh: Terminal,
  disk: HardDrive,
};

export function MirageBackendIcon({ backend }: { backend: string }) {
  const brand = BRANDS[backend] ?? (isBrandName(backend) ? backend : undefined);
  const logo = backend === "lancedb" ? CONNECTOR_LOGOS.lancedb : undefined;
  const Fallback = SYSTEM_ICONS[backend] ?? Plug;

  return (
    <span
      aria-hidden
      className="border-foreground/10 grid size-6 shrink-0 place-items-center rounded-md border bg-white text-neutral-800"
    >
      {logo ? (
        // Baked data URI; no request or image optimisation is needed.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={logo} alt="" className="size-4 object-contain" />
      ) : brand ? (
        <BrandIcon name={brand} className="size-4" />
      ) : (
        <Fallback className="size-4" />
      )}
    </span>
  );
}
