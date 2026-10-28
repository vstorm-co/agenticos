import { permissionStep } from "./permissions.js";

/**
 * The first-run onboarding: where AgenticOS lives for this person - a stack the
 * app sets up on this computer, or an organization's server - and getting there.
 * What comes after (blobby, shortcuts, notifications) is the console's own
 * welcome, `/desktop/welcome`, which the shell opens once a console answers.
 */

const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;

const STEPS = ["files", "download", "start", "owner"];

const screens = [...document.querySelectorAll("[data-screen]")];
const serverForm = document.getElementById("server-form");
const serverField = document.getElementById("server");
const localForm = document.getElementById("local-form");
const localMessage = document.querySelector("[data-local-message]");
const localActions = document.querySelector("[data-local-actions]");

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
  const first = document.querySelector(
    `[data-screen="${name}"] input, [data-screen="${name}"] .primary`,
  );
  first?.focus();
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
  try {
    await invoke("connect", { url: serverField.value });
  } catch (message) {
    showError(serverForm, message);
    submit.disabled = false;
  }
});

/** What the local screen says and offers, for each state of this computer. */
const LOCAL = {
  no_docker: {
    message:
      "AgenticOS runs in Docker, which is not on this computer yet. Install Docker Desktop, open it, then check again.",
    actions: ["docker", "check"],
  },
  docker_stopped: {
    message:
      "Docker is installed but not running. Open Docker Desktop, then check again.",
    actions: ["check"],
  },
  running: {
    message: "AgenticOS is already running on this computer.",
    actions: ["use"],
  },
  ready: {
    message:
      "Create your organization. AgenticOS downloads, starts and keeps itself up to date from the menu bar.",
    actions: [],
  },
};

async function checkLocal() {
  localMessage.textContent = "Checking this computer…";
  localActions.hidden = true;
  localForm.hidden = true;
  let status;
  try {
    status = await invoke("local_status");
  } catch (message) {
    localMessage.textContent = String(message);
    localActions.hidden = false;
    return;
  }
  const view = LOCAL[status];
  localMessage.textContent = view.message;
  for (const button of localActions.querySelectorAll("[data-action]")) {
    button.hidden = !view.actions.includes(button.dataset.action);
  }
  localActions.hidden = view.actions.length === 0;
  localForm.hidden = status !== "ready";
  if (status === "ready") document.getElementById("organization").focus();
}

localActions.addEventListener("click", async (event) => {
  const action = event.target.closest("[data-action]")?.dataset.action;
  if (action === "check") await checkLocal();
  if (action === "docker") await invoke("open_docker_download").catch(report);
  if (action === "use") {
    try {
      await invoke("use_local");
    } catch (message) {
      localMessage.textContent = String(message);
    }
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
