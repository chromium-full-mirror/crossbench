// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {beforeEach, describe, expect, it, vi} from 'vitest';

import {parseCommandLine} from '../src/main';

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.restoreAllMocks();

  const mockDb: any = {
    transaction: () => ({
      objectStore: () => ({
        get: () => {
          const req: any = {result: null};
          queueMicrotask(() => req.onsuccess && req.onsuccess());
          return req;
        },
        put: () => {
          const req: any = {};
          queueMicrotask(() => req.onsuccess && req.onsuccess());
          return req;
        },
        delete: () => {
          const req: any = {};
          queueMicrotask(() => req.onsuccess && req.onsuccess());
          return req;
        },
      }),
    }),
  };

  const mockFactory: any = {
    open: () => {
      const req: any = {result: mockDb};
      queueMicrotask(() => req.onsuccess && req.onsuccess());
      return req;
    },
  };

  (globalThis as any).indexedDB = mockFactory;
  (window as any).indexedDB = mockFactory;
});

describe('parseCommandLine', () => {
  it('handles empty or whitespace strings', () => {
    expect(parseCommandLine('')).toEqual([]);
    expect(parseCommandLine('   ')).toEqual([]);
  });

  it('parses simple benchmark command line arguments', () => {
    expect(parseCommandLine('loadline2-phone --browser cdp:chrome')).toEqual([
      'loadline2-phone',
      '--browser',
      'cdp:chrome',
    ]);
  });

  it('strips leading ./cb.py, cb.py, cb, and crossbench prefixes', () => {
    expect(parseCommandLine('./cb.py loadline2-phone --browser cdp:chrome'))
        .toEqual([
          'loadline2-phone',
          '--browser',
          'cdp:chrome',
        ]);
    expect(parseCommandLine(
               'cb.py loading --browser cdp:chrome --url https://google.com'))
        .toEqual([
          'loading',
          '--browser',
          'cdp:chrome',
          '--url',
          'https://google.com',
        ]);
    expect(parseCommandLine('cb speedometer --browser cdp:chrome')).toEqual([
      'speedometer',
      '--browser',
      'cdp:chrome',
    ]);
    expect(parseCommandLine('crossbench loadline2-phone --browser cdp:chrome'))
        .toEqual([
          'loadline2-phone',
          '--browser',
          'cdp:chrome',
        ]);
  });

  it('strips leading python / python3 / vpython3 wrapper prefixes', () => {
    expect(parseCommandLine(
               'python3 ./cb.py loadline2-phone --browser cdp:chrome'))
        .toEqual([
          'loadline2-phone',
          '--browser',
          'cdp:chrome',
        ]);
    expect(parseCommandLine('vpython3 cb.py loading --browser cdp:chrome'))
        .toEqual([
          'loading',
          '--browser',
          'cdp:chrome',
        ]);
  });

  it('handles quoted arguments containing spaces', () => {
    expect(parseCommandLine(
               'loading --browser cdp:chrome ' +
               '--url "https://example.com/test?a=1&b=2" ' +
               '--extra-flags="--flag1 --flag2"'))
        .toEqual([
          'loading',
          '--browser',
          'cdp:chrome',
          '--url',
          'https://example.com/test?a=1&b=2',
          '--extra-flags=--flag1 --flag2',
        ]);
    expect(parseCommandLine(
               'loading --browser cdp:chrome ' +
               '--url \'https://example.com/path with spaces\''))
        .toEqual([
          'loading',
          '--browser',
          'cdp:chrome',
          '--url',
          'https://example.com/path with spaces',
        ]);
  });
});

describe('getCrossbenchVirtualFiles', () => {
  it('maps crossbench, config, and protoc files correctly without collisions',
     async () => {
       const {getCrossbenchVirtualFiles} = await import('../src/main');
       const files = getCrossbenchVirtualFiles();
       expect(files['/third_party/__init__.py']).toBeDefined();
       expect(files['/third_party/protoc/__init__.py']).toBeDefined();
       expect(files['/tools/__init__.py']).toBeDefined();
       expect(files['/tools/protoc/sys_path.py']).toBeDefined();
       expect(files['/config/probe/perfetto/trace_config/default.txtpb'])
           .toBeDefined();
       expect(files['/crossbench/cli/cli.py']).toBeDefined();
     });
});

