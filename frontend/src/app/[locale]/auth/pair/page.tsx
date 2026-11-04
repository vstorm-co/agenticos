import { Suspense } from "react";

import { PairDevice } from "@/components/mobile/pair-device";

/** Where the mobile app sends its webview with a scanned pairing code (#2097). */
export default function PairPage() {
  return (
    <Suspense fallback={null}>
      <PairDevice />
    </Suspense>
  );
}
