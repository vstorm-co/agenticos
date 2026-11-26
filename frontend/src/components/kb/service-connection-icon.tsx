import { FileType2 } from "lucide-react";

import { BrandIcon } from "@/components/icons/brand-icon";
import { ProviderIcon } from "@/components/vault/provider-icon";
import type { ServiceConnectionKind, ServiceConnectionStyle } from "@/lib/service-connections-api";

/** Use the publisher's maintained LlamaIndex mark for LiteParse, Ollama's for Ollama, the generic plug for a gateway. */
export function ServiceConnectionIcon({
  kind,
  provider,
  className,
}: {
  kind: ServiceConnectionKind;
  provider?: ServiceConnectionStyle;
  className?: string;
}) {
  if (provider === "openai_compatible") {
    return <ProviderIcon provider="openai_compatible" className={className} />;
  }
  if (kind === "document_parser") {
    // Docling publishes no mark here; the generic parser glyph says what it is for.
    return <FileType2 className={className} aria-hidden />;
  }
  return kind === "embedding" ? (
    <ProviderIcon provider="ollama" className={className} />
  ) : (
    <BrandIcon name="llamaparse" mono className={className} />
  );
}
