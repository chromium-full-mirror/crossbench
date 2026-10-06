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
  if (typeof document !== 'undefined') {
    const runningWarning = document.getElementById(
                               'benchmark-running-warning',
                               ) as HTMLElement |
        null;
    if (runningWarning) {
      runningWarning.style.display = running ? 'block' : 'none';
    }
  }
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

export type RunnerMode = 'simple'|'developer';
export const RUNNER_MODE_STORAGE_KEY = 'crossbench_runner_mode';

let currentRunnerMode: RunnerMode = 'simple';

export function getRunnerMode(): RunnerMode {
  if (typeof document !== 'undefined') {
    const simpleVariantEl = document.getElementById('simple-benchmark-variant');
    if (!simpleVariantEl) {
      return 'developer';
    }
  }
  return currentRunnerMode;
}

export function setRunnerMode(
    mode: RunnerMode, onModeChange?: (mode: RunnerMode) => void): void {
  currentRunnerMode = mode;
  try {
    localStorage.setItem(RUNNER_MODE_STORAGE_KEY, mode);
  } catch (err) {
    console.warn('Failed to persist runner mode:', err);
  }

  if (typeof document === 'undefined') {
    return;
  }

  const btnSimple =
      document.getElementById('btn-mode-simple') as HTMLButtonElement | null;
  const btnDev =
      document.getElementById('btn-mode-developer') as HTMLButtonElement | null;

  if (btnSimple) {
    btnSimple.classList.toggle('active', mode === 'simple');
    btnSimple.setAttribute('aria-selected', String(mode === 'simple'));
  }
  if (btnDev) {
    btnDev.classList.toggle('active', mode === 'developer');
    btnDev.setAttribute('aria-selected', String(mode === 'developer'));
  }

  const simpleArchiveSection =
      document.getElementById('simple-archive-section') as HTMLElement | null;
  const devArchiveSection =
      document.getElementById('dev-archive-section') as HTMLElement | null;
  const simpleBenchmarkSection =
      document.getElementById('simple-benchmark-section') as HTMLElement | null;
  const devBenchmarkSection =
      document.getElementById('dev-benchmark-section') as HTMLElement | null;
  const simpleProgressCard =
      document.getElementById('simple-progress-card') as HTMLElement | null;
  const devLogCard =
      document.getElementById('dev-log-card') as HTMLElement | null;

  const isSimple = mode === 'simple';
  if (simpleArchiveSection) {
    simpleArchiveSection.style.display = isSimple ? 'block' : 'none';
  }
  if (devArchiveSection) {
    devArchiveSection.style.display = isSimple ? 'none' : 'block';
  }
  if (simpleBenchmarkSection) {
    simpleBenchmarkSection.style.display = isSimple ? 'block' : 'none';
  }
  if (devBenchmarkSection) {
    devBenchmarkSection.style.display = isSimple ? 'none' : 'block';
  }
  if (simpleProgressCard) {
    simpleProgressCard.style.display = isSimple ? 'block' : 'none';
  }
  if (devLogCard) {
    devLogCard.style.display = isSimple ? 'none' : 'block';
  }

  if (onModeChange) {
    onModeChange(mode);
  }
}

export function updateBenchmarkProgressBar(
    completed: number, total: number, statusMessage?: string): void {
  const statusEl =
      document.getElementById('simple-progress-status') as HTMLElement | null;
  const percentageEl =
      document.getElementById('simple-progress-percentage') as HTMLElement |
      null;
  const barEl =
      document.getElementById('simple-progress-bar') as HTMLElement | null;

  if (statusEl && statusMessage !== undefined) {
    statusEl.innerText = statusMessage;
  }

  if (total > 0) {
    const clamped = Math.max(0, Math.min(total, completed));
    const pct = Math.round((clamped / total) * 100);
    if (percentageEl) {
      percentageEl.innerText = `${clamped} / ${total} (${pct}%)`;
    }
    if (barEl) {
      barEl.style.width = `${pct}%`;
    }
  } else {
    if (percentageEl) {
      percentageEl.innerText = '0%';
    }
    if (barEl) {
      barEl.style.width = '0%';
    }
  }
}

export function parseCsvToRows(csvText: string): string[][] {
  const rows: string[][] = [];
  const lines = csvText.replace(/\r\n/g, '\n').split('\n');
  for (const rawLine of lines) {
    if (!rawLine.trim()) {
      continue;
    }
    const cells: string[] = [];
    let current = '';
    let inQuotes = false;
    for (let i = 0; i < rawLine.length; i++) {
      const ch = rawLine[i];
      if (inQuotes) {
        if (ch === '"' && rawLine[i + 1] === '"') {
          current += '"';
          i++;
        } else if (ch === '"') {
          inQuotes = false;
        } else {
          current += ch;
        }
      } else if (ch === '"') {
        inQuotes = true;
      } else if (ch === ',') {
        cells.push(current.trim());
        current = '';
      } else {
        current += ch;
      }
    }
    cells.push(current.trim());
    rows.push(cells);
  }
  return rows;
}

