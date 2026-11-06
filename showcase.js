const story = document.querySelector('#clawdy-3d');
const showcase = story.querySelector('.stage');
const art = showcase.querySelector('.art');
const canvas = art.querySelector('canvas');
const context = canvas.getContext('2d');
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
const signalButtons = [...showcase.querySelectorAll('[data-phase]')];
const signalPanels = [...showcase.querySelectorAll('[data-panel]')];
const signalIndex = showcase.querySelector('#phase-index');

const viewSize = 420;
const viewsPerRow = 7;
const viewsPerTurn = 42;
const scrollMotion = matchMedia('(prefers-reduced-motion: no-preference) and (min-height: 501px)');
const phases = [
  {name: 'attention', label: '01 / YOUR TURN'},
  {name: 'working', label: '02 / WORKING'},
  {name: 'ready', label: '03 / READY'}
];
let phaseIndex = 0;
let view = 0;
let scrollProgress;
let scrollFrame;
let settle;
let motion;
let frame;
let drag;

function paintFrame(image, position, opacity = 1) {
  const index = ((Math.round(position) % viewsPerTurn) + viewsPerTurn) % viewsPerTurn;
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

const clamp = value => Math.max(0, Math.min(1, value));
const smooth = value => value * value * (3 - 2 * value);
const travel = () => Math.max(1, story.offsetHeight - showcase.offsetHeight);

function setView(next, withTrail = true) {
  const previous = view;
  view = next;
  draw(withTrail && !reducedMotion.matches ? previous : undefined);
  clearTimeout(settle);
  if (withTrail && !reducedMotion.matches) settle = setTimeout(() => draw(), 85);
}

function updateScroll() {
  scrollFrame = 0;
  if (!scrollMotion.matches) return;

  const progress = clamp(-story.getBoundingClientRect().top / travel());
  if (progress === scrollProgress) return;
  const moved = scrollProgress !== undefined;
  scrollProgress = progress;
  showPhase(progress < .25 ? 0 : progress < .75 ? 1 : 2, moved);
  const turn = Math.min(1, Math.floor(progress * 2));
  const blend = smooth(clamp((progress * 2 - turn - .25) / .5));
  if (!drag) setView((turn + blend) * viewsPerTurn, moved);
}

function scheduleScroll() {
  if (scrollMotion.matches && !scrollFrame) scrollFrame = requestAnimationFrame(updateScroll);
}

function updateScrollMode() {
  story.toggleAttribute('data-scroll-motion', scrollMotion.matches);
  scrollProgress = undefined;
  motion?.cancel();
  if (scrollMotion.matches) scheduleScroll();
  else setView(0, false);
}

function loadViews() {
  for (const phase of phases) {
    const image = new Image();
    image.src = new URL('./assets/showcase-' + phase.name + '.webp?v=2', document.baseURI).href;
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

function showPhase(index, animate = false) {
  if (phaseIndex === index) return;
  motion?.cancel();
  const left = animate ? art.getBoundingClientRect().left : 0;
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
  if (!animate || !art.animate) return;

  const shift = left - art.getBoundingClientRect().left;
  if (shift) motion = art.animate([
    {transform: 'translateX(' + shift + 'px)'},
    {transform: 'translateX(0)'}
  ], {duration: 480, easing: 'cubic-bezier(.2,.7,.24,1)'});
}

signalButtons.forEach((button, index) => {
  button.addEventListener('click', () => {
    if (scrollMotion.matches) {
      const top = story.getBoundingClientRect().top + scrollY + travel() * index / 2;
      window.scrollTo({top, behavior: 'smooth'});
    } else {
      showPhase(index);
      setView(0, false);
    }
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
  setView(view + (event.key === 'ArrowLeft' ? -1 : 1), false);
});
scrollMotion.addEventListener('change', updateScrollMode);
addEventListener('scroll', scheduleScroll, {passive: true});
addEventListener('resize', scheduleScroll, {passive: true});
updateScrollMode();
