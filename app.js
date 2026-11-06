"use strict";
// Only the canonical Pages URL may generate public links to simulated scenes.
const shareDeployment = Object.freeze({ reviewed: true, publicDemoUrl: "https://alfonsoforcen3.github.io/Clawdy-Virtual/" });
const publicSourceUrl = "https://github.com/alfonsoforcen3/Clawdy-Virtual";
const states = Object.freeze({
  working: { label: "ON IT", title: "Ideas in motion.", message: "Your chats are working. This moment is yours.", detail: "Two simulated chats are working. WIP counts working chats; the app labels show who is working.", color: "amber", wip: "2 WIP", providers: "Codex · Claude Code", target: "None", action: false },
  attention: { label: "YOUR TURN", title: "A little help?", message: "A Codex chat needs your attention.", detail: "Codex needs your attention. The 1 WIP · Claude Code label names the other chat still working, not the attention target. This question card stays until you close it or choose simulated Open chat, even if the lights change.", color: "red", wip: "1 WIP", providers: "Claude Code", target: "Codex", action: true },
  ready: { label: "ALL CLEAR", title: "Tiny victory lap.", message: "All tracked chats are ready or finished.", detail: "Green means the simulated tracked work is ready. WIP and working-app indicators clear.", color: "green", wip: "0 WIP", providers: "", target: "None", action: false },
  error: { label: "NEEDS A LOOK", title: "A plot twist.", message: "A Codex chat reported an error.", detail: "Codex reported an error. Steady red means error; an input request blinks red. With Reduce Motion, the input signal stays steady.", color: "red", wip: "0 WIP", providers: "", target: "Codex", action: true }
});
function validState(key) { return typeof key === "string" && Object.prototype.hasOwnProperty.call(states, key); }
function stateFromUrl(href) {
  try {
    const values = new URL(href).searchParams.getAll("demo");
    return values.length === 1 && validState(values[0]) ? values[0] : "working";
  } catch { return "working"; }
}
function isLocalPreview(url) {
  return url.protocol === "file:" || url.hostname === "localhost" || url.hostname.endsWith(".localhost") || /^127\./.test(url.hostname) || ["[::1]", "::1"].includes(url.hostname);
}
function reviewedDemoUrl(href, config) {
  if (!config || config.reviewed !== true || typeof config.publicDemoUrl !== "string") return null;
  try {
    const configured = new URL(config.publicDemoUrl);
    const current = new URL(href);
    const host = configured.hostname;
    if (configured.protocol !== "https:" || !host.includes(".") || host.includes(":") || /^\d+\./.test(host) || /\.(localhost|local|test|example|invalid)$/.test(host) || isLocalPreview(configured) || configured.username || configured.password || configured.search || configured.hash || configured.port) return null;
    if (isLocalPreview(current) || configured.origin !== current.origin || configured.pathname !== current.pathname) return null;
    return configured;
  } catch { return null; }
}
function sharePayload(href, key, config = shareDeployment) {
  const stateKey = validState(key) ? key : "working";
  const state = states[stateKey];
  const published = reviewedDemoUrl(href, config);
  if (published) {
    published.searchParams.set("demo", stateKey);
    published.hash = "experience";
    return { mode: "public", title: "Clawdy — stop checking on your AI", text: `Try Clawdy’s simulated ${state.label.toLowerCase()} scene: menu-bar traffic lights for local AI coding work. Browser illustration, not a live app connection. Mac source prototype; no signed installer.`, url: published.href, boundary: "Share this simulated scene. No app connection or installation required to view the demo." };
  }
  let local = false;
  try { local = isLocalPreview(new URL(href)); } catch { /* Unknown locations stay unpublished. */ }
  return { mode: local ? "preview" : "unpublished", title: "Meet Clawdy", text: `Clawdy is a Mac source prototype for menu-bar traffic lights and attention cards for local AI coding chats. The ${state.label.toLowerCase()} scene I explored is simulated; its interactive preview is not published. Live status needs an already-running local companion. No signed consumer installer is available. Explore the public source:`, url: publicSourceUrl, boundary: local ? "Preview link—works only on this computer. Copy an introduction and the public source instead." : "This interactive preview isn’t published for sharing. Copy an introduction and the public source instead." };
}
async function deliverSharePayload(payload, actions) {
  const text = `${payload.text}\n${payload.url}`;
  if (payload.mode === "public" && typeof actions.share === "function") {
    try {
      await actions.share({ title: payload.title, text: payload.text, url: payload.url });
      return { outcome: "shared" };
    } catch (error) {
      if (error && error.name === "AbortError") return { outcome: "cancelled" };
    }
  }
  let timeout;
  try {
    await Promise.race([actions.copy(text), new Promise((_, reject) => { timeout = setTimeout(() => reject(new Error("Clipboard timeout")), 1500); })]);
    return { outcome: "copied" };
  } catch { return { outcome: "manual", text }; }
  finally { clearTimeout(timeout); }
}
// Pure synthetic-demo state. Nothing is persisted or sourced from real chats.
function createDemoState() { return { current: "working", pending: null, visible: true, hoverDismissed: false, oneLeft: false }; }
function reduceDemoState(model, event) {
  if (event.type === "select") {
    const key = validState(event.key) ? event.key : "working";
    const newEpisode = key !== model.current || event.explicit === true;
    return { current: key, pending: states[key].action && newEpisode ? key : model.pending,
      visible: model.pending !== null || newEpisode ? true : model.visible,
      hoverDismissed: newEpisode ? false : model.hoverDismissed, oneLeft: key === "working" && event.oneLeft === true };
  }
  if (["close", "acknowledge"].includes(event.type)) return { ...model, pending: null, visible: false, hoverDismissed: true };
  if (event.type === "hover") return model.hoverDismissed ? model : { ...model, visible: true };
  if (["outside", "leave"].includes(event.type)) return model.pending ? model : { ...model, visible: false };
  if (event.type === "toggle") return model.visible ? reduceDemoState(model, { type: "close" }) : { ...model, visible: true };
  return model;
}
function demoPresentation(model) {
  const current = model.oneLeft ? { ...states.working, wip: "1 WIP", providers: "Codex", title: "One done. One thinking.", message: "One chat finished; Codex is still working.", detail: "One of two simulated chats finished. The light stays amber because Codex is still working. One completion doesn’t hide another chat’s work." } : states[model.current];
  const recent = model.pending !== null && model.pending !== model.current;
  const held = model.pending ? states[model.pending] : current;
  const alertName = model.pending === "error" ? "error" : "question";
  const card = recent ? { ...held, label: `RECENT ${alertName.toUpperCase()}`, title: `Recent ${alertName}.`, message: `An earlier Codex ${alertName} is saved here until you open or close it.` } : held;
  return { current, card, recent, target: model.pending ? held.target : "None", action: model.pending !== null };
}
function initClawdyPage() {
  const desk = document.querySelector("#experience");
  const card = document.querySelector("#demo-card");
  const menu = document.querySelector("#menu-preview");
  const feedback = document.querySelector("#demo-feedback");
  const announcement = document.querySelector("#demo-announcement");
  const action = document.querySelector("#open-chat");
  const shareButton = document.querySelector("#share-demo");
  const shareFeedback = document.querySelector("#share-feedback");
  const manual = document.querySelector("#share-manual");
  let currentState = stateFromUrl(location.href);
  let model = { ...createDemoState(), visible: false };
  function renderCard() {
    const view = demoPresentation(model);
    const state = view.card;
    card.hidden = !model.visible;
    menu.setAttribute("aria-expanded", String(model.visible));
    menu.setAttribute("aria-label", `${model.visible ? "Hide" : "Show"} simulated Clawdy status card`);
    document.querySelector("#demo-label").textContent = state.label;
    document.querySelector("#demo-title").textContent = state.title;
    document.querySelector("#demo-message").textContent = state.message;
    document.querySelector("#demo-dot").className = "status-dot " + state.color + (model.pending === "attention" && !view.recent ? " blink" : "");
    action.hidden = !view.action;
    document.querySelector("#card-foot").textContent = view.action ? `Saved until Open chat or close · current status: ${view.current.label.toLowerCase()} · simulated` : "Simulated status · no live apps connected";
    announcement.textContent = `Simulated current status: ${view.current.label.toLowerCase()}. ${view.current.wip}. Working applications: ${view.current.providers || "none"}. Saved attention target: ${view.target}.${view.recent ? " Recent alert remains available." : ""}`;
  }
  function cardEvent(type) { model = reduceDemoState(model, { type }); renderCard(); }
  function updateSharing() {
    const payload = sharePayload(location.href, currentState);
    document.querySelector("#share-boundary").textContent = payload.boundary;
    shareButton.textContent = payload.mode === "public" ? "Share this demo ↗" : "Copy intro + source ↗";
    document.querySelector("#share-state").textContent = `Selected scene: ${states[currentState].label.toLowerCase()} · simulated`;
    shareFeedback.textContent = "";
    manual.hidden = true;
    manual.value = "";
    document.querySelector("#share-manual-label").hidden = true;
  }
  function setState(key, updateUrl = true, oneLeft = false) {
    currentState = validState(key) ? key : "working";
    model = reduceDemoState(model, { type: "select", key: currentState, explicit: updateUrl, oneLeft });
    if (!model.pending) model.visible = false;
    const state = demoPresentation(model).current;
    desk.dataset.scene = currentState;
    const selected = desk.querySelector(`[data-state="${currentState}"]`);
    desk.querySelectorAll("[data-state]").forEach(button => button.setAttribute("aria-pressed", String(button === selected)));
    const sceneLabel = selected.textContent.trim();
    desk.querySelectorAll("[data-desk-label]").forEach(label => { label.textContent = sceneLabel; });
    desk.querySelectorAll("[data-desk-wip]").forEach(label => { label.textContent = state.wip; });
    desk.querySelector("#desk-oled-status").textContent = state.label;
    document.querySelector("#demo-wip").textContent = state.wip;
    const providers = document.querySelector("#demo-providers");
    providers.textContent = state.providers;
    providers.hidden = !state.providers;
    desk.querySelectorAll(".desk-scene .lamp").forEach(lamp => {
      lamp.classList.toggle("on", lamp.classList.contains(state.color));
      lamp.classList.toggle("blink", currentState === "attention" && lamp.classList.contains("red"));
    });
    document.querySelector("#finish-demo").hidden = currentState !== "working" || oneLeft;
    feedback.textContent = "";
    if (updateUrl) {
      try { const url = new URL(location.href); url.searchParams.set("demo", currentState); history.replaceState(null, "", url.href); } catch { /* File/restricted previews remain usable. */ }
    }
    updateSharing();
    renderCard();
  }
  desk.querySelectorAll("[data-state]").forEach(button => button.addEventListener("click", () => setState(button.dataset.state)));
  document.querySelector("#finish-demo").addEventListener("click", () => { setState("working", true, true); document.querySelector("[data-state=working]").focus({ preventScroll: true }); });
  menu.addEventListener("click", () => cardEvent("toggle"));
  menu.addEventListener("pointerenter", event => { if (event.pointerType !== "touch") cardEvent("hover"); });
  document.querySelector(".interactive-preview").addEventListener("pointerleave", () => cardEvent("leave"));
  document.addEventListener("pointerdown", event => { if (!card.contains(event.target) && !menu.contains(event.target)) cardEvent("outside"); });
  document.querySelector("#dismiss-card").addEventListener("click", () => { cardEvent("close"); menu.focus({ preventScroll: true }); });
  action.addEventListener("click", () => {
    cardEvent("acknowledge");
    menu.focus({ preventScroll: true });
    const message = "Demo only: this would open the verified local Codex attention chat. No app was launched.";
    feedback.textContent = message;
    announcement.textContent = message;
    document.querySelector("#card-foot").textContent = "Simulated action complete · no app launched";
  });
  shareButton.disabled = false;
  shareButton.addEventListener("click", async () => {
    const payload = sharePayload(location.href, currentState);
    // Always show the exact safe payload after an explicit click. Some embedded
    // browsers resolve clipboard writes without making text available to paste.
    manual.value = `${payload.text}\n${payload.url}`;
    manual.hidden = false;
    document.querySelector("#share-manual-label").hidden = false;
    shareButton.disabled = true;
    try {
      const result = await deliverSharePayload(payload, {
        share: typeof navigator.share === "function" ? data => navigator.share(data) : null,
        copy: text => navigator.clipboard.writeText(text)
      });
      if (result.outcome === "shared") shareFeedback.textContent = "Share request completed.";
      else if (result.outcome === "cancelled") shareFeedback.textContent = "Sharing cancelled. Nothing was copied.";
      else if (result.outcome === "copied") shareFeedback.textContent = payload.mode === "public" ? "Copy requested. The simulated scene link is also shown below." : "Copy requested. The introduction and public source are shown below. No preview URL is included.";
      else {
        manual.value = result.text;
        manual.hidden = false;
        document.querySelector("#share-manual-label").hidden = false;
        shareFeedback.textContent = "Clipboard unavailable. Select and copy the introduction below.";
        manual.focus();
        manual.select();
      }
    } finally { shareButton.disabled = false; }
  });
  const coffeeDialog = document.querySelector("#coffee-dialog");
  document.querySelector("#coffee-button").addEventListener("click", () => coffeeDialog.showModal());
  ["#close-coffee", "#coffee-done"].forEach(selector => document.querySelector(selector).addEventListener("click", () => coffeeDialog.close()));
  coffeeDialog.addEventListener("click", event => { if (event.target === coffeeDialog) { const rect = coffeeDialog.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) coffeeDialog.close(); } });
  document.addEventListener("keydown", event => { if (event.key === "Escape" && !coffeeDialog.open && !card.hidden) { cardEvent("close"); menu.focus({ preventScroll: true }); } });
  window.addEventListener("popstate", () => setState(stateFromUrl(location.href), false));
  setState(currentState, false);
}
if (typeof module !== "undefined" && module.exports) module.exports = { states, validState, stateFromUrl, isLocalPreview, reviewedDemoUrl, sharePayload, deliverSharePayload, createDemoState, reduceDemoState, demoPresentation };
if (typeof document !== "undefined") initClawdyPage();
