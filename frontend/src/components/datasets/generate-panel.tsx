"use client";

import { useState } from "react";

import { GenerateCasesDialog } from "./generate-cases-dialog";
import { ProposedCases } from "./proposed-cases";

export function GeneratePanel({ datasetId }: { datasetId: string }) {
  const [generating, setGenerating] = useState(false);
  return (
    <>
      <ProposedCases datasetId={datasetId} canEdit onGenerate={() => setGenerating(true)} />
      {generating && (
        <GenerateCasesDialog datasetId={datasetId} open onOpenChange={setGenerating} />
      )}
    </>
  );
}
