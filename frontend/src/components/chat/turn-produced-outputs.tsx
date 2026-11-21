"use client";

import { memo, useMemo } from "react";
import type { ToolCall, TurnFileSource } from "@/types/chat";
import { useMediaSurface } from "@/lib/generated-media";
import { toolLookupName } from "@/lib/tool-identity";
import { pathArg } from "@/lib/tool-steps";
import { CodingAgentResult, parseCodingReport } from "./tool-results/coding-agent";
import { GeneratedImageResult, parseGeneratedImage } from "./tool-results/generated-image";
import { GeneratedSpeechResult, parseGeneratedSpeech } from "./tool-results/generated-speech";
import { GeneratedVideoResult, parseGeneratedVideo } from "./tool-results/generated-video";
import { DesktopScreenshotResult, parseDesktopScreenshot } from "./tool-results/desktop-screenshot";
import { WorkspaceFileCard } from "./tool-results/workspace";

const OUTPUT_TOOLS = new Set([
  "generate_image",
  "generate_speech",
  "generate_video",
  "computer_save_screenshot",
  "run_coding_agent",
  "write_file",
  "edit_file",
]);

/** Produced files and media belong to the answer, never inside diagnostic disclosures. */
export function TurnProducedOutputs({
  calls,
  fileSource,
}: {
  calls: readonly ToolCall[];
  fileSource?: TurnFileSource;
}) {
  const files = new Set<string>();
  return calls.map((call) => {
    if (call.status !== "completed" || !OUTPUT_TOOLS.has(toolLookupName(call))) return null;
    if (["write_file", "edit_file"].includes(toolLookupName(call))) {
      const path = pathArg(call.args);
      if (path === null || files.has(path)) return null;
      files.add(path);
      return <ProducedFile key={call.id} path={path} fileSource={fileSource} />;
    }
    return <ProducedOutput key={call.id} call={call} fileSource={fileSource} />;
  });
}

const ProducedFile = memo(WorkspaceFileCard);

const ProducedOutput = memo(function ProducedOutput({
  call,
  fileSource,
}: {
  call: ToolCall;
  fileSource?: TurnFileSource;
}) {
  const surface = useMediaSurface();
  const name = toolLookupName(call);
  const result = useMemo(
    () =>
      typeof call.result === "string"
        ? call.result
        : call.result === undefined
          ? ""
          : JSON.stringify(call.result),
    [call.result],
  );
  if (name === "generate_image") {
    const data = parseGeneratedImage(result, surface);
    return data && <GeneratedImageResult key={call.id} data={data} />;
  }
  if (name === "generate_speech") {
    const data = parseGeneratedSpeech(result, surface);
    return data && <GeneratedSpeechResult key={call.id} data={data} />;
  }
  if (name === "generate_video") {
    const data = parseGeneratedVideo(result, surface);
    return data && <GeneratedVideoResult key={call.id} data={data} />;
  }
  if (name === "computer_save_screenshot") {
    const data = parseDesktopScreenshot(result, surface);
    return data && <DesktopScreenshotResult key={call.id} data={data} />;
  }
  return parseCodingReport(result) === null ? null : (
    <CodingAgentResult toolCall={call} resultText={result} fileSource={fileSource} />
  );
});
