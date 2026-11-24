"use client";
import { use } from "react";
import { BrowserTeachingReview } from "@/components/browser/browser-teaching-review";
export default function TeachingReviewPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);
  return <BrowserTeachingReview sessionId={sessionId} />;
}
