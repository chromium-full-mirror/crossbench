// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

/**
 * DOM UI state management, status badges, log viewer, and initialization
 * overlay.
 */

import {isWebUsbSupported} from './webadb_bridge';

export const isTestEnvironment = typeof process !== 'undefined' &&
    (Boolean(process.env.VITEST) || process.env.NODE_ENV === 'test');

export let isBenchmarkRunning = false;

export function setBenchmarkRunning(running: boolean): void {
  isBenchmarkRunning = running;
}

export function handleBeforeUnload(event: BeforeUnloadEvent): string|undefined {
  if (isBenchmarkRunning) {
    event.preventDefault();
    event.returnValue = '';
    return '';
  }
  return undefined;
}

if (typeof window !== 'undefined') {
  window.addEventListener('beforeunload', handleBeforeUnload);
}

export function log(
    message: string, _type: 'info'|'success'|'warn'|'error' = 'info') {
  const timestamp = new Date().toLocaleTimeString();
  const logEl = document.getElementById('log-output') as HTMLElement | null;
  if (logEl) {
    const line = `[${timestamp}] ${message}`;
    logEl.textContent =
        logEl.textContent ? `${logEl.textContent}\n${line}` : line;
    logEl.scrollTop = logEl.scrollHeight;
  }
}

export function updateDownloadProgressBar(
    loaded: number, total: number, labelPrefix = 'Downloading'): void {
  const statusText =
      document.getElementById('download-status-text') as HTMLElement | null;
  const percentage =
      document.getElementById('download-percentage') as HTMLElement | null;
  const progressBar =
      document.getElementById('download-progress-bar') as HTMLElement | null;

  const loadedMb = (loaded / (1024 * 1024)).toFixed(1);
  if (total > 0) {
    const pct = Math.min(100, Math.round((loaded / total) * 100));
    const totalMb = (total / (1024 * 1024)).toFixed(1);
    if (statusText) {
      statusText.innerText =
          `${labelPrefix}: ${loadedMb} MB / ${totalMb} MB (${pct}%)`;
    }
    if (percentage) {
      percentage.innerText = `${pct}%`;
    }
    if (progressBar) {
      progressBar.style.width = `${pct}%`;
    }
  } else {
    if (statusText) {
      statusText.innerText = `${labelPrefix}: ${loadedMb} MB...`;
    }
  }
}

const INTERACTIVE_ELEMENT_IDS = [
  'target-archive-input',
  'gcs-token-input',
  'btn-save-token',
  'btn-download-archive',
  'btn-clear-cache',
  'btn-gis-signin',
  'btn-gis-signout',
  'btn-gis-refresh',
  'btn-clear-token',
  'btn-copy-log',
];

export function setInitializing(initializing: boolean, statusText?: string) {
  const overlay = document.getElementById('init-overlay') as HTMLElement | null;
  const overlayText =
      document.getElementById('init-overlay-text') as HTMLElement | null;
  const container = document.querySelector('.container') as HTMLElement | null;

  if (overlayText && statusText) {
    overlayText.innerText = statusText;
  }

  if (initializing) {
    if (overlay) {
      overlay.classList.remove('hidden');
      overlay.style.display = 'flex';
    }
    if (container) {
      container.classList.add('ui-disabled');
    }
    document.querySelectorAll('button, input').forEach((el) => {
      (el as HTMLButtonElement | HTMLInputElement).disabled = true;
    });
    const badge =
        document.getElementById('connection-status') as HTMLElement | null;
    if (badge) {
      badge.innerHTML = '<span class="spinner"></span> Initializing...';
      badge.className = 'status-badge loading';
    }
    const devInfo =
        document.getElementById('device-info') as HTMLElement | null;
    if (devInfo) {
      devInfo.innerText = statusText || 'Initializing web runner modules...';
    }
    const connErr =
        document.getElementById('connection-error') as HTMLElement | null;
    if (connErr) {
      connErr.innerText = '';
      connErr.style.display = 'none';
    }
  } else {
    if (overlay) {
      overlay.classList.add('hidden');
      overlay.style.display = 'none';
    }
    if (container) {
      container.classList.remove('ui-disabled');
    }
    for (const id of INTERACTIVE_ELEMENT_IDS) {
      const el = document.getElementById(id) as | HTMLInputElement |
          HTMLButtonElement | null;
      if (el) {
        el.disabled = false;
      }
    }
  }
}

