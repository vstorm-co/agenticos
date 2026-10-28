import { localComputerStep } from "./local-computer.js";
import { permissionStep } from "./permissions.js";

/**
 * The first-run onboarding: where AgenticOS lives for this person - a stack the
 * app sets up on this computer, or an organization's server - and getting there.
 * What comes after (blobby, shortcuts, notifications) is the console's own
 * connection review, `/desktop/readiness`, once a console answers.
 */

const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;

const STEPS = ["files", "download", "start", "owner"];

const screens = [...document.querySelectorAll("[data-screen]")];
const serverForm = document.getElementById("server-form");
const serverField = document.getElementById("server");
const localForm = document.getElementById("local-form");
const checkLocal = localComputerStep(
  document.querySelector('[data-screen="local"]'),
  invoke,
  report,
);

function report(message) {
  void invoke("page_error", { message: String(message) });
}
window.addEventListener("error", (event) => report(event.message));
window.addEventListener("unhandledrejection", (event) => report(event.reason));

const permissions = document.querySelector('[data-screen="permissions"]');
const refreshPermissions = permissionStep(permissions, invoke, () =>
  show("where"),
);
window.addEventListener("focus", () => {
  if (!permissions.hidden) void refreshPermissions();
});

function show(name) {
  for (const screen of screens) screen.hidden = screen.dataset.screen !== name;
  document.body.classList.toggle("busy", name === "progress");
  if (name === "local") void checkLocal();
  if (name === "permissions") void refreshPermissions();
  const first = [
    ...document.querySelectorAll(
      `[data-screen="${name}"] input, [data-screen="${name}"] button`,
    ),
  ].find((control) => !control.closest("[hidden]") && !control.disabled);
  if (first?.matches("input")) first.focus();
}

function showError(container, message) {
  const error = container.querySelector(".error");
  error.textContent = String(message);
  error.hidden = false;
}

function hideError(container) {
  container.querySelector(".error").hidden = true;
}

for (const button of document.querySelectorAll("[data-go]")) {
  button.addEventListener("click", () => show(button.dataset.go));
}

serverForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  hideError(serverForm);
  const submit = serverForm.querySelector(".primary");
  submit.disabled = true;
  submit.dataset.busy = "true";
  submit.textContent = "Connecting…";
  try {
    await invoke("connect", { url: serverField.value });
  } catch (message) {
    showError(serverForm, message);
    submit.disabled = false;
    delete submit.dataset.busy;
    submit.textContent = "Connect";
  }
});

function markSteps(current, failed = false) {
  const index = STEPS.indexOf(current);
  for (const item of document.querySelectorAll("[data-step]")) {
    const at = STEPS.indexOf(item.dataset.step);
    item.dataset.state =
      at < index || current === "done"
        ? "done"
        : at === index
          ? failed
            ? "failed"
            : "active"
          : "";
  }
}

let currentStep = "files";

localForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  hideError(localForm);
  const data = new FormData(localForm);
  const owner = {
    instance_name: String(data.get("instance-name")),
    instance_id: String(data.get("instance-id")) || null,
    organization: String(data.get("organization")),
    email: String(data.get("email")),
    password: String(data.get("password")),
    provider: String(data.get("provider")),
    api_key: String(data.get("api-key")) || null,
  };
  const progress = document.querySelector('[data-screen="progress"]');
  hideError(progress);
  document.querySelector("[data-progress-actions]").hidden = true;
  currentStep = "files";
  markSteps(currentStep);
  show("progress");
  try {
    await invoke("set_up_local", { owner });
  } catch (message) {
    markSteps(currentStep, true);
    showError(progress, message);
    document.querySelector("[data-progress-actions]").hidden = false;
  }
});

async function start() {
  await listen("docker:download", ({ payload }) => {
    const label = document.querySelector("[data-local-message]");
    if (payload && typeof payload.received === "number") {
      label.textContent =
        payload.total > 0
          ? `Downloading Docker Desktop… ${Math.min(100, Math.floor((payload.received / payload.total) * 100))}%`
          : `Downloading Docker Desktop… ${Math.floor(payload.received / 1024 / 1024)} MB`;
    }
  });
  await listen("local:progress", ({ payload }) => {
    currentStep = payload.step;
    markSteps(currentStep);
  });
  const [state, notice] = await Promise.all([
    invoke("onboarding_state"),
    invoke("startup_notice"),
  ]);
  if (state.server_url) serverField.value = state.server_url;
  // Somebody who has been through it - "Change Server…", or a server that
  // stopped answering - is asked where, not welcomed again.
  if (notice) {
    show(state.deployment === "local" ? "local" : "server");
    if (state.deployment !== "local") showError(serverForm, notice);
    return;
  }
  show(state.deployment ? "where" : "welcome");
}

start().catch(report);
