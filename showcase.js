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
  {key: 'attention', label: 'YOUR TURN', ink: '#a0382c'},
  {key: 'working', label: 'WORKING', ink: '#80500a'},
  {key: 'ready', label: 'READY', ink: '#296442'}
];
const views = 72;
const viewsPerSheet = 12;
const groups = [];
const clamp = value => Math.max(0, Math.min(1, value));
const smooth = value => value * value * (3 - 2 * value);
const staticStage = () => reduced.matches || compact.matches;
let selected = 0, shown = -1, pose = 0, target = 0, last = 0, frame = 0, visible = true;
let winkStarted = null, winkSheet, winkRects, lastPaint;
let artWidth = 0, storyTop = 0, travel = 1;
let split = false, previousBlend, previousInterval;

function read() {
  return staticStage() ? selected / 2 : clamp((scrollY - storyTop) / travel);
}

function schedule() {
  if (!frame && visible && !document.hidden) frame = requestAnimationFrame(tick);
}

function paint(sheet, [x, y, width, height, left, top], alpha = 1) {
  ctx.globalAlpha = alpha;
  ctx.drawImage(sheet, x, y, width, height, left, top, width, height);
}

function draw(interval, blend, angle, wink) {
  const view = Math.round(angle * views) % views;
  const group = groups[Math.floor(view / viewsPerSheet)];
  if (!group) return;
  const step = Math.round(blend * 24);
  const key = view + '/' + interval + '/' + step + '/' + wink;
  if (lastPaint === key) return;
  lastPaint = key;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (wink && winkSheet) {
    paint(winkSheet, winkRects[wink]);
  } else {
    const index = view % viewsPerSheet;
    paint(group.images[0], group.rects[0][index]);
    if (interval || step) {
      // Only the lights differ. Repaint their small patch instead of a second full frame.
      const from = group.rects[interval + 1][index];
      const to = group.rects[interval + 2][index];
      ctx.clearRect(from[4], from[5], from[2], from[3]);
      if (step < 24) paint(group.images[interval + 1], from, 1 - step / 24);
      ctx.globalCompositeOperation = 'lighter';
      if (step) paint(group.images[interval + 2], to, step / 24);
      ctx.globalCompositeOperation = 'source-over';
    }
  }
  if (!art.hasAttribute('data-ready')) art.setAttribute('data-ready', '');
}

function update(now) {
  const phase = pose < .25 ? 0 : pose < .75 ? 1 : 2;
  if (phase !== shown) {
    if (phase === 2 && shown >= 0 && !staticStage()) winkStarted = now;
    else winkStarted = null;
    shown = phase;
    stage.dataset.signalPhase = phases[phase].key;
    stage.style.setProperty('--signal', phases[phase].ink);
    phaseIndex.textContent = '0' + (phase + 1) + ' / ' + phases[phase].label;
    panels.forEach((panel, index) => { panel.hidden = index !== phase; });
    buttons.forEach((button, index) => button.setAttribute('aria-pressed', String(index === phase)));
  }

  const interval = Math.min(1, Math.floor(pose * 2));
  const blend = smooth(clamp((pose * 2 - interval - .25) / .5));
  progress.style.transform = 'scaleX(' + pose + ')';
  if (blend !== previousBlend || interval !== previousInterval) {
    previousBlend = blend;
    previousInterval = interval;
    stage.style.setProperty('--amber-mix', interval === 0 ? blend : 1);
    stage.style.setProperty('--green-mix', interval === 1 ? blend : 0);
    const shift = split ? (interval === 0 ? -1 + 2 * blend : 1 - 2 * blend) : 0;
    art.style.setProperty('--model-pan', shift * artWidth * .24 + 'px');
    stage.style.setProperty('--story-copy', smooth(Math.abs(2 * blend - 1)));
  }

  if (staticStage()) winkStarted = null;
  // Face front as green arrives so the wink can happen on entry, even mid-scroll.
  const lampBlend = interval === 0 ? blend : smooth(clamp((pose - .54) / .21));
  const angle = staticStage() ? 0 : interval + lampBlend;
  const winkTime = winkStarted === null ? 1 : clamp((now - winkStarted) / 480);
  const wink = winkSheet ? Math.round(6 * smooth(1 - Math.abs(2 * winkTime - 1))) : 0;
  if (ctx) draw(interval, lampBlend, angle, wink);
}

