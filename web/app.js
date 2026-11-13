"use strict";
const q = (selector) => document.querySelector(selector);
const local = ["127.0.0.1", "localhost"].includes(location.hostname);
const dialog = q("dialog");
document
  .querySelectorAll(".preview")
  .forEach((button) =>
    button.addEventListener("click", () => dialog.showModal()),
  );
q("#close-dialog").onclick = q("#dismiss").onclick = () => dialog.close();
document.querySelectorAll("[data-toy]").forEach((button) =>
  button.addEventListener("click", () => {
    const duck = button.dataset.toy === "duck";
    document.body.classList.toggle("duck", duck);
    document.querySelectorAll("[data-name]").forEach((node) => {
      node.textContent = duck ? "CyberDuck" : "Clawdy";
    });
    document
      .querySelectorAll("[data-toy]")
      .forEach((node) =>
        node.setAttribute("aria-pressed", String(node === button)),
      );
    q(".toy").setAttribute(
      "aria-label",
      "Illustration of " + (duck ? "CyberDuck" : "Clawdy"),
    );
  }),
);
function render(data) {
  const valid = data.connected === true && data.stale === false;
  q("#connection").textContent = valid ? "Current board report received" : "Waiting for your Clawdy";
  q("#connection-dot").classList.toggle("online", valid);
  const modes = { G: "Ready", Y: "Working", B: "Your attention", R: "Error", O: "Lights off" };
  q("#light-state").textContent = valid ? (modes[data.mode] || "Unknown") : "Waiting";
  q("#transport").textContent = valid ? ({ ble: "Bluetooth", usb: "USB", serial: "USB" }[data.transport] || "Unknown") : "—";
  q("#firmware").textContent = valid && typeof data.firmware === "string" ? data.firmware.slice(0, 80) : "—";
  q("#display-phase").textContent = valid && typeof data.display_phase === "string" ? data.display_phase.slice(0, 40) : "—";
  const age = data.age_seconds;
  q("#sample-age").textContent = valid && Number.isFinite(age) && age >= 0 ? "UPDATED " + age + "s AGO" : "NO CURRENT REPORT";
  q("#status-note").textContent = valid ? "This is your board’s reported light state. Provider and visible-light checks remain separate." : "Check USB power, range and Bluetooth access. A stale report is never shown as live.";
}
async function refresh() {
  try {
    const response = await fetch("/api/status", {
      cache: "no-store",
      signal: AbortSignal.timeout(4000),
    });
    if (!response.ok) throw new Error("Bridge unavailable");
    render(await response.json());
  } catch {
    render({ connected: false, stale: true });
  }
}
if (local) {
  refresh();
  setInterval(refresh, 5000);
  const resetBtn = q("#reset-sessions");
  if (resetBtn) {
    resetBtn.hidden = false;
    resetBtn.addEventListener("click", async () => {
      try {
        resetBtn.disabled = true;
        resetBtn.textContent = "Clearing…";
        const response = await fetch("/api/reset", { method: "POST" });
        if (!response.ok) throw new Error("Reset failed");
        setTimeout(() => {
          resetBtn.disabled = false;
          resetBtn.textContent = "Clear sessions";
          refresh();
        }, 500);
      } catch (e) {
        resetBtn.disabled = false;
        resetBtn.textContent = "Retry clearing sessions";
      }
    });
  }
} else {
  q("#connection").textContent = "Live device status stays on your laptop";
  q("#status-note").textContent =
    "Open the local dashboard for your Clawdy’s actual connection and light status. This static page does not connect to your laptop.";
  q("#local-link").hidden = false;
}