describe('UI keyboard interaction', () => {
  it('triggers run benchmark when Enter is pressed in benchmark input',
     async () => {
       document.body.innerHTML = `
      <input id="benchmark-cmd" value="loading --browser cdp:chrome" />
      <button id="btn-run-benchmark"></button>
    `;
       const {setupBenchmarkEventListeners} = await import('../src/main');
       const input =
           document.getElementById('benchmark-cmd') as HTMLInputElement;
       const button =
           document.getElementById('btn-run-benchmark') as HTMLButtonElement;

       const mockBridge = {
         isConnected: false,
         serial: null,
       } as any;
       setupBenchmarkEventListeners(mockBridge);

       let clicked = false;
       button.addEventListener('click', () => {
         clicked = true;
       });

       const enterEvent =
           new KeyboardEvent('keydown', {key: 'Enter', cancelable: true});
       input.dispatchEvent(enterEvent);
       expect(clicked).toBe(true);
       expect(enterEvent.defaultPrevented).toBe(true);

       // When button is disabled, click is not triggered
       clicked = false;
       button.disabled = true;
       const enterDisabledEvent =
           new KeyboardEvent('keydown', {key: 'Enter', cancelable: true});
       input.dispatchEvent(enterDisabledEvent);
       expect(clicked).toBe(false);
     });
});

describe('getTargetArchiveUrl', () => {
  it('returns default archive url when input is missing or empty', async () => {
    const {getTargetArchiveUrl} = await import('../src/main');
    const url = getTargetArchiveUrl();
    expect(url).toBe(
        'gs://chrome-partner-loadline/archive_phone_20260331.wprgo');
  });

  it('returns custom archive url when target-archive-input is set',
     async () => {
       const input = document.createElement('input');
       input.id = 'target-archive-input';
       input.value = 'gs://custom-bucket/custom_archive.wprgo';
       document.body.appendChild(input);

       const {getTargetArchiveUrl} = await import('../src/main');
       expect(getTargetArchiveUrl())
           .toBe('gs://custom-bucket/custom_archive.wprgo');
       document.body.removeChild(input);
     });
});

describe('setInitializing', () => {
  it('toggles overlay, container classes, and disables/enables elements',
     async () => {
       document.body.innerHTML = `
      <div class="container">
        <button id="btn-connect">Connect</button>
        <input id="target-archive-input" value="gs://test/archive.wprgo" />
        <input id="gcs-token-input" value="" />
        <button id="btn-save-token">Save</button>
      </div>
      <div id="init-overlay" class="init-overlay hidden">
        <div id="init-overlay-text">Initializing...</div>
      </div>
      <span id="connection-status"></span>
      <p id="device-info"></p>
    `;

       const {setInitializing} = await import('../src/main');
       const container = document.querySelector('.container') as HTMLElement;
       const overlay = document.getElementById('init-overlay') as HTMLElement;
       const btnConnect =
           document.getElementById('btn-connect') as HTMLButtonElement;
       const targetInput =
           document.getElementById('target-archive-input') as HTMLInputElement;

       // Set initializing to true
       setInitializing(true, 'Preparing environment...');
       expect(container.classList.contains('ui-disabled')).toBe(true);
       expect(overlay.classList.contains('hidden')).toBe(false);
       expect(overlay.style.display).toBe('flex');
       expect(btnConnect.disabled).toBe(true);
       expect(targetInput.disabled).toBe(true);

       // Set initializing to false
       setInitializing(false);
       expect(container.classList.contains('ui-disabled')).toBe(false);
       expect(overlay.classList.contains('hidden')).toBe(true);
       expect(overlay.style.display).toBe('none');
       expect(targetInput.disabled).toBe(false);
     });
});

