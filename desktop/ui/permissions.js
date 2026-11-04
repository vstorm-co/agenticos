/** @typedef {{supported: boolean, screen_capture: boolean, accessibility: boolean, microphone: boolean}} PermissionStatus */

/** @param {unknown} value @returns {PermissionStatus} */
function readStatus(value) {
  if (
    value === null ||
    typeof value !== "object" ||
    !("supported" in value) ||
    typeof value.supported !== "boolean" ||
    !("screen_capture" in value) ||
    typeof value.screen_capture !== "boolean" ||
    !("accessibility" in value) ||
    typeof value.accessibility !== "boolean" ||
    !("microphone" in value) ||
    typeof value.microphone !== "boolean"
  ) {
    throw new Error("The app could not read the system permission status.");
  }
  return value;
}

/**
 * Read status on entry and focus; only an explicit click may request a permission.
 * @param {HTMLElement} root
 * @param {(command: string, args?: Record<string, string>) => Promise<unknown>} invoke
 * @param {() => void} unsupported
 * @returns {() => Promise<void>}
 */
export function permissionStep(root, invoke, unsupported) {
  const error = root.querySelector(".error");
  const rows = [...root.querySelectorAll("[data-permission]")];
  /** @param {PermissionStatus} status */
  function render(status) {
    if (!status.supported) {
      unsupported();
      return;
    }
    for (const row of rows) {
      const key = row.dataset.permission;
      const granted = Boolean(status[key]);
      row.querySelector("[data-permission-status]").textContent = granted
        ? "Allowed"
        : "Not enabled";
      const button = row.querySelector("button");
      button.disabled = granted;
      button.textContent = granted
        ? "Allowed"
        : key === "microphone"
          ? "Allow"
          : "Open settings";
    }
  }
  async function refresh() {
    error.hidden = true;
    try {
      render(readStatus(await invoke("onboarding_permissions")));
    } catch (failure) {
      error.textContent = String(failure);
      error.hidden = false;
    }
  }
  for (const row of rows) {
    const button = row.querySelector("button");
    button.addEventListener("click", async () => {
      button.disabled = true;
      error.hidden = true;
      try {
        render(
          readStatus(
            await invoke("request_onboarding_permission", {
              permission: row.dataset.permission,
            }),
          ),
        );
      } catch (failure) {
        error.textContent = String(failure);
        error.hidden = false;
        button.disabled = false;
      }
    });
  }
  return refresh;
}
