import * as THREE from './vendor/three.module.js';

const colors = [0xff413a, 0xffaa36, 0x42f292];

export function mountSignalScene(art, stage, reducedMotion) {
  const canvas = art.querySelector('canvas');
  const composite = canvas.getContext('2d');
  if (!composite) return null;

  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.25;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(34, 1, .1, 30);
  camera.position.set(0, 3.5, 9.4);
  camera.lookAt(0, 1.4, 0);
  scene.add(new THREE.HemisphereLight(0xfff7ed, 0x795342, 2.1));
  for (const [color, intensity, position] of [
    [0xffe0bf, 3.0, [3, 7, 5]], [0xffffff, 1.8, [-4, 2, 5]], [0xffc58c, 3.5, [-2, 5, -4]]
  ]) {
    const light = new THREE.DirectionalLight(color, intensity);
    light.position.set(...position);
    scene.add(light);
  }

  const rig = new THREE.Group();
  scene.add(rig);
  const clay = new THREE.MeshStandardMaterial({ color: 0xd26d4d, roughness: .63 });
  const graphite = new THREE.MeshStandardMaterial({ color: 0x242326, roughness: .54 });
  const eye = new THREE.MeshStandardMaterial({ color: 0x161317, roughness: .32 });

  function box(size, position, material) {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), material);
    mesh.position.set(...position);
    rig.add(mesh);
    return mesh;
  }

  // This illustration uses arbitrary proportions and solid primitives.
  box([2.25, 1.5, 1.08], [.6, 1.27, 0], clay);
  box([.30, .48, .65], [-.64, 1.15, 0], clay);
  box([.30, .48, .65], [1.84, 1.15, 0], clay);
  for (const x of [-.22, 1.42]) {
    for (const z of [-.33, .33]) box([.38, .55, .37], [x, .28, z], clay);
  }
  box([.22, .23, .08], [-.01, 1.4, .55], eye);
  const winkEye = box([.22, .23, .08], [1.21, 1.4, .55], eye);

  box([.73, .12, .68], [-1.6, .06, 0], graphite);
  box([.28, .7, .28], [-1.6, .4, 0], graphite);
  box([.65, 2.0, .52], [-1.6, 1.7, 0], graphite);

  function radialTexture() {
    const image = document.createElement('canvas');
    image.width = image.height = 64;
    const context = image.getContext('2d');
    const gradient = context.createRadialGradient(32, 32, 1, 32, 32, 31);
    gradient.addColorStop(0, '#ffffff');
    gradient.addColorStop(.35, '#ffffff60');
    gradient.addColorStop(1, '#ffffff00');
    context.fillStyle = gradient;
    context.fillRect(0, 0, 64, 64);
    return new THREE.CanvasTexture(image);
  }

  const radial = radialTexture();
  const shadow = new THREE.Mesh(
    new THREE.PlaneGeometry(5.8, 3.1),
    new THREE.MeshBasicMaterial({ map: radial, color: 0x321914, opacity: .46, transparent: true, depthWrite: false })
  );
  shadow.rotation.x = -Math.PI / 2;
  shadow.position.y = -.02;
  scene.add(shadow);

  const lamps = colors.map((color, index) => {
    const y = 2.34 - index * .63;
    const material = new THREE.MeshStandardMaterial({
      color, emissive: color, emissiveIntensity: 0, roughness: .25
    });
    const bulb = new THREE.Mesh(new THREE.SphereGeometry(.19, 24, 14), material);
    bulb.scale.z = .56;
    bulb.position.set(-1.6, y, .27);
    rig.add(bulb);
    const glow = new THREE.Sprite(new THREE.SpriteMaterial({
      map: radial, color, blending: THREE.AdditiveBlending, opacity: 0,
      depthWrite: false, toneMapped: false
    }));
    glow.position.set(-1.6, y, .38);
    glow.scale.setScalar(1.26);
    rig.add(glow);
    return { material, glow, color };
  });

  let signal = 0;
  let frame = 0;
  let turn = null;
  let angle = .34;
  let lost = false;

  function draw(trail = false) {
    if (lost || !canvas.width || !canvas.height) return;
    rig.rotation.y = angle;
    shadow.rotation.z = angle;
    renderer.render(scene, camera);
    if (trail) {
      composite.globalCompositeOperation = 'destination-in';
      composite.fillStyle = '#0008';
      composite.fillRect(0, 0, canvas.width, canvas.height);
      composite.globalCompositeOperation = 'source-over';
    } else {
      composite.clearRect(0, 0, canvas.width, canvas.height);
    }
    composite.drawImage(renderer.domElement, 0, 0);
  }

  function resize() {
    const bounds = art.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    const scale = Math.min(devicePixelRatio, 1.5);
    canvas.width = Math.round(bounds.width * scale);
    canvas.height = Math.round(bounds.height * scale);
    renderer.setSize(canvas.width, canvas.height, false);
    camera.aspect = bounds.width / bounds.height;
    camera.updateProjectionMatrix();
    draw();
  }

  function animate(now) {
    const progress = Math.min(1, (now - turn.started) / 820);
    const ease = progress * progress * (3 - 2 * progress);
    angle = THREE.MathUtils.lerp(turn.from, turn.to, ease);
    const wink = signal === 2 ? Math.max(0, 1 - Math.abs(progress - .84) / .13) : 0;
    winkEye.scale.y = 1 - .85 * wink;
    draw(progress > .08 && progress < .92);
    if (progress < 1) frame = requestAnimationFrame(animate);
    else turn = null;
  }

  function select(index, animateChange = true) {
    signal = index;
    lamps.forEach(({ material, glow, color }, lamp) => {
      const active = lamp === index;
      material.color.setHex(color).multiplyScalar(active ? 1 : .23);
      material.emissiveIntensity = active ? 1.5 : .02;
      glow.material.opacity = active ? .7 : 0;
    });
    cancelAnimationFrame(frame);
    turn = null;
    winkEye.scale.y = 1;
    const target = index === 1 ? -.34 : .34;
    if (animateChange && !reducedMotion.matches && !lost) {
      const direction = index === 1 ? -1 : 1;
      turn = { from: angle, to: target + Math.PI * 2 * direction, started: performance.now() };
      angle = target + Math.atan2(Math.sin(angle - target), Math.cos(angle - target));
      turn.from = angle;
      frame = requestAnimationFrame(animate);
    } else {
      angle = target;
      draw();
    }
  }

  renderer.domElement.addEventListener('webglcontextlost', event => {
    event.preventDefault();
    lost = true;
    cancelAnimationFrame(frame);
    stage.removeAttribute('data-rendered');
  });
  renderer.domElement.addEventListener('webglcontextrestored', () => {
    lost = false;
    select(signal, false);
    stage.setAttribute('data-rendered', '');
  });
  new ResizeObserver(resize).observe(art);
  reducedMotion.addEventListener('change', () => select(signal, false));
  select(0, false);
  resize();
  stage.setAttribute('data-rendered', '');
  return select;
}
