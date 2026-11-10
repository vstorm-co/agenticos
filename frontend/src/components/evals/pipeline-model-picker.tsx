"use client";

import { useState, type ComponentProps } from "react";
import { useTranslations } from "next-intl";

import { ModelProfilePicker } from "@/components/agents/model-profile-picker";
import { usableForAgents } from "@/lib/model-profiles";
import { PipelineProfileSelect } from "./pipeline-profile-select";
import { MoreOptions } from "@/components/ui/more-options";

type PipelineModelPickerProps = ComponentProps<typeof ModelProfilePicker>;

/** Pipeline setup chooses an existing model first; creation stays available on demand. */
export function PipelineModelPicker({ allowAdd, ...props }: PipelineModelPickerProps) {
  const t = useTranslations("agents");
  const [adding, setAdding] = useState(false);
  const [firstCreation, setFirstCreation] = useState<"pending" | "open" | "done">("pending");
  if (firstCreation === "pending" && props.profilesStatus === "loaded") {
    setFirstCreation(allowAdd && props.profiles.length === 0 ? "open" : "done");
  }

  // A refreshed list must not unmount the first creation before its selection callback runs.
  if (firstCreation === "open" && allowAdd) {
    return (
      <ModelProfilePicker
        {...props}
        allowAdd
        onChange={(value) => {
          props.onChange(value);
          setFirstCreation("done");
        }}
      />
    );
  }

  return (
    <div className="min-w-0 space-y-3">
      {props.profilesStatus === "loaded" &&
      props.profiles.some((profile) => usableForAgents(profile) || profile.id === props.value) ? (
        <PipelineProfileSelect
          profiles={props.profiles}
          value={props.value}
          onChange={props.onChange}
          disabled={props.disabled}
        />
      ) : (
        <ModelProfilePicker {...props} />
      )}
      {allowAdd && (
        <MoreOptions label={t("addModel")} open={adding} onOpenChange={setAdding}>
          <ModelProfilePicker
            {...props}
            allowAdd
            onChange={(value) => {
              props.onChange(value);
              setAdding(false);
            }}
          />
        </MoreOptions>
      )}
    </div>
  );
}
