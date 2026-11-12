import { DesktopPage } from "@/components/desktop/desktop-only";
import { BlobbyWindow } from "@/components/desktop/blobby-window";

/** Blobby, in the desktop app's transparent window of its own (`desktop/src-tauri/src/blobby.rs`). */
export default function BlobbyPage() {
  return (
    <DesktopPage>
      <BlobbyWindow />
    </DesktopPage>
  );
}