describe('updateGcsUI', () => {
  it('updates UI elements for GIS authenticated session', async () => {
    document.body.innerHTML = `
      <span id="auth-status"></span>
      <span id="cache-status"></span>
      <input
        id="target-archive-input"
        value="gs://chrome-partner-loadline/archive_phone_20260331.wprgo" />
      <input id="gcs-token-input" value="" />
      <button id="btn-gis-signin"></button>
      <button id="btn-gis-signout" style="display: none;"></button>
      <button id="btn-gis-refresh" style="display: none;"></button>
      <button id="btn-clear-token" style="display: none;"></button>
      <button id="btn-download-archive"></button>
      <button id="btn-clear-cache" style="display: none;"></button>
    `;

    const {setStoredAuthSession} = await import('../src/gis_auth');
    const {updateGcsUI} = await import('../src/main');

    setStoredAuthSession({
      accessToken: 'mock_token_mock_valid',
      tokenType: 'Bearer',
      expiresAt: Date.now() + 3000 * 1000,
      scope: 'https://www.googleapis.com/auth/devstorage.read_only',
      userEmail: 'googler@google.com',
    });

    await updateGcsUI();

    const authBadge = document.getElementById('auth-status') as HTMLElement;
    const signInBtn =
        document.getElementById('btn-gis-signin') as HTMLButtonElement;
    const signOutBtn =
        document.getElementById('btn-gis-signout') as HTMLButtonElement;

    expect(authBadge.innerText).toContain('Authenticated (googler@google.com)');
    expect(authBadge.classList.contains('connected')).toBe(true);
    expect(signInBtn.style.display).toBe('none');
    expect(signOutBtn.style.display).toBe('inline-block');
  });

  it('updates UI elements when GIS session is expired', async () => {
    document.body.innerHTML = `
      <span id="auth-status"></span>
      <span id="cache-status"></span>
      <input
        id="target-archive-input"
        value="gs://chrome-partner-loadline/archive_phone_20260331.wprgo" />
      <input id="gcs-token-input" value="" />
      <button id="btn-gis-signin"></button>
      <button id="btn-gis-signout" style="display: none;"></button>
      <button id="btn-gis-refresh" style="display: none;"></button>
      <button id="btn-clear-token" style="display: none;"></button>
      <button id="btn-download-archive"></button>
      <button id="btn-clear-cache" style="display: none;"></button>
    `;

    const {setStoredAuthSession} = await import('../src/gis_auth');
    const {updateGcsUI} = await import('../src/main');

    setStoredAuthSession({
      accessToken: 'mock_token_mock_expired',
      tokenType: 'Bearer',
      expiresAt: Date.now() - 5000,
      scope: 'https://www.googleapis.com/auth/devstorage.read_only',
      userEmail: 'googler@google.com',
    });

    await updateGcsUI();

    const authBadge = document.getElementById('auth-status') as HTMLElement;
    const refreshBtn =
        document.getElementById('btn-gis-refresh') as HTMLButtonElement;

    expect(authBadge.innerText).toContain('OAuth Token Expired');
    expect(authBadge.classList.contains('warning')).toBe(true);
    expect(refreshBtn.style.display).toBe('inline-block');
  });

  it('updates UI elements for manual token input', async () => {
    document.body.innerHTML = `
      <span id="auth-status"></span>
      <span id="cache-status"></span>
      <input
        id="target-archive-input"
        value="gs://chrome-partner-loadline/archive_phone_20260331.wprgo" />
      <input id="gcs-token-input" value="" />
      <button id="btn-gis-signin"></button>
      <button id="btn-gis-signout" style="display: none;"></button>
      <button id="btn-gis-refresh" style="display: none;"></button>
      <button id="btn-clear-token" style="display: none;"></button>
      <button id="btn-download-archive"></button>
      <button id="btn-clear-cache" style="display: none;"></button>
    `;

    const {clearAuthSession} = await import('../src/gis_auth');
    const {setStoredAccessToken} = await import('../src/gcs_cache');
    const {updateGcsUI} = await import('../src/main');

    clearAuthSession();
    setStoredAccessToken('mock_token_manual_test_123');

    await updateGcsUI();

    const authBadge = document.getElementById('auth-status') as HTMLElement;
    const clearTokenBtn =
        document.getElementById('btn-clear-token') as HTMLButtonElement;

    expect(authBadge.innerText).toBe('Manual Token Set');
    expect(authBadge.classList.contains('connected')).toBe(true);
    expect(clearTokenBtn.style.display).toBe('inline-block');
  });
});

