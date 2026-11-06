const story = document.querySelector('#clawdy-3d');
const stage = story.querySelector('.stage');
const art = stage.querySelector('.art');
const canvas = art.querySelector('canvas');
const ctx = canvas.getContext('2d');
const panels = [...stage.querySelectorAll('[data-panel]')];
const buttons = [...stage.querySelectorAll('[data-phase]')];
const phaseIndex = stage.querySelector('#phase-index');
const progress = stage.querySelector('.progress i');

const reduced = matchMedia('(prefers-reduced-motion: reduce)');
const compact = matchMedia('(max-height: 500px)');
const wide = matchMedia('(min-width: 900px) and (min-height: 650px) and (min-aspect-ratio: 4/3)');
const phases = [
  {key: 'attention', label: 'YOUR TURN', ink: '#a0382c', tint: '#e9ad9e', wash: '#f5e3dd'},
  {key: 'working', label: 'WORKING', ink: '#80500a', tint: '#eac775', wash: '#f7ebcf'},
  {key: 'ready', label: 'READY', ink: '#296442', tint: '#a4cba7', wash: '#e2efe1'}
];
const sheets = new Map();
const tile = canvas.width;
const views = 42;
const clamp = value => Math.max(0, Math.min(1, value));
const smooth = value => value * value * (3 - 2 * value);
const staticStage = () => reduced.matches || compact.matches;
const travel = () => Math.max(1, story.offsetHeight - stage.offsetHeight);
let selected = 0, shown = -1, pose = 0, target = 0, last = 0, frame = 0, visible = true;
let winkStarted = null;
let lastPaint;

function read() {
  target = staticStage() ? selected / 2 : clamp(-story.getBoundingClientRect().top / travel());
}

function schedule() {
  if (!frame && visible && !document.hidden) frame = requestAnimationFrame(tick);
}

function paint(sheet, index, opacity = 1) {
  ctx.globalAlpha = opacity;
  ctx.drawImage(sheet, (index % 7) * tile, Math.floor(index / 7) * tile, tile, tile, 0, 0, tile, tile);
}

function draw(phase, interval, blend, angle, wink) {
  const view = Math.round(angle * views) % views;
  const from = sheets.get(phases[interval].key);
  const to = sheets.get(phases[interval + 1].key);
  const active = sheets.get(phases[phase].key);
  if (!active) {
    art.removeAttribute('data-ready');
    return;
  }
  if (lastPaint?.view === view && lastPaint.blend === blend && lastPaint.wink === wink && lastPaint.active === active && lastPaint.from === from && lastPaint.to === to) return;
  lastPaint = {view, blend, wink, active, from, to};
  ctx.clearRect(0, 0, tile, tile);
  if (wink && sheets.has('wink')) paint(sheets.get('wink'), wink);
  else if (from && to && blend > 0 && blend < 1) {
    paint(from, view);
    paint(to, view, blend);
  } else paint(active, view);
  art.setAttribute('data-ready', '');
}

function update(now) {
  const phase = pose < .25 ? 0 : pose < .75 ? 1 : 2;
  if (phase !== shown) {
    shown = phase;
    stage.dataset.signalPhase = phases[phase].key;
    phaseIndex.textContent = '0' + (phase + 1) + ' / ' + phases[phase].label;
    panels.forEach((panel, index) => { panel.hidden = index !== phase; });
    buttons.forEach((button, index) => button.setAttribute('aria-pressed', String(index === phase)));
  }

  const interval = Math.min(1, Math.floor(pose * 2));
  const blend = smooth(clamp((pose * 2 - interval - .25) / .5));
  for (const [property, color] of [['--tint', 'tint'], ['--wash', 'wash'], ['--signal', 'ink']]) {
    const from = phases[interval][color];
    const to = phases[interval + 1][color];
    const mix = 'color-mix(in srgb-linear, ' + from + ', ' + to + ' ' + blend * 100 + '%)';
    stage.style.setProperty(property, CSS.supports('color', mix) ? mix : phases[phase][color]);
  }
  progress.style.transform = 'scaleX(' + pose + ')';
  const split = wide.matches && !staticStage();
  const shift = split ? (interval === 0 ? -1 + 2 * blend : 1 - 2 * blend) : 0;
  art.style.setProperty('--model-shift', shift * 24 + '%');
  stage.style.setProperty('--story-copy', smooth(Math.abs(2 * blend - 1)));

  if (staticStage() || phase !== 2) winkStarted = null;
  else if (pose >= .985 && winkStarted === null && sheets.has('wink')) winkStarted = now;
  const winkTime = winkStarted === null ? 1 : clamp((now - winkStarted) / 480);
  const wink = Math.round(6 * smooth(1 - Math.abs(2 * winkTime - 1)));
  if (ctx) draw(phase, interval, blend, staticStage() ? 0 : interval + blend, wink);
}

function tick(now) {
  frame = 0;
  const dt = last ? Math.min(.064, (now - last) / 1000) : .016;
  last = now;
  pose = staticStage() ? target : pose + (target - pose) * (1 - Math.exp(-dt * 14));
  if (Math.abs(target - pose) < .0002) pose = target;
  update(now);
  if (pose !== target || (winkStarted !== null && now - winkStarted < 480)) schedule();
  else last = 0;
}

function resize() {
  const horizontal = wide.matches && !staticStage() ? .168 : .093;
  // Match the archived orthographic camera using the baked square view.
  const artSize = .126 * Math.min(art.clientHeight / .079, art.clientWidth / horizontal);
  art.style.setProperty('--art-size', artSize + 'px');
  read();
  schedule();
}

function loadViews() {
  if (!ctx) return;
  for (const key of [...phases.map(phase => phase.key), 'wink']) {
    const image = new Image();
    image.src = new URL('./assets/showcase-' + key + '.webp?v=stage-2', document.baseURI).href;
    image.decode().then(() => {
      if (image.naturalWidth !== 7 * tile || image.naturalHeight !== (key === 'wink' ? tile : 6 * tile)) return;
      sheets.set(key, image);
      schedule();
    }).catch(() => { /* The original still remains available. */ });
  }
}

buttons.forEach((button, index) => button.addEventListener('click', () => {
  selected = index;
  if (staticStage()) {
    read();
    schedule();
    return;
  }
  const top = story.getBoundingClientRect().top + scrollY + travel() * index / 2;
  window.scrollTo({top, behavior: 'smooth'});
}));

addEventListener('scroll', () => { read(); schedule(); }, {passive: true});
for (const query of [reduced, compact, wide]) query.addEventListener('change', resize);
document.addEventListener('visibilitychange', schedule);
new ResizeObserver(resize).observe(art);
const observer = new IntersectionObserver(([entry]) => {
  visible = entry.isIntersecting;
  if (visible) {
    read();
    schedule();
  }
});
observer.observe(stage);
const loader = new IntersectionObserver(([entry]) => {
  if (entry.isIntersecting) {
    loader.disconnect();
    loadViews();
  }
}, {rootMargin: '300px'});
loader.observe(stage);
read();
pose = target;
update(performance.now());
