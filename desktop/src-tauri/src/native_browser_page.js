(() => {
  if (window.__agenticosNative) return;
  let held = false;
  let acting = 0;
  const take = event => {
    if (!event.isTrusted || acting || held) return;
    held = true;
    window.__TAURI_INTERNALS__?.invoke('native_browser_input').catch(error => console.warn('Native browser takeover notification failed', error));
  };
  for (const type of ['pointerdown', 'keydown', 'wheel', 'touchstart', 'beforeinput', 'input', 'change', 'compositionstart'])
    window.addEventListener(type, take, {capture: true, passive: true});
  const action = run => {
    if (held) throw new Error('The person holds this browser. Wait for hand-back.');
    acting += 1;
    try { return run(); } finally { acting -= 1; }
  };
  const command = (method, params) => {
    if (held) throw new Error('The person holds this browser. Wait for hand-back.');
    if (method === 'Input.dispatchMouseEvent') {
      if (params.type === 'mouseWheel') {
        window.scrollBy({top: params.deltaY || 0, left: params.deltaX || 0, behavior: 'instant'});
        return;
      }
      const element = document.elementFromPoint(params.x, params.y);
      if (!element) throw new Error('The target is outside the viewport.');
      if (params.type === 'mousePressed') {
        element.focus?.();
        element.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true, cancelable: true, clientX: params.x, clientY: params.y, button: 0}));
        element.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true, clientX: params.x, clientY: params.y, button: 0}));
      } else if (params.type === 'mouseReleased') {
        element.dispatchEvent(new PointerEvent('pointerup', {bubbles: true, cancelable: true, clientX: params.x, clientY: params.y, button: 0}));
        element.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, cancelable: true, clientX: params.x, clientY: params.y, button: 0}));
        element.click();
      } else throw new Error('Unsupported native mouse operation.');
      return;
    }
    if (method === 'Input.insertText') {
      if (!document.execCommand('insertText', false, params.text))
        throw new Error('The focused element does not accept text.');
      return;
    }
    if (method === 'Input.dispatchKeyEvent') {
      if (!['Enter', 'Tab', 'Backspace', 'Delete'].includes(params.key))
        throw new Error('Use the desktop keyboard for this native key.');
      if (params.type === 'char') return;
      const element = document.activeElement;
      const down = params.type !== 'keyUp';
      const accepted = element.dispatchEvent(new KeyboardEvent(down ? 'keydown' : 'keyup', {
        key: params.key, code: params.code, bubbles: true, cancelable: true,
      }));
      if (!down || !accepted) return;
      if (params.key === 'Enter' && element.form) element.form.requestSubmit();
      else if (params.key === 'Backspace') document.execCommand('delete');
      else if (params.key === 'Delete') document.execCommand('forwardDelete');
      else if (params.key === 'Tab') {
        const fields = [...document.querySelectorAll('a[href],button,input,select,textarea,[tabindex]')]
          .filter(el => !el.disabled && el.tabIndex >= 0 && el.getClientRects().length);
        fields[(fields.indexOf(element) + 1) % fields.length]?.focus();
      } else if (params.key === 'Enter' && ['BUTTON', 'A'].includes(element.tagName)) element.click();
    }
  };
  Object.defineProperty(window, '__agenticosNative', {value: Object.freeze({
    get held() { return held; }, setHeld(value) { held = Boolean(value); }, command, action,
  }), writable: false, configurable: false});
  document.addEventListener('click', event => {
    const link = event.target.closest?.('a[target]');
    if (link) link.target = '_self';
  }, true);
  window.open = (url) => { if (url) location.assign(url); return null; };
})();
