
type Turnstile = {
  render(node: HTMLElement, opts: {
    sitekey: string;
    callback(token: string): void;
    'expired-callback'(): void;
    'error-callback'(): void;
  }): string;
  remove(id: string): void;
};

let loading: Promise<Turnstile> | undefined;
function client(): Promise<Turnstile> {
  const host = window as Window & { turnstile?: Turnstile };
  if (host.turnstile) return Promise.resolve(host.turnstile);
  if (!loading) loading = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
    script.async = true;
    script.onload = () => host.turnstile ? resolve(host.turnstile) : reject(new Error('Turnstile unavailable'));
    script.onerror = () => { script.remove(); reject(new Error('Turnstile unavailable')); };
    document.head.append(script);
  }).catch((error: unknown) => { loading = undefined; throw error; }) as Promise<Turnstile>;
  return loading;
}

export function mountCaptcha(node: HTMLElement, onError: () => void) {
  let widget: { id: string; api: Turnstile } | undefined;
  let key: string | undefined;
  let token = '';
  let generation = 0;

  function render(siteKey?: string) {
    key = siteKey;
    token = '';
    const current = ++generation;
    if (widget) widget.api.remove(widget.id);
    widget = undefined;
    node.replaceChildren();
    node.hidden = !siteKey;
    if (!siteKey) return;
    void client().then(api => {
      if (current !== generation) return;
      widget = { api, id: api.render(node, {
        sitekey: siteKey,
        callback: value => { token = value; },
        'expired-callback': () => { token = ''; },
        'error-callback': () => { token = ''; onError(); },
      }) };
    }).catch(() => { if (current === generation) onError(); });
  }

  return {
    render,
    reset: () => render(key),
    getToken: () => token,
  };
}