describe('Interrupt Benchmark UI interaction', () => {
  it('updates status on run button and allows re-clicking interrupt button',
     async () => {
       document.body.innerHTML = `
      <button id="btn-run-benchmark" class="btn" disabled>⏳ Running...</button>
      <button id="btn-stop-benchmark" class="btn btn-danger">
        ⏹️ Interrupt Execution
      </button>
      <span id="connection-status" class="status-badge tracing">
        Benchmark in Progress...
      </span>
    `;
       const {setupBenchmarkEventListeners} = await import('../src/main');
       const btnRun =
           document.getElementById('btn-run-benchmark') as HTMLButtonElement;
       const btnStop =
           document.getElementById('btn-stop-benchmark') as HTMLButtonElement;
       const status =
           document.getElementById('connection-status') as HTMLElement;

       const mockBridge = {
         isConnected: false,
         serial: null,
       } as any;
       setupBenchmarkEventListeners(mockBridge);

       btnStop.click();

       expect(btnStop.disabled).toBe(false);
       expect(btnRun.innerText).toBe('⏹️ Stopping...');
       expect(status.innerText).toBe('Stopping Benchmark...');
       expect(status.classList.contains('warning')).toBe(true);

       // Can be clicked again
       btnStop.click();
       expect(btnStop.disabled).toBe(false);
     });
});

describe('Page Unload Protection (beforeunload)', () => {
  it('returns undefined when benchmark is not running', async () => {
    const {handleBeforeUnload} = await import('../src/main');
    const mockEvent = {
      preventDefault: vi.fn(),
      returnValue: undefined,
    } as unknown as BeforeUnloadEvent;

    const result = handleBeforeUnload(mockEvent);
    expect(result).toBeUndefined();
    expect(mockEvent.preventDefault).not.toHaveBeenCalled();
  });

  it('prevents default and sets returnValue when benchmark is running',
     async () => {
       const {handleBeforeUnload, setBenchmarkRunning} =
           await import('../src/main');
       setBenchmarkRunning(true);

       const mockEvent = {
         preventDefault: vi.fn(),
         returnValue: undefined,
       } as unknown as BeforeUnloadEvent;

       const result = handleBeforeUnload(mockEvent);
       expect(result).toBe('');
       expect(mockEvent.preventDefault).toHaveBeenCalled();
       expect(mockEvent.returnValue).toBe('');

       setBenchmarkRunning(false);
     });
});

describe('Log Output Formatting', () => {
  it('appends log messages without emoji prefixes', async () => {
    document.body.innerHTML = `
      <div id="log-output" class="console-log"></div>
    `;
    const {log} = await import('../src/main');
    const logEl = document.getElementById('log-output') as HTMLElement;

    log('Testing info message', 'info');
    log('Testing error message', 'error');
    log('Testing warning message', 'warn');
    log('Testing success message', 'success');

    const output = logEl.innerText;
    expect(output).toContain('Testing info message');
    expect(output).toContain('Testing error message');
    expect(output).toContain('Testing warning message');
    expect(output).toContain('Testing success message');

    // Ensure no emojis exist in the log output
    expect(output).not.toContain('❌');
    expect(output).not.toContain('ℹ️');
    expect(output).not.toContain('✅');
    expect(output).not.toContain('⚠️');
    expect(output).not.toContain('⏹️');
  });
});