export function setupUIEventListeners(): void {
  const btnCopyLog =
      document.getElementById('btn-copy-log') as HTMLButtonElement | null;
  const logOutput = document.getElementById('log-output') as HTMLElement | null;

  if (btnCopyLog) {
    btnCopyLog.addEventListener('click', async () => {
      if (!logOutput) {
        return;
      }
      const text = logOutput.textContent || logOutput.innerText || '';
      try {
        if (!navigator?.clipboard?.writeText) {
          throw new Error('Clipboard API is not available');
        }
        await navigator.clipboard.writeText(text);
        const originalText = btnCopyLog.innerText;
        btnCopyLog.innerText = '✓ Copied!';
        setTimeout(() => {
          btnCopyLog.innerText = originalText;
        }, 2000);
      } catch (err) {
        console.error('Failed to copy logs to clipboard:', err);
        log(`Failed to copy logs to clipboard: ${err}`, 'warn');
      }
    });
  }
}

export function updateUI(
    connected: boolean, serial?: string|null, errorMessage?: string|null) {
  const badge =
      document.getElementById('connection-status') as HTMLElement | null;
  const devInfo = document.getElementById('device-info') as HTMLElement | null;
  const connectBtn =
      document.getElementById('btn-connect') as HTMLButtonElement | null;
  const disconnectBtn =
      document.getElementById('btn-disconnect') as HTMLButtonElement | null;
  const connErr =
      document.getElementById('connection-error') as HTMLElement | null;
  const benchCard =
      document.getElementById('benchmark-card') as HTMLElement | null;
  const benchInput =
      document.getElementById('benchmark-cmd') as HTMLInputElement | null;
  const runBtn =
      document.getElementById('btn-run-benchmark') as HTMLButtonElement | null;
  const stopBtn =
      document.getElementById('btn-stop-benchmark') as HTMLButtonElement | null;

  if (connErr) {
    if (!connected && errorMessage) {
      connErr.innerText = errorMessage;
      connErr.style.display = 'block';
    } else {
      connErr.innerText = '';
      connErr.style.display = 'none';
    }
  }

  if (connected) {
    if (badge) {
      badge.innerText = 'Connected';
      badge.className = 'status-badge connected';
    }
    if (devInfo) {
      devInfo.innerText = `Connected Serial ID: ${serial ?? 'USB Device'}`;
    }
    if (connectBtn)
      connectBtn.style.display = 'none';
    if (disconnectBtn) {
      disconnectBtn.style.display = 'inline-block';
      disconnectBtn.disabled = false;
    }
    if (benchCard)
      benchCard.style.opacity = '1';
    if (benchInput)
      benchInput.disabled = false;
    if (runBtn) {
      runBtn.style.display = 'inline-block';
      runBtn.disabled = false;
    }
    if (stopBtn) {
      stopBtn.style.display = 'none';
      stopBtn.disabled = true;
    }
  } else if (!isWebUsbSupported()) {
    if (badge) {
      badge.innerText = 'WebUSB Not Supported';
      badge.className = 'status-badge expired';
    }
    if (devInfo) {
      devInfo.innerText =
          'WebUSB is not supported in this browser. Please use a browser ' +
          'with WebUSB support (e.g. Google Chrome).';
    }
    if (connectBtn) {
      connectBtn.style.display = 'inline-block';
      connectBtn.disabled = true;
      connectBtn.title =
          'WebUSB is not supported in this browser. Please use Google Chrome.';
    }
    if (disconnectBtn)
      disconnectBtn.style.display = 'none';
    if (benchCard)
      benchCard.style.opacity = '0.5';
    if (benchInput)
      benchInput.disabled = true;
    if (runBtn) {
      runBtn.style.display = 'inline-block';
      runBtn.disabled = true;
    }
    if (stopBtn) {
      stopBtn.style.display = 'none';
      stopBtn.disabled = true;
    }
  } else {
    if (badge) {
      badge.innerText = 'Disconnected';
      badge.className = 'status-badge';
    }
    if (devInfo) {
      devInfo.innerText = 'No device connected.';
    }
    if (connectBtn) {
      connectBtn.style.display = 'inline-block';
      connectBtn.disabled = false;
      connectBtn.removeAttribute('title');
    }
    if (disconnectBtn)
      disconnectBtn.style.display = 'none';
    if (benchCard)
      benchCard.style.opacity = '0.5';
    if (benchInput)
      benchInput.disabled = true;
    if (runBtn) {
      runBtn.style.display = 'inline-block';
      runBtn.disabled = true;
    }
    if (stopBtn) {
      stopBtn.style.display = 'none';
      stopBtn.disabled = true;
    }
  }
}
