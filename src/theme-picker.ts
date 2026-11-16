import './palettes.css';
import './theme-picker.css';

const themes = {
  jade: 'หยกเข้ม',
  ocean: 'ทะเลลึก',
  plum: 'ม่วงอเมทิสต์',
  ember: 'อำพัน',
  sakura: 'ซากุระ',
  parchment: 'กระดาษคราฟต์',
};

type Theme = keyof typeof themes;
const defaultTheme: Theme = 'jade';
const storageKey = 'hidden-orders:theme';

function isTheme(value: string | null): value is Theme {
  return value !== null && Object.hasOwn(themes, value);
}

function savedTheme(): Theme {
  try {
    const saved = localStorage.getItem(storageKey);
    return isTheme(saved) ? saved : defaultTheme;
  } catch {
    return defaultTheme;
  }
}

export function mountThemePicker(dialog: HTMLDialogElement, onChange: () => void) {
  const options = dialog.querySelector<HTMLFieldSetElement>('.theme-options')!;
  const triggers = document.querySelectorAll<HTMLButtonElement>('[data-open-themes]');
  const inputs = new Map<string, HTMLInputElement>();
  let current = savedTheme();
  let opener: HTMLButtonElement | undefined;

  for (const [id, name] of Object.entries(themes)) {
    const label = document.createElement('label');
    label.className = 'theme-option';
    const radio = document.createElement('input');
    radio.type = 'radio';
    radio.name = 'game-theme';
    radio.value = id;
    const swatch = document.createElement('span');
    swatch.className = 'theme-swatch';
    swatch.dataset.themeSwatch = id;
    swatch.setAttribute('aria-hidden', 'true');
    const text = document.createElement('span');
    text.textContent = name;
    label.append(radio, swatch, text);
    options.append(label);
    inputs.set(id, radio);
  }

  function apply(theme: Theme) {
    current = theme;
    document.documentElement.dataset.theme = theme;
    const radio = inputs.get(theme);
    if (radio) radio.checked = true;
    for (const trigger of triggers) trigger.title = 'ธีมปัจจุบัน · ' + themes[theme];
    onChange();
  }

  apply(current);
  options.addEventListener('change', event => {
    const radio = event.target;
    if (!(radio instanceof HTMLInputElement) || !radio.checked || !isTheme(radio.value)) return;
    apply(radio.value);
    try {
      localStorage.setItem(storageKey, current);
    } catch {
      // Theme changes still apply for the current tab.
    }
  });

  for (const trigger of triggers) {
    trigger.addEventListener('click', () => {
      if (dialog.open) return;
      opener = trigger;
      dialog.showModal();
      inputs.get(current)?.focus();
    });
  }
  dialog.addEventListener('close', () => opener?.focus({ preventScroll: true }));
}