export function clearBenchmarkScoreTable(): void {
  const container =
      document.getElementById('simple-score-container') as HTMLElement | null;
  const wrapper =
      document.getElementById('simple-score-table-wrapper') as HTMLElement |
      null;
  if (wrapper) {
    wrapper.innerHTML = '';
  }
  if (container) {
    container.style.display = 'none';
  }
}

export function renderBenchmarkScoreTable(csvText: string): void {
  const container =
      document.getElementById('simple-score-container') as HTMLElement | null;
  const wrapper =
      document.getElementById('simple-score-table-wrapper') as HTMLElement |
      null;
  if (!container || !wrapper) {
    return;
  }

  const rows = parseCsvToRows(csvText);
  if (rows.length === 0) {
    clearBenchmarkScoreTable();
    return;
  }

  wrapper.innerHTML = '';
  const table = document.createElement('table');
  table.id = 'benchmark-score-table';
  table.className = 'score-table';

  const thead = document.createElement('thead');
  const headerTr = document.createElement('tr');
  for (const headerCell of rows[0]) {
    const th = document.createElement('th');
    th.textContent = headerCell;
    headerTr.appendChild(th);
  }
  thead.appendChild(headerTr);
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  for (let i = 1; i < rows.length; i++) {
    const row = rows[i];
    const tr = document.createElement('tr');
    if (row[0] === 'TOTAL_SCORE') {
      tr.className = 'score-total-row';
    }
    for (const cell of row) {
      const td = document.createElement('td');
      td.textContent = cell;
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);

  wrapper.appendChild(table);
  container.style.display = 'block';
}

const INTERACTIVE_ELEMENT_IDS = [
  'btn-mode-simple',
  'btn-mode-developer',
  'simple-benchmark-variant',
  'btn-simple-download-archive',
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
    document.querySelectorAll('button, input, select').forEach((el) => {
      (el as HTMLButtonElement | HTMLInputElement | HTMLSelectElement)
          .disabled = true;
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
    for (const errId
             of ['connection-error', 'simple-download-error',
                 'download-error']) {
      const errEl = document.getElementById(errId) as HTMLElement | null;
      if (errEl) {
        errEl.innerText = '';
        errEl.style.display = 'none';
      }
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
          HTMLButtonElement | HTMLSelectElement | null;
      if (el) {
        el.disabled = false;
      }
    }
  }
}

export function setupUIEventListeners(
    onModeChange?: (mode: RunnerMode) => void): void {
  const btnModeSimple =
      document.getElementById('btn-mode-simple') as HTMLButtonElement | null;
  const btnModeDev =
      document.getElementById('btn-mode-developer') as HTMLButtonElement | null;

  try {
    const savedMode = localStorage.getItem(RUNNER_MODE_STORAGE_KEY);
    if (savedMode === 'simple' || savedMode === 'developer') {
      currentRunnerMode = savedMode;
    } else {
      currentRunnerMode = 'simple';
    }
  } catch {
    currentRunnerMode = 'simple';
  }
  if (btnModeSimple || btnModeDev) {
    setRunnerMode(currentRunnerMode, onModeChange);
  }

  if (btnModeSimple) {
    btnModeSimple.addEventListener('click', () => {
      setRunnerMode('simple', onModeChange);
    });
  }
  if (btnModeDev) {
    btnModeDev.addEventListener('click', () => {
      setRunnerMode('developer', onModeChange);
    });
  }

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
  const simpleBrowserSelect =
      document.getElementById('simple-browser-select') as HTMLSelectElement |
      null;
  const simpleRepetitionsSelect =
      document.getElementById('simple-repetitions-select') as
          HTMLSelectElement |
      null;
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
    if (simpleBrowserSelect) {
      const hasValidBrowser = Array.from(simpleBrowserSelect.options)
                                  .some((opt) => Boolean(opt.value));
      simpleBrowserSelect.disabled = !hasValidBrowser;
    }
    if (simpleRepetitionsSelect) {
      simpleRepetitionsSelect.disabled = false;
    }
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
    if (simpleBrowserSelect) {
      simpleBrowserSelect.innerHTML =
          '<option value="">Connect a device to load browsers...</option>';
      simpleBrowserSelect.disabled = true;
    }
    if (simpleRepetitionsSelect) {
      simpleRepetitionsSelect.disabled = true;
    }
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
    if (simpleBrowserSelect) {
      simpleBrowserSelect.innerHTML =
          '<option value="">Connect a device to load browsers...</option>';
      simpleBrowserSelect.disabled = true;
    }
    if (simpleRepetitionsSelect) {
      simpleRepetitionsSelect.disabled = true;
    }
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