function tick(now) {
  frame = 0;
  target = read();
  const dt = last ? Math.min(.064, (now - last) / 1000) : .016;
  last = now;
  pose = staticStage() ? target : pose + (target - pose) * (1 - Math.exp(-dt * 20));
  if (Math.abs(target - pose) < .0002) pose = target;
  update(now);
  if (pose !== target || (winkStarted !== null && now - winkStarted < 480)) schedule();
  else last = 0;
}

function measure() {
  storyTop = story.getBoundingClientRect().top + scrollY;
  travel = Math.max(1, story.offsetHeight - stage.offsetHeight);
}

function resize() {
  split = wide.matches && !staticStage();
  artWidth = art.clientWidth;
  const horizontal = split ? .168 : .093;
  const artSize = .126 * Math.min(art.clientHeight / .079, artWidth / horizontal);
  art.style.setProperty('--art-size', artSize + 'px');
  previousBlend = undefined;
  measure();
  schedule();
}

async function loadViews() {
  if (!ctx) return;
  const pixels = matchMedia('(min-width: 850px)').matches ? 1080 : 648;
  const directory = new URL('./assets/showcase-' + pixels + '/', document.baseURI);
  const loadImage = async name => {
    const url = new URL(name + '.webp', directory);
    if (typeof createImageBitmap === 'function') {
      const response = await fetch(url);
      if (!response.ok) throw new Error('Missing showcase image');
      try {
        return await createImageBitmap(await response.blob());
      } catch { /* Fall back to the browser image decoder. */ }
    }
    const image = new Image();
    image.src = url.href;
    await image.decode();
    return image;
  };
  try {
    const response = await fetch(new URL('frames.json', directory));
    if (!response.ok) throw new Error('Missing showcase frames');
    const manifest = await response.json();
    canvas.width = canvas.height = pixels;
    const loadGroup = async index => {
      const images = await Promise.all(['body', 'red', 'amber', 'green'].map(name => loadImage(index + '-' + name)));
      groups[index] = {images, rects: manifest.groups[index]};
      schedule();
    };
    loadImage('wink').then(image => {
      winkSheet = image;
      winkRects = manifest.wink;
    }).catch(() => {});
    await loadGroup(0);
    // Warm the turn in order, yielding between batches so scrolling stays responsive.
    for (let index = 1; index < manifest.groups.length; index += 2) {
      await Promise.allSettled([index, index + 1].filter(i => i < manifest.groups.length).map(loadGroup));
    }
  } catch {
    // The still and the signal controls remain available.
  }
}

buttons.forEach((button, index) => button.addEventListener('click', () => {
  selected = index;
  if (staticStage()) {
    schedule();
    return;
  }
  measure();
  window.scrollTo({top: storyTop + travel * index / 2, behavior: 'smooth'});
}));

addEventListener('scroll', schedule, {passive: true});
for (const query of [reduced, compact, wide]) query.addEventListener('change', resize);
document.addEventListener('visibilitychange', schedule);
const layout = new ResizeObserver(resize);
layout.observe(art);
layout.observe(document.body);
const observer = new IntersectionObserver(([entry]) => {
  visible = entry.isIntersecting;
  if (visible) {
    measure();
    schedule();
  }
});
observer.observe(stage);
const loader = new IntersectionObserver(([entry]) => {
  if (entry.isIntersecting) {
    loader.disconnect();
    loadViews();
  }
}, {rootMargin: '750px'});
loader.observe(stage);
resize();
pose = read();
update(performance.now());
