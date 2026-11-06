const installDisclosure = document.getElementById('setup');
const installToggle = document.getElementById('install-toggle');
const installSummary = installDisclosure.querySelector('summary');
const installHashes = ['#setup', '#mac-setup', '#windows-setup', '#start'];

function syncInstallToggle() {
  installToggle.setAttribute('aria-expanded', String(installDisclosure.open));
}

function openInstall(hash) {
  if (!installHashes.includes(hash)) return;
  installDisclosure.open = true;
  const target = document.querySelector(hash);
  if (target.matches('.install-platform')) {
    target.dataset.pinned = '';
    target.open = true;
  }
}

installDisclosure.dataset.enhanced = '';
installSummary.textContent = 'Close install prompts';
openInstall(window.location.hash);
syncInstallToggle();

window.addEventListener('hashchange', () => openInstall(window.location.hash));
installToggle.addEventListener('click', event => {
  event.preventDefault();
  installDisclosure.open = !installDisclosure.open;
  syncInstallToggle();
  if (installDisclosure.open) {
    installDisclosure.scrollIntoView({block: 'nearest', behavior: 'instant'});
    installSummary.focus({preventScroll: true});
  }
});
installDisclosure.addEventListener('toggle', syncInstallToggle);
installSummary.addEventListener('click', event => {
  event.preventDefault();
  installDisclosure.open = false;
  installToggle.focus();
});
installDisclosure.addEventListener('keydown', event => {
  if (event.key !== 'Escape' || !installDisclosure.open) return;
  installDisclosure.open = false;
  installToggle.focus();
});
document.addEventListener('click', event => {
  const link = event.target.closest('a[href]');
  if (link !== installToggle) openInstall(link?.getAttribute('href'));
});

const fineHover = matchMedia('(any-hover: hover) and (any-pointer: fine)');
for (const platform of installDisclosure.querySelectorAll('.install-platform')) {
  const summary = platform.querySelector('summary');
  let hoverTimer;

  function closePreview() {
    clearTimeout(hoverTimer);
    hoverTimer = setTimeout(() => {
      if (!('pinned' in platform.dataset) && !platform.contains(document.activeElement)) {
        platform.open = false;
      }
    }, 180);
  }

  platform.addEventListener('pointerenter', event => {
    if (!fineHover.matches || event.pointerType !== 'mouse') return;
    clearTimeout(hoverTimer);
    hoverTimer = setTimeout(() => {
      if (installDisclosure.open) platform.open = true;
    }, 120);
  });
  platform.addEventListener('pointerleave', event => {
    if (event.pointerType === 'mouse') closePreview();
  });
  platform.addEventListener('focusout', event => {
    if (!platform.contains(event.relatedTarget) && !platform.matches(':hover')) closePreview();
  });
  summary.addEventListener('click', event => {
    event.preventDefault();
    clearTimeout(hoverTimer);
    if ('pinned' in platform.dataset) {
      delete platform.dataset.pinned;
      platform.open = false;
    } else {
      platform.dataset.pinned = '';
      platform.open = true;
    }
  });
  installDisclosure.addEventListener('toggle', () => {
    if (installDisclosure.open) return;
    clearTimeout(hoverTimer);
    if (!('pinned' in platform.dataset)) platform.open = false;
  });
}

for (const button of installDisclosure.querySelectorAll('[data-copy-install]')) {
  const prompt = document.getElementById(button.dataset.copyInstall);
  const status = button.closest('.install-platform').querySelector('[role="status"]');
  const label = button.querySelector('span');
  let resetLabel;
  button.hidden = false;

  button.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(prompt.textContent.trim());
      label.textContent = 'Copied';
      status.textContent = 'Install prompt copied.';
      clearTimeout(resetLabel);
      resetLabel = setTimeout(() => { label.textContent = 'Copy'; }, 1800);
    } catch {
      label.textContent = 'Copy';
      clearTimeout(resetLabel);
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(prompt);
      selection.removeAllRanges();
      selection.addRange(range);
      status.textContent = 'Prompt selected. Copy it with your keyboard or touch menu.';
    }
  });
}
