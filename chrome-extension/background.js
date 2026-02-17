// Background service worker — manages recording state and relays messages

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'startRecording') {
    // Notify all content scripts to start
    chrome.tabs.query({}, (tabs) => {
      for (const tab of tabs) {
        chrome.tabs.sendMessage(tab.id, { action: 'startRecording' }).catch(() => {});
      }
    });
    // Set badge to indicate recording
    chrome.action.setBadgeText({ text: 'REC' });
    chrome.action.setBadgeBackgroundColor({ color: '#ff4444' });
  }

  if (msg.action === 'stopRecording') {
    chrome.tabs.query({}, (tabs) => {
      for (const tab of tabs) {
        chrome.tabs.sendMessage(tab.id, { action: 'stopRecording' }).catch(() => {});
      }
    });
    chrome.action.setBadgeText({ text: '' });
  }

  if (msg.action === 'recordEvent') {
    // Append event to storage
    chrome.storage.local.get(['events', 'isRecording'], (data) => {
      if (!data.isRecording) return;
      const events = data.events || [];
      events.push(msg.event);
      chrome.storage.local.set({ events });
    });
  }
});

// Track tab focus changes
chrome.tabs.onActivated.addListener((activeInfo) => {
  chrome.storage.local.get(['isRecording'], (data) => {
    if (!data.isRecording) return;
    chrome.tabs.get(activeInfo.tabId, (tab) => {
      if (chrome.runtime.lastError || !tab) return;
      const event = {
        timestamp: new Date().toISOString(),
        eventType: 'tabFocus',
        url: tab.url || '',
        pageTitle: tab.title || '',
        data: {
          tabId: tab.id,
          windowId: activeInfo.windowId
        }
      };
      chrome.storage.local.get(['events'], (d) => {
        const events = d.events || [];
        events.push(event);
        chrome.storage.local.set({ events });
      });
    });
  });
});

// Track window focus changes
chrome.windows.onFocusChanged.addListener((windowId) => {
  if (windowId === chrome.windows.WINDOW_ID_NONE) return;
  chrome.storage.local.get(['isRecording'], (data) => {
    if (!data.isRecording) return;
    chrome.tabs.query({ active: true, windowId }, (tabs) => {
      if (!tabs || !tabs[0]) return;
      const tab = tabs[0];
      const event = {
        timestamp: new Date().toISOString(),
        eventType: 'tabFocus',
        url: tab.url || '',
        pageTitle: tab.title || '',
        data: {
          tabId: tab.id,
          windowId,
          type: 'windowFocus'
        }
      };
      chrome.storage.local.get(['events'], (d) => {
        const events = d.events || [];
        events.push(event);
        chrome.storage.local.set({ events });
      });
    });
  });
});
