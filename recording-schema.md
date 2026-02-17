# Recording Schema Reference

> Technical specification for the event data captured by the Workflow Recorder Chrome extension.

---

## Table of Contents

- [1. Overview](#1-overview)
- [2. Storage Mechanism](#2-storage-mechanism)
- [3. Base Event Schema](#3-base-event-schema)
- [4. Event Types](#4-event-types)
  - [4.1 click](#41-click)
  - [4.2 navigation](#42-navigation)
  - [4.3 input](#43-input)
  - [4.4 formSubmit](#44-formsubmit)
  - [4.5 copy](#45-copy)
  - [4.6 paste](#46-paste)
  - [4.7 tabFocus](#47-tabfocus)
- [5. Shared Data Structures](#5-shared-data-structures)
  - [5.1 ElementInfo](#51-elementinfo)
  - [5.2 ParentContext](#52-parentcontext)
- [6. Capture Behavior](#6-capture-behavior)
- [7. Data Limits and Redaction](#7-data-limits-and-redaction)

---

## 1. Overview

The recorder captures a chronological sequence of user-initiated browser events. All events are stored locally using `chrome.storage.local` during the recording session. No data is transmitted externally until the user explicitly triggers the "Send to Interpreter" action.

**Capture sources:**

| Source | Events Captured |
|--------|----------------|
| Content Script (DOM) | `click`, `input`, `formSubmit`, `copy`, `paste`, `navigation` |
| Background Service Worker | `tabFocus` (tab switches, window focus changes) |

---

## 2. Storage Mechanism

| Property | Value |
|----------|-------|
| Storage API | `chrome.storage.local` |
| Storage key | `events` (array of event objects) |
| Recording state key | `isRecording` (boolean) |
| Persistence | Survives page reloads; cleared on new recording start |
| External calls during recording | None |

---

## 3. Base Event Schema

Every captured event conforms to the following base structure:

```jsonc
{
  "timestamp": "string",     // ISO 8601 datetime (e.g., "2026-02-16T12:30:45.123Z")
  "eventType": "string",     // One of: click | navigation | input | formSubmit | copy | paste | tabFocus
  "url": "string",           // Full URL of the page where the event occurred
  "pageTitle": "string",     // document.title at the time of capture
  "data": { }                // Event-specific payload (see Section 4)
}
```

---

## 4. Event Types

### 4.1 `click`

Captured on every `click` event via document-level capture-phase listener.

```jsonc
{
  "eventType": "click",
  "data": {
    "element": { },          // ElementInfo — see Section 5.1
    "parent": { },           // ParentContext — see Section 5.2
    "x": 0,                  // clientX coordinate (integer)
    "y": 0                   // clientY coordinate (integer)
  }
}
```

**Trigger:** `document.addEventListener('click', handler, true)`

---

### 4.2 `navigation`

Captured on URL changes. Covers full page loads, SPA navigation, and browser history events.

```jsonc
{
  "eventType": "navigation",
  "data": {
    "from": "string | null",   // Previous URL (null on initial page load)
    "to": "string",            // New URL
    "method": "string"         // Detection method (see table below)
  }
}
```

**Detection methods:**

| `method` value | Trigger |
|----------------|---------|
| `pageLoad` | Recording started on a page (initial capture) |
| `pushState` | `history.pushState()` called (SPA navigation) |
| `replaceState` | `history.replaceState()` called (SPA URL replacement) |
| `popstate_or_spa` | Browser back/forward button or other `popstate` event |

**Implementation:** `history.pushState` and `history.replaceState` are monkey-patched to intercept SPA navigations. The `popstate` event listener handles back/forward browser navigation.

---

### 4.3 `input`

Captured on form field value changes. **Debounced at 800ms** — only the final value is recorded after the user stops typing.

```jsonc
{
  "eventType": "input",
  "data": {
    "element": { },          // ElementInfo — see Section 5.1
    "parent": { },           // ParentContext — see Section 5.2
    "value": "string"        // Final field value (max 1000 chars)
  }
}
```

**Eligible elements:** `<input>`, `<textarea>`, `<select>`, and elements with `contentEditable=true`.

**Trigger:** `document.addEventListener('input', handler, true)` with per-field debounce keyed by XPath.

---

### 4.4 `formSubmit`

Captured when a `<form>` element fires its `submit` event.

```jsonc
{
  "eventType": "formSubmit",
  "data": {
    "formAction": "string | null",   // Form's action attribute (target URL)
    "formMethod": "string | null",   // HTTP method (GET, POST, etc.)
    "formId": "string | null",       // Form element's id attribute
    "fields": {                      // Key-value map of all form fields
      "fieldName": "value",
      "password_field": "[REDACTED]" // Password fields are always redacted
    }
  }
}
```

**Field collection rules:**

| Condition | Behavior |
|-----------|----------|
| Field has `name` attribute | Used as the key |
| Field has no `name` but has `id` | `id` used as the key |
| Field has neither | Key is `field_{index}` |
| Field type is `password` | Value replaced with `[REDACTED]` |
| Field type is `submit` or `button` | Skipped entirely |

**Trigger:** `document.addEventListener('submit', handler, true)`

---

### 4.5 `copy`

Captured when the user copies text to the clipboard.

```jsonc
{
  "eventType": "copy",
  "data": {
    "text": "string"         // Selected text content (max 1000 chars)
  }
}
```

**Source:** `window.getSelection().toString()`

**Trigger:** `document.addEventListener('copy', handler, true)`

---

### 4.6 `paste`

Captured when the user pastes content from the clipboard.

```jsonc
{
  "eventType": "paste",
  "data": {
    "text": "string"         // Pasted text content (max 1000 chars)
  }
}
```

**Source:** `ClipboardEvent.clipboardData.getData('text')`

**Trigger:** `document.addEventListener('paste', handler, true)`

---

### 4.7 `tabFocus`

Captured when the user switches between browser tabs or windows. This event is recorded from the **background service worker**, not the content script.

```jsonc
{
  "eventType": "tabFocus",
  "data": {
    "tabId": 0,              // Chrome tab ID (integer)
    "windowId": 0,           // Chrome window ID (integer)
    "type": "string"         // Present only for window focus events (value: "windowFocus")
  }
}
```

**Triggers:**

| Chrome API | Scenario |
|------------|----------|
| `chrome.tabs.onActivated` | User switches to a different tab within the same window |
| `chrome.windows.onFocusChanged` | User switches to a different browser window |

---

## 5. Shared Data Structures

### 5.1 `ElementInfo`

Describes a DOM element involved in an event. Used in `click`, `input`, and `formSubmit` events.

```jsonc
{
  "tag": "string",               // Lowercase tag name (e.g., "button", "a", "input")
  "id": "string | null",         // Element id attribute
  "classes": ["string"],         // Array of CSS class names
  "textContent": "string",       // Trimmed inner text (max 200 chars)
  "href": "string | null",       // href attribute (links)
  "name": "string | null",       // name attribute (form fields)
  "type": "string | null",       // type attribute (input fields)
  "value": "string | null",      // Current value property (max 500 chars)
  "placeholder": "string | null",// placeholder attribute
  "role": "string | null",       // ARIA role attribute
  "ariaLabel": "string | null",  // aria-label attribute
  "xpath": "string"              // Computed XPath selector
}
```

**XPath generation rules:**
- If element has an `id`: `//*[@id="elementId"]`
- Otherwise: full positional path from root (e.g., `/html[1]/body[1]/div[2]/button[1]`)

---

### 5.2 `ParentContext`

Minimal descriptor of the immediate parent element. Provides structural context for identifying where an element sits in the page.

```jsonc
{
  "tag": "string",               // Lowercase tag name of parent
  "id": "string | null",         // Parent id attribute
  "classes": ["string"]          // Parent CSS class names
}
```

---

## 6. Capture Behavior

| Behavior | Detail |
|----------|--------|
| Listener phase | All DOM listeners use **capture phase** (`true` as third argument) to intercept events before they can be stopped by page scripts |
| Input debounce | 800ms idle timeout per field, keyed by XPath. Only the final value is recorded |
| SPA detection | `history.pushState` and `history.replaceState` are wrapped at `document_start` to intercept before page scripts run |
| Initial page capture | A `navigation` event with `method: "pageLoad"` is emitted when listeners are attached |
| Pending input flush | On stop, all debounce timers are cleared (pending inputs are discarded, not force-flushed) |
| Recording toggle | Managed via `chrome.storage.local` (`isRecording` flag). Background service worker relays start/stop to all open tabs |

---

## 7. Data Limits and Redaction

| Field | Max Length | Notes |
|-------|-----------|-------|
| `element.textContent` | 200 chars | Truncated |
| `element.value` | 500 chars | Truncated |
| `input.data.value` | 1000 chars | Truncated |
| `copy.data.text` | 1000 chars | Truncated |
| `paste.data.text` | 1000 chars | Truncated |
| Password fields in `formSubmit` | N/A | Replaced with `[REDACTED]` |
| Submit/button fields in `formSubmit` | N/A | Excluded entirely |

All truncation is applied via `String.slice()` — no trailing indicators are added.
