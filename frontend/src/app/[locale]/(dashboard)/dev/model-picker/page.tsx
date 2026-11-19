import { Suspense } from "react";
import { notFound } from "next/navigation";
import { ModelPickerPreviewPage } from "@/components/chat/model-picker-preview";

export default function Page() {
  if (process.env.NODE_ENV === "production") notFound();
  return (
    <Suspense>
      <ModelPickerPreviewPage />
    </Suspense>
  );
}
