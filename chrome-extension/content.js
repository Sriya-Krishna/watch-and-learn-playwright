// Content script — captures DOM events and sends them to background

let recording = false;
const inputTimers = new Map(); // debounce timers for input fields

// Check recording state on load
chrome.storage.local.get(['isRecording'], (data) => {
  recording = data.isRecording || false;
  if (recording) attachListeners();
});

// Listen for start/stop from background
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.action === 'startRecording') {
    recording = true;
    attachListeners();
  }
  if (msg.action === 'stopRecording') {
    recording = false;
    detachListeners();
  }
});

function getXPath(el) {
  if (!el || el.nodeType !== 1) return '';
  if (el.id) return `//*[@id="${el.id}"]`;
  if (el === document.body) return '/html/body';
  const parts = [];
  let current = el;
  while (current && current.nodeType === 1) {
    let index = 1;
    let sibling = current.previousSibling;
    while (sibling) {
      if (sibling.nodeType === 1 && sibling.tagName === current.tagName) index++;
      sibling = sibling.previousSibling;
    }
    const tag = current.tagName.toLowerCase();
    parts.unshift(`${tag}[${index}]`);
    current = current.parentElement;
  }
  return '/' + parts.join('/');
}

function getElementInfo(el) {
  if (!el || !el.tagName) return {};
  return {
    tag: el.tagName.toLowerCase(),
    id: el.id || null,
    classes: el.className ? String(el.className).split(/\s+/).filter(Boolean) : [],
    textContent: (el.textContent || '').trim().slice(0, 200),
    href: el.getAttribute('href') || null,
    name: el.getAttribute('name') || null,
    type: el.getAttribute('type') || null,
    value: el.value !== undefined ? String(el.value).slice(0, 500) : null,
    placeholder: el.getAttribute('placeholder') || null,
    role: el.getAttribute('role') || null,
    ariaLabel: el.getAttribute('aria-label') || null,
    xpath: getXPath(el)
  };
}

function getParentContext(el) {
  const parent = el?.parentElement;
  if (!parent) return null;
  return {
    tag: parent.tagName.toLowerCase(),
    id: parent.id || null,
    classes: parent.className ? String(parent.className).split(/\s+/).filter(Boolean) : []
  };
}

function makeEvent(eventType, data) {
  return {
    timestamp: new Date().toISOString(),
    eventType,
    url: window.location.href,
    pageTitle: document.title,
    data
  };
}

function sendEvent(evt) {
  if (!recording) return;
  try {
    chrome.runtime.sendMessage({ action: 'recordEvent', event: evt });
  } catch (e) {
    // Extension context invalidated
  }
}

// --- Event Handlers ---

function onClickCapture(e) {
  const el = e.target;
  sendEvent(makeEvent('click', {
    element: getElementInfo(el),
    parent: getParentContext(el),
    x: e.clientX,
    y: e.clientY
  }));
}

function onInputCapture(e) {
  const el = e.target;
  if (!el || !el.tagName) return;
  const tag = el.tagName.toLowerCase();
  if (tag !== 'input' && tag !== 'textarea' && tag !== 'select' && !el.isContentEditable) return;

  // Debounce: capture final value after 800ms of no typing
  const key = getXPath(el);
  if (inputTimers.has(key)) clearTimeout(inputTimers.get(key));
  inputTimers.set(key, setTimeout(() => {
    inputTimers.delete(key);
    sendEvent(makeEvent('input', {
      element: getElementInfo(el),
      parent: getParentContext(el),
      value: el.value !== undefined ? String(el.value).slice(0, 1000) : (el.textContent || '').slice(0, 1000)
    }));
  }, 800));
}

function onSubmitCapture(e) {
  const form = e.target;
  if (!form || form.tagName?.toLowerCase() !== 'form') return;

  // Collect all form field values
  const fields = {};
  const elements = form.elements;
  for (let i = 0; i < elements.length; i++) {
    const field = elements[i];
    const name = field.name || field.id || `field_${i}`;
    if (field.type === 'password') {
      fields[name] = '[REDACTED]';
    } else if (field.type === 'submit' || field.type === 'button') {
      continue;
    } else {
      fields[name] = field.value || '';
    }
  }

  sendEvent(makeEvent('formSubmit', {
    formAction: form.action || null,
    formMethod: form.method || null,
    formId: form.id || null,
    fields
  }));
}

function onCopyCapture(e) {
  const text = window.getSelection()?.toString()?.slice(0, 1000) || '';
  sendEvent(makeEvent('copy', { text }));
}

function onPasteCapture(e) {
  const text = e.clipboardData?.getData('text')?.slice(0, 1000) || '';
  sendEvent(makeEvent('paste', { text }));
}

// --- SPA Navigation ---

let lastUrl = window.location.href;

function checkNavigation() {
  const currentUrl = window.location.href;
  if (currentUrl !== lastUrl) {
    sendEvent(makeEvent('navigation', {
      from: lastUrl,
      to: currentUrl,
      method: 'popstate_or_spa'
    }));
    lastUrl = currentUrl;
  }
}

function onPopState() {
  checkNavigation();
}

// Patch pushState/replaceState for SPA detection
const origPushState = history.pushState;
const origReplaceState = history.replaceState;

history.pushState = function (...args) {
  origPushState.apply(this, args);
  if (recording) {
    setTimeout(() => {
      sendEvent(makeEvent('navigation', {
        from: lastUrl,
        to: window.location.href,
        method: 'pushState'
      }));
      lastUrl = window.location.href;
    }, 0);
  }
};

history.replaceState = function (...args) {
  origReplaceState.apply(this, args);
  if (recording) {
    setTimeout(() => {
      sendEvent(makeEvent('navigation', {
        from: lastUrl,
        to: window.location.href,
        method: 'replaceState'
      }));
      lastUrl = window.location.href;
    }, 0);
  }
};

// --- Attach/Detach ---

function attachListeners() {
  document.addEventListener('click', onClickCapture, true);
  document.addEventListener('input', onInputCapture, true);
  document.addEventListener('submit', onSubmitCapture, true);
  document.addEventListener('copy', onCopyCapture, true);
  document.addEventListener('paste', onPasteCapture, true);
  window.addEventListener('popstate', onPopState);

  // Record initial navigation
  sendEvent(makeEvent('navigation', {
    from: null,
    to: window.location.href,
    method: 'pageLoad'
  }));
}

function detachListeners() {
  document.removeEventListener('click', onClickCapture, true);
  document.removeEventListener('input', onInputCapture, true);
  document.removeEventListener('submit', onSubmitCapture, true);
  document.removeEventListener('copy', onCopyCapture, true);
  document.removeEventListener('paste', onPasteCapture, true);
  window.removeEventListener('popstate', onPopState);

  // Flush any pending input timers
  for (const [key, timer] of inputTimers) {
    clearTimeout(timer);
  }
  inputTimers.clear();
}
