const showcase = document.querySelector('#clawdy-3d .stage');
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
