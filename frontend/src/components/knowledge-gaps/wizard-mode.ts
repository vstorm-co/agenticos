import { createContext, useContext } from "react";

/**
 * True inside the Improve wizard, where a topic is reviewed to add its document:
 * links that leave the wizard - to a run, a dataset, the drafter - are not offered.
 */
export const InImproveWizard = createContext(false);

export function useInImproveWizard(): boolean {
  return useContext(InImproveWizard);
}