describe('WebUSB Browser Support Detection in UI', () => {
  it('enables connect button when WebUSB is supported', async () => {
    const originalNavigator = globalThis.navigator;
    Object.defineProperty(globalThis, 'navigator', {
      value: {usb: {}},
      configurable: true,
      writable: true,
    });

    document.body.innerHTML = `
      <span id="connection-status" class="status-badge"></span>
      <p id="device-info"></p>
      <button id="btn-connect" class="btn" disabled>
        Connect Android Device (WebUSB)
      </button>
      <button id="btn-disconnect" class="btn btn-danger" style="display: none;">
        Disconnect Device
      </button>
      <div id="benchmark-card"></div>
      <input id="benchmark-cmd" disabled />
      <button id="btn-run-benchmark" disabled></button>
      <button id="btn-stop-benchmark" style="display: none;"></button>
    `;

    const {updateUI} = await import('../src/main');
    updateUI(false);

    const badge = document.getElementById('connection-status') as HTMLElement;
    const devInfo = document.getElementById('device-info') as HTMLElement;
    const btnConnect =
        document.getElementById('btn-connect') as HTMLButtonElement;

    expect(badge.innerText).toBe('Disconnected');
    expect(badge.className).toBe('status-badge');
    expect(devInfo.innerText).toBe('No device connected.');
    expect(btnConnect.disabled).toBe(false);
    expect(btnConnect.title).toBe('');

    Object.defineProperty(globalThis, 'navigator', {
      value: originalNavigator,
      configurable: true,
      writable: true,
    });
  });

  it('shows recommendation to use Chrome when WebUSB is not supported',
     async () => {
       const originalNavigator = globalThis.navigator;
       // Simulate browser without WebUSB (e.g. Firefox, Safari)
       Object.defineProperty(globalThis, 'navigator', {
         value: {},
         configurable: true,
         writable: true,
       });

       document.body.innerHTML = `
      <span id="connection-status" class="status-badge"></span>
      <p id="device-info"></p>
      <button id="btn-connect" class="btn">
        Connect Android Device (WebUSB)
      </button>
      <button id="btn-disconnect" class="btn btn-danger" style="display: none;">
        Disconnect Device
      </button>
      <div id="benchmark-card"></div>
      <input id="benchmark-cmd" />
      <button id="btn-run-benchmark"></button>
      <button id="btn-stop-benchmark" style="display: none;"></button>
    `;

       const {updateUI} = await import('../src/main');
       updateUI(false);

       const badge =
           document.getElementById('connection-status') as HTMLElement;
       const devInfo = document.getElementById('device-info') as HTMLElement;
       const btnConnect =
           document.getElementById('btn-connect') as HTMLButtonElement;

       expect(badge.innerText).toBe('WebUSB Not Supported');
       expect(badge.classList.contains('expired')).toBe(true);
       expect(devInfo.innerText)
           .toContain('WebUSB is not supported in this browser');
       expect(devInfo.innerText).toContain('Chrome');
       expect(btnConnect.disabled).toBe(true);
       expect(btnConnect.title).toContain('WebUSB is not supported');

       Object.defineProperty(globalThis, 'navigator', {
         value: originalNavigator,
         configurable: true,
         writable: true,
       });
     });

  it('initApp logs warning recommending compatible browser when ' +
         'WebUSB is missing',
     async () => {
       const originalNavigator = globalThis.navigator;
       Object.defineProperty(globalThis, 'navigator', {
         value: {},
         configurable: true,
         writable: true,
       });

       document.body.innerHTML = `
      <div id="init-overlay" class="init-overlay hidden">
        <div id="init-overlay-text">Initializing...</div>
      </div>
      <span id="connection-status"></span>
      <p id="device-info"></p>
      <span id="auth-status"></span>
      <span id="cache-status"></span>
      <input id="target-archive-input" value="gs://test/archive.wprgo" />
      <input id="gcs-token-input" value="" />
      <button id="btn-connect"></button>
      <div id="log-output" class="console-log"></div>
    `;

       const {initApp} = await import('../src/main');
       await initApp();

       const logEl = document.getElementById('log-output') as HTMLElement;
       expect(logEl.innerText)
           .toContain('WebUSB is not supported in this browser');
       expect(logEl.innerText).toContain('Chrome');

       Object.defineProperty(globalThis, 'navigator', {
         value: originalNavigator,
         configurable: true,
         writable: true,
       });
     });
});

