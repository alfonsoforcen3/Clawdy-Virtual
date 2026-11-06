const showcase = document.querySelector('#clawdy-3d .stage');
const art = showcase.querySelector('.art');
const canvas = art.querySelector('canvas');
const context = canvas.getContext('2d');
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
const signalButtons = [...showcase.querySelectorAll('[data-phase]')];
const signalPanels = [...showcase.querySelectorAll('[data-panel]')];
const signalIndex = showcase.querySelector('#phase-index');

const viewSize = 420;
const viewsPerRow = 7;
const lastView = 20;
const phases = [
  {name: 'attention', label: '01 / YOUR TURN', restView: 10},
  {name: 'working', label: '02 / WORKING', restView: 16},
  {name: 'ready', label: '03 / READY', restView: 8}
];
let phaseIndex = 0;
let view = phases[0].restView;
let motion;
let frame;
let drag;

function paintFrame(image, position, opacity = 1) {
  const index = Math.round(position);
  const x = index % viewsPerRow * viewSize;
  const y = Math.floor(index / viewsPerRow) * viewSize;
  context.globalAlpha = opacity;
  context.drawImage(image, x, y, viewSize, viewSize, 0, 0, viewSize, viewSize);
}

function draw(trail) {
  const image = phases[phaseIndex].image;
  if (!context || !image) {
    showcase.removeAttribute('data-views-ready');
    return;
  }

  context.clearRect(0, 0, viewSize, viewSize);
  if (trail !== undefined && Math.round(trail) !== Math.round(view)) paintFrame(image, trail, .33);
  paintFrame(image, view);
  showcase.setAttribute('data-views-ready', '');
}

function turnTo(target) {
  cancelAnimationFrame(frame);
  if (reducedMotion.matches || !phases[phaseIndex].image) {
    view = target;
    draw();
    return;
  }

  const from = view;
  const started = performance.now();
  function step(now) {
    const progress = Math.min(1, (now - started) / 620);
    const eased = progress * progress * (3 - 2 * progress);
    const previous = view;
    view = from + (target - from) * eased;
    draw(progress < 1 ? previous : undefined);
    if (progress < 1) frame = requestAnimationFrame(step);
  }
  frame = requestAnimationFrame(step);
}

function setView(next) {
  cancelAnimationFrame(frame);
  const previous = view;
  view = Math.max(0, Math.min(lastView, next));
  draw(reducedMotion.matches ? undefined : previous);
}

function loadViews() {
  for (const phase of phases) {
    const image = new Image();
    image.src = new URL('./assets/showcase-' + phase.name + '.webp?v=1', document.baseURI).href;
    image.decode().then(() => {
      phase.image = image;
      if (phases[phaseIndex] === phase) {
        draw();
      }
    }).catch(() => {
      // The illustrated fallback and signal controls remain usable.
    });
  }
}

if (context && 'IntersectionObserver' in window) {
  const observer = new IntersectionObserver(entries => {
    if (!entries.some(entry => entry.isIntersecting)) return;
    observer.disconnect();
    loadViews();
  }, {rootMargin: '160px'});
  observer.observe(showcase);
} else if (context) {
  loadViews();
}

signalButtons.forEach((button, index) => {
  button.addEventListener('click', () => {
    if (phaseIndex === index) return;
    const from = art.getBoundingClientRect();
    motion?.cancel();
    phaseIndex = index;
    const phase = phases[index];
    showcase.dataset.signalPhase = phase.name;
    signalIndex.textContent = phase.label;
    signalButtons.forEach((option, optionIndex) => {
      option.setAttribute('aria-pressed', String(optionIndex === index));
    });
    signalPanels.forEach((panel, panelIndex) => {
      panel.hidden = panelIndex !== index;
    });
    draw();
    turnTo(phase.restView);
    if (reducedMotion.matches || !art.animate) return;

    const shift = from.left - art.getBoundingClientRect().left;
    motion = art.animate([
      {transform: 'translateX(' + shift + 'px)', filter: 'blur(0)'},
      {offset: .42, filter: 'blur(' + (shift ? 2.3 : 1) + 'px)'},
      {transform: 'translateX(0)', filter: 'blur(0)'}
    ], {duration: 620, easing: 'cubic-bezier(.2,.7,.24,1)'});
  });
});

canvas.addEventListener('pointerdown', event => {
  if (!event.isPrimary || event.button !== 0) return;
  drag = {id: event.pointerId, x: event.clientX, view};
  canvas.setPointerCapture(event.pointerId);
});
canvas.addEventListener('pointermove', event => {
  if (drag?.id !== event.pointerId) return;
  setView(drag.view + (event.clientX - drag.x) / 8);
});
canvas.addEventListener('lostpointercapture', () => {
  drag = null;
  draw();
});
canvas.addEventListener('keydown', event => {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
  event.preventDefault();
  setView(view + (event.key === 'ArrowLeft' ? -1 : 1));
  draw();
});
reducedMotion.addEventListener('change', () => {
  motion?.cancel();
  turnTo(phases[phaseIndex].restView);
});
