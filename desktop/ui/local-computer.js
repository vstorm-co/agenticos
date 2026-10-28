/** @typedef {(command: string) => Promise<unknown>} Invoke */

const VIEWS = {
  no_docker: {
    title: "Install Docker to get started",
    message: "Open Docker Desktop after installing it, then check again.",
    actions: ["docker", "check"],
  },
  docker_stopped: {
    title: "Docker is ready to open",
    message: "Start Docker Desktop, then check again to set up your workspace.",
    actions: ["check"],
  },
  running: {
    title: "Your local workspace is ready",
    message:
      "AgenticOS is running on this computer. Connect to sign in and finish setting up desktop features.",
    actions: ["use"],
  },
  ready: {
    title: "Ready to create your workspace",
    message:
      "Add your organization and account below. The app will download and start AgenticOS for you.",
    actions: [],
  },
};

/**
 * Local setup keeps its status card mounted while probing and connecting.
 * @param {HTMLElement} root
 * @param {Invoke} invoke
 * @param {(message: unknown) => void} report
 * @returns {() => Promise<void>}
 */
export function localComputerStep(root, invoke, report) {
  const card = root.querySelector("[data-local-instance]");
  const title = root.querySelector("[data-local-title]");
  const message = root.querySelector("[data-local-message]");
  const actions = root.querySelector("[data-local-actions]");
  const form = root.querySelector("form");
  let generation = 0;
  let connecting = false;
  function setBusy(busy) {
    card.setAttribute("aria-busy", String(busy));
  }
  function showActions(visible) {
    actions.hidden = false;
    for (const button of actions.querySelectorAll("[data-action]")) {
      button.hidden = !visible.includes(button.dataset.action);
    }
  }
  async function refresh() {
    const request = ++generation;
    card.dataset.state = "checking";
    setBusy(true);
    title.textContent = "Checking this computer";
    message.textContent = "Looking for AgenticOS and Docker…";
    showActions([]);
    form.hidden = true;
    try {
      const status = await invoke("local_status");
      if (request !== generation || root.hidden) return;
      if (typeof status !== "string" || !Object.hasOwn(VIEWS, status))
        throw new Error("The app could not read this computer's status.");
      const view = VIEWS[status];
      card.dataset.state = status;
      title.textContent = view.title;
      message.textContent = view.message;
      showActions(view.actions);
      form.hidden = status !== "ready";
      if (status === "ready") form.querySelector("input")?.focus();
    } catch (error) {
      if (request !== generation || root.hidden) return;
      card.dataset.state = "error";
      title.textContent = "Could not check this computer";
      message.textContent = String(error);
      showActions(["check"]);
    } finally {
      if (request === generation) setBusy(false);
    }
  }
  actions.addEventListener("click", async (event) => {
    if (!(event.target instanceof Element)) return;
    const button = event.target.closest("[data-action]");
    const action = button?.dataset.action;
    if (action === "check") await refresh();
    if (action === "docker") await invoke("open_docker_download").catch(report);
    if (action !== "use" || connecting) return;
    connecting = true;
    button.disabled = true;
    root.querySelector("[data-go]").disabled = true;
    button.dataset.busy = "true";
    button.textContent = "Connecting…";
    setBusy(true);
    try {
      await invoke("use_local");
    } catch (error) {
      message.textContent = String(error);
      connecting = false;
      button.disabled = false;
      root.querySelector("[data-go]").disabled = false;
      delete button.dataset.busy;
      button.textContent = "Connect and continue";
      setBusy(false);
    }
  });
  return refresh;
}
