const showcase = document.querySelector('#clawdy-3d .stage');
const art = showcase.querySelector('.art');
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
let motion;

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
    if (showcase.dataset.signalPhase === phase.name) return;
    const from = art.getBoundingClientRect();
    motion?.cancel();
    showcase.dataset.signalPhase = phase.name;
    signalIndex.textContent = phase.label;
    signalButtons.forEach((option, optionIndex) => {
      option.setAttribute('aria-pressed', String(optionIndex === index));
    });
    signalPanels.forEach((panel, panelIndex) => {
      panel.hidden = panelIndex !== index;
    });
    if (reducedMotion.matches || !art.animate) return;

    const to = art.getBoundingClientRect();
    const shift = from.left - to.left;
    const tilt = shift > 0 ? -13 : 13;
    motion = art.animate([
      { transform: 'translateX(' + shift + 'px)', filter: 'blur(0)' },
      { offset: .43, transform: 'translateX(' + shift * .35 + 'px) perspective(650px) rotateY(' + tilt + 'deg) scale(.98)', filter: 'blur(2.5px)' },
      { transform: 'translateX(0) perspective(650px) rotateY(0)', filter: 'blur(0)' }
    ], { duration: 550, easing: 'cubic-bezier(.2,.7,.24,1)' });
  });
});