describe('setupUIEventListeners', () => {
  it('copies log output to clipboard and updates button state', async () => {
    document.body.innerHTML = `
      <button id="btn-copy-log">📋 Copy Log</button>
      <div id="log-output"></div>
    `;
    const logEl = document.getElementById('log-output') as HTMLElement;
    logEl.textContent = 'Sample log line 1\nSample log line 2';
    const {setupUIEventListeners} = await import('../src/main');
    const btnCopy =
        document.getElementById('btn-copy-log') as HTMLButtonElement;

    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(globalThis.navigator, 'clipboard', {
      value: {writeText: writeTextMock},
      configurable: true,
      writable: true,
    });

    setupUIEventListeners();
    btnCopy.click();
    await Promise.resolve();

    expect(writeTextMock)
        .toHaveBeenCalledWith('Sample log line 1\nSample log line 2');
    expect(btnCopy.innerText).toBe('✓ Copied!');
  });

  it('preserves newlines when copying logs generated via log()', async () => {
    document.body.innerHTML = `
      <button id="btn-copy-log">📋 Copy Log</button>
      <div id="log-output"></div>
    `;
    const {log, setupUIEventListeners} = await import('../src/main');
    const {log: authLog} = await import('../src/auth_ui');
    const btnCopy =
        document.getElementById('btn-copy-log') as HTMLButtonElement;

    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(globalThis.navigator, 'clipboard', {
      value: {writeText: writeTextMock},
      configurable: true,
      writable: true,
    });

    log('First line');
    authLog('Second line from auth');
    log('Multi-line\ntraceback');

    setupUIEventListeners();
    btnCopy.click();
    await Promise.resolve();

    expect(writeTextMock).toHaveBeenCalledTimes(1);
    const copiedText = writeTextMock.mock.calls[0][0] as string;
    const lines = copiedText.split('\n');
    expect(lines).toHaveLength(4);
    expect(lines[0]).toContain('First line');
    expect(lines[1]).toContain('Second line from auth');
    expect(lines[2]).toContain('Multi-line');
    expect(lines[3]).toBe('traceback');
  });
});

describe('updateDownloadProgressBar', () => {
  it('updates progress bar and percentage correctly', async () => {
    document.body.innerHTML = `
      <span id="download-status-text"></span>
      <span id="download-percentage"></span>
      <div id="download-progress-bar" style="width: 0%;"></div>
    `;
    const {updateDownloadProgressBar} = await import('../src/main');
    updateDownloadProgressBar(
        50 * 1024 * 1024, 100 * 1024 * 1024, 'Downloading');

    const statusText =
        document.getElementById('download-status-text') as HTMLElement;
    const percentage =
        document.getElementById('download-percentage') as HTMLElement;
    const progressBar =
        document.getElementById('download-progress-bar') as HTMLElement;

    expect(statusText.innerText)
        .toContain('Downloading: 50.0 MB / 100.0 MB (50%)');
    expect(percentage.innerText).toBe('50%');
    expect(progressBar.style.width).toBe('50%');
  });
});

