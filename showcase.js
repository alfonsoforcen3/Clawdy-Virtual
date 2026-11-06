const showcase = document.querySelector('#clawdy-3d .stage');
const art = showcase.querySelector('.art');
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
let drawSignal;
let selectedSignal = 0;

new IntersectionObserver((entries, observer) => {
  if (!entries.some(entry => entry.isIntersecting)) return;
  observer.disconnect();
  import('./signal-renderer.js?v=890d9bbe').then(({ mountSignalScene }) => {
    drawSignal = mountSignalScene(art, showcase, reducedMotion);
    drawSignal?.(selectedSignal, false);
  }).catch(() => {
    // The illustration and signal controls remain available without WebGL.
  });
}).observe(showcase);

const signalButtons = [...showcase.querySelectorAll('[data-phase]')];
const signalPanels = [...showcase.querySelectorAll('[data-panel]')];
const signalIndex = showcase.querySelector('#phase-index');
const signalPhases = [
  {name: 'attention', label: '01 / YOUR TURN'},
  {name: 'working', label: '02 / WORKING'},
  {name: 'ready', label: '03 / READY'},
];

signalButtons.forEach((button, index) => {
  button.addEventListener('click', () => {
    const phase = signalPhases[index];
    if (index !== selectedSignal) drawSignal?.(index);
    selectedSignal = index;
    showcase.dataset.signalPhase = phase.name;
    signalIndex.textContent = phase.label;
    signalButtons.forEach((option, optionIndex) => {
      option.setAttribute('aria-pressed', String(optionIndex === index));
    });
    signalPanels.forEach((panel, panelIndex) => {
      panel.hidden = panelIndex !== index;
    });
  });
});
