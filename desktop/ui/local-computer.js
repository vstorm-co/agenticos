/** @typedef {(command: string, args?: Record<string, string>) => Promise<unknown>} Invoke */

const VIEWS = {
  no_docker: {
    title: "Install Docker to get started",
    message: "Open Docker Desktop after installing it, then check again.",
    actions: ["docker", "open-docker", "check"],
  },
  docker_stopped: {
    title: "Docker is ready to open",
    message: "Start Docker Desktop, then check again to set up your workspace.",
    actions: ["open-docker", "check"],
  },
  running: {
    title: "Your local workspace is ready",
    message:
      "AgenticOS is running on this computer. Connect to sign in and finish setting up desktop features.",
    actions: ["use", "create"],
  },
  ready: {
    title: "Ready to create your workspace",
    message:
      "Create an instance for your organization and choose its owner account.",
    actions: ["create"],
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
  const list = root.querySelector("[data-instance-list]");
  const instanceError = root.querySelector("[data-instance-error]");
  const overview = root.querySelector("[data-local-overview]");
  const create = root.querySelector("[data-local-create]");
  const heading = root.querySelector("[data-local-heading]");
  const lead = root.querySelector("[data-local-lead]");
  let instances = [];
  function showOverview() {
    root.dataset.view = "overview";
    overview.hidden = false;
    create.hidden = true;
    form.hidden = true;
    heading.textContent = "AgenticOS on this computer";
    lead.textContent = "A local workspace, managed from your menu bar.";
  }
  form
    .querySelector('[data-action="cancel-create"]')
    .addEventListener("click", () => {
      showOverview();
      actions
        .querySelector('[data-action="create"]')
        ?.focus({ preventScroll: true });
    });
  function showForm(instance) {
    root.dataset.view = "create";
    overview.hidden = true;
    create.hidden = false;
    form.hidden = false;
    heading.textContent = instance
      ? "Finish setting up your instance"
      : "Create a local instance";
    lead.textContent = "Your own workspace, running on this computer.";
    form.querySelector("[name=instance-id]").value = instance?.id ?? "";
    form.querySelector("[name=instance-name]").value = instance?.name ?? "";
    form.querySelector("[name=instance-name]").focus();
  }
  async function refreshInstances(request) {
    try {
      const answer = await invoke("local_instances");
      if (request !== generation || root.hidden) return;
      if (
        !Array.isArray(answer) ||
        answer.some(
          (row) =>
            !row ||
            typeof row.id !== "string" ||
            typeof row.name !== "string" ||
            typeof row.url !== "string" ||
            typeof row.installed !== "boolean" ||
            typeof row.running !== "boolean",
        )
      )
        throw new Error("The app could not read its local instances.");
      instances = answer;
      list.replaceChildren();
      for (const instance of instances) {
        const row = document.createElement("div");
        row.className = "instance-row";
        const description = document.createElement("div");
        const name = document.createElement("strong");
        name.textContent = instance.name;
        const hint = document.createElement("p");
        hint.textContent = `${instance.url} · ${!instance.installed ? "Setup unfinished" : instance.running ? "Running" : "Stopped"}`;
        description.append(name, hint);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "secondary";
        button.textContent = !instance.installed
          ? "Finish setup"
          : instance.running
            ? "Connect"
            : "Start and connect";
        button.dataset.instance = instance.id;
        row.append(description, button);
        list.append(row);
      }
      list.hidden = instances.length === 0;
      instanceError.hidden = true;
    } catch (error) {
      if (request !== generation || root.hidden) return;
      instanceError.hidden = false;
      instanceError.textContent = String(error);
    }
  }
  list.addEventListener("click", async (event) => {
    if (!(event.target instanceof Element)) return;
    const button = event.target.closest("[data-instance]");
    const instance = instances.find(
      (item) => item.id === button?.dataset.instance,
    );
    if (!instance || connecting) return;
    if (!instance.installed) {
      showForm(instance);
      return;
    }
    connecting = true;
    root.inert = true;
    button.disabled = true;
    button.textContent = "Connecting…";
    try {
      await invoke("use_local", { instanceId: instance.id });
    } catch (error) {
      instanceError.hidden = false;
      instanceError.textContent = String(error);
      connecting = false;
      root.inert = false;
      button.disabled = false;
      button.textContent = "Retry connection";
    }
  });
  let generation = 0;
  let connecting = false;
  function setBusy(busy) {
    card.setAttribute("aria-busy", String(busy));
  }
  function showActions(visible) {
    actions.hidden = false;
    const primary = ["use", "create", "docker", "open-docker", "check"].find(
      (action) => visible.includes(action),
    );
    for (const button of actions.querySelectorAll("[data-action]")) {
      button.hidden = !visible.includes(button.dataset.action);
      button.classList.toggle("primary", button.dataset.action === primary);
      button.classList.toggle("secondary", button.dataset.action !== primary);
    }
  }
  async function refresh() {
    const request = ++generation;
    showOverview();
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
      void refreshInstances(request);
      const view = VIEWS[status];
      card.dataset.state = status;
      title.textContent = view.title;
      message.textContent = view.message;
      showActions(view.actions);
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
    if (action === "create") showForm(null);
    if (action === "docker") {
      button.disabled = true;
      message.textContent = "Downloading Docker Desktop…";
      try {
        await invoke("download_docker");
        message.textContent =
          "Finish installing Docker Desktop, then open it and check again.";
      } catch (error) {
        message.textContent = String(error);
        report(error);
      } finally {
        button.disabled = false;
      }
    }
    if (action === "open-docker") {
      try {
        await invoke("open_docker");
        message.textContent =
          "Finish Docker Desktop's setup, then check again.";
      } catch (error) {
        message.textContent = String(error);
      }
    }
    if (action !== "use" || connecting) return;
    connecting = true;
    root.inert = true;
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
      root.inert = false;
      button.disabled = false;
      root.querySelector("[data-go]").disabled = false;
      delete button.dataset.busy;
      button.textContent = "Connect and continue";
      setBusy(false);
    }
  });
  return refresh;
}