describe('Device Connection Error Reporting', () => {
  it('shows connection error next to the button', async () => {
    const originalNavigator = globalThis.navigator;
    Object.defineProperty(globalThis, 'navigator', {
      value: {usb: {}},
      configurable: true,
      writable: true,
    });

    document.body.innerHTML = `
      <span id="connection-status" class="status-badge"></span>
      <p id="device-info"></p>
      <button id="btn-connect" class="btn">
        Connect Android Device (WebUSB)
      </button>
      <button id="btn-disconnect" class="btn btn-danger" style="display: none;">
        Disconnect Device
      </button>
      <div
        id="connection-error"
        class="connection-error"
        style="display: none;"></div>
      <div id="log-output" class="console-log"></div>
    `;

    const {setupDeviceEventListeners, webAdbBridge} =
        await import('../src/main');
    vi.spyOn(webAdbBridge, 'requestDevice').mockResolvedValue({
      serial: 'mock-device'
    } as any);
    vi.spyOn(webAdbBridge, 'connect')
        .mockRejectedValue(new Error('Unable to claim interface.'));

    setupDeviceEventListeners();
    const btnConnect =
        document.getElementById('btn-connect') as HTMLButtonElement;
    const connErr = document.getElementById('connection-error') as HTMLElement;
    const logEl = document.getElementById('log-output') as HTMLElement;

    btnConnect.click();
    for (let i = 0; i < 5; i++) {
      await Promise.resolve();
    }

    expect(connErr.style.display).toBe('block');
    expect(connErr.innerText)
        .toContain('Connection failed: Unable to claim interface.');
    expect(logEl.textContent)
        .toContain('Connection failed: Unable to claim interface.');

    // Subsequent successful connection clears the error
    vi.spyOn(webAdbBridge, 'connect').mockResolvedValue(undefined);
    vi.spyOn(webAdbBridge, 'serial', 'get').mockReturnValue('mock-device');

    btnConnect.click();
    for (let i = 0; i < 5; i++) {
      await Promise.resolve();
    }

    expect(connErr.style.display).toBe('none');
    expect(connErr.innerText).toBe('');

    Object.defineProperty(globalThis, 'navigator', {
      value: originalNavigator,
      configurable: true,
      writable: true,
    });
  });
});

describe('Input Field Persistence Across Page Reloads', () => {
  it('saves archive and command on Run Benchmark and restores across reloads',
     async () => {
       document.body.innerHTML = `
      <input
        id="target-archive-input"
        value="gs://chrome-partner-loadline/archive_phone_20260331.wprgo" />
      <input
        id="benchmark-cmd"
        value="loadline2-phone --browser cdp:chrome" />
      <button id="btn-run-benchmark"></button>
    `;
       const {setupBenchmarkEventListeners} = await import('../src/main');
       const mockBridge = {isConnected: false, serial: null} as any;

       setupBenchmarkEventListeners(mockBridge);
       const archiveInput =
           document.getElementById('target-archive-input') as HTMLInputElement;
       const cmdInput =
           document.getElementById('benchmark-cmd') as HTMLInputElement;
       const runBtn =
           document.getElementById('btn-run-benchmark') as HTMLButtonElement;

       archiveInput.value = 'gs://custom-bucket/tablet_archive.wprgo';
       cmdInput.value = 'loadline2-tablet --browser cdp:chrome --repeat 3';
       runBtn.click();

       // Simulate page reload with fresh default DOM
       document.body.innerHTML = `
      <input
        id="target-archive-input"
        value="gs://chrome-partner-loadline/archive_phone_20260331.wprgo" />
      <input
        id="benchmark-cmd"
        value="loadline2-phone --browser cdp:chrome" />
      <button id="btn-run-benchmark"></button>
    `;
       setupBenchmarkEventListeners(mockBridge);
       const reloadedArchiveInput =
           document.getElementById('target-archive-input') as HTMLInputElement;
       const reloadedCmdInput =
           document.getElementById('benchmark-cmd') as HTMLInputElement;
       expect(reloadedArchiveInput.value)
           .toBe('gs://custom-bucket/tablet_archive.wprgo');
       expect(reloadedCmdInput.value)
           .toBe('loadline2-tablet --browser cdp:chrome --repeat 3');
     });
});
