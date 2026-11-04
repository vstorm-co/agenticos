import { BrandIcon } from "@/components/icons/brand-icon";
import { ProviderIcon } from "@/components/vault/provider-icon";
import type { LocalServiceKind } from "@/lib/local-services-api";

/** Use the publisher's maintained LlamaIndex mark for LiteParse. */
export function LocalServiceIcon({
  kind,
  className,
}: {
  kind: LocalServiceKind;
  className?: string;
}) {
  return kind === "embedding" ? (
    <ProviderIcon provider="ollama" className={className} />
  ) : (
    <BrandIcon name="llamaparse" mono className={className} />
  );
}
