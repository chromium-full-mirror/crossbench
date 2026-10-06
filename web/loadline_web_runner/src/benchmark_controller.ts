// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

/**
 * Crossbench benchmark execution controller, file bundling, and worker RPC
 * proxy.
 */

import {getTargetArchiveUrl, syncSimpleChoicesToDevInputs, updateGcsUI,} from './auth_ui';
import {CdpClient} from './cdp_client';
import {downloadGcsArchive, fetchGcsMetadata, getCachedGcsArchive, getStoredAccessToken, parseGcsUrl,} from './gcs_cache';
import {PyodideWorkerClient} from './pyodide_worker';
import {clearBenchmarkScoreTable, getRunnerMode, log, renderBenchmarkScoreTable, setBenchmarkRunning, updateBenchmarkProgressBar, updateDownloadProgressBar, updateUI,} from './ui_state';
import {getBrowserUpgradePath, WebAdbBridge} from './webadb_bridge';

const crossbenchPyFiles = import.meta.glob(
                              [
                                '../../../crossbench/**/*',
                                '../../../config/**/*',
                                '../../../third_party/__init__.py',
                                '../../../third_party/protoc/**/*',
                                '../../../third_party/webpagereplay/*',
                                '../../../third_party/webpagereplay/scripts/*',
                                '../../../tools/__init__.py',
                                '../../../tools/protoc/**/*',
                              ],
                              {
                                query: '?raw',
                                import: 'default',
                                eager: true,
                              }) as Record<string, string>;

export function getCrossbenchVirtualFiles(): Record<string, string> {
  const files: Record<string, string> = {};
  for (const [relativePath, content] of Object.entries(crossbenchPyFiles)) {
    const match = relativePath.match(
        /^(?:\.\.[/\\])*((?:crossbench|config|tools|third_party)[/\\].*)$/);
    if (match) {
      files['/' + match[1].replace(/\\/g, '/')] = content;
    }
  }
  return files;
}

const CB_BINARIES = new Set(['./cb.py', 'cb.py', 'cb', 'crossbench']);
const PYTHON_RUNNERS = new Set(['python', 'python3', 'vpython3']);

export function parseCommandLine(cmdStr: string): string[] {
  const trimmed = cmdStr.trim();
  if (!trimmed) {
    return [];
  }
  const tokens: string[] = [];
  let current = '';
  let inDoubleQuote = false;
  let inSingleQuote = false;
  let escape = false;

  for (let i = 0; i < trimmed.length; i++) {
    const char = trimmed[i];
    if (escape) {
      current += char;
      escape = false;
    } else if (char === '\\') {
      escape = true;
    } else if (char === '"' && !inSingleQuote) {
      inDoubleQuote = !inDoubleQuote;
    } else if (char === '\'' && !inDoubleQuote) {
      inSingleQuote = !inSingleQuote;
    } else if (/\s/.test(char) && !inDoubleQuote && !inSingleQuote) {
      if (current.length > 0) {
        tokens.push(current);
        current = '';
      }
    } else {
      current += char;
    }
  }
  if (current.length > 0) {
    tokens.push(current);
  }

  if (tokens.length > 0) {
    if (CB_BINARIES.has(tokens[0])) {
      tokens.shift();
    } else if (
        PYTHON_RUNNERS.has(tokens[0]) && tokens.length > 1 &&
        (tokens[1] === 'cb.py' || tokens[1] === './cb.py')) {
      tokens.splice(0, 2);
    }
  }

  return tokens;
}

export interface DeviceBrowserInfo {
  packageName: string;
  browserArg: string;
  displayName: string;
  versionName: string;
  label: string;
}

export const KNOWN_ANDROID_BROWSERS: ReadonlyArray<
    {packageName: string; browserArg: string; displayName: string;}> =
    [
      {
        packageName: 'com.android.chrome',
        browserArg: 'cdp:chrome',
        displayName: 'Chrome',
      },
      {
        packageName: 'com.chrome.beta',
        browserArg: 'cdp:chrome-beta',
        displayName: 'Chrome Beta',
      },
      {
        packageName: 'com.chrome.dev',
        browserArg: 'cdp:chrome-dev',
        displayName: 'Chrome Dev',
      },
      {
        packageName: 'com.chrome.canary',
        browserArg: 'cdp:chrome-canary',
        displayName: 'Chrome Canary',
      },
      {
        packageName: 'com.google.android.apps.chrome',
        browserArg: 'cdp:chrome-app',
        displayName: 'Chrome App',
      },
      {
        packageName: 'org.chromium.chrome',
        browserArg: 'cdp:chromium',
        displayName: 'Chromium',
      },
    ];

function decodeShellOutput(raw: Uint8Array|string): string {
  return typeof raw === 'string' ? raw : new TextDecoder().decode(raw);
}

export async function fetchDeviceBrowsers(webAdbBridge: WebAdbBridge):
    Promise<DeviceBrowserInfo[]> {
  if (!webAdbBridge.isConnected) {
    return [];
  }
  const packagesRaw =
      decodeShellOutput(await webAdbBridge.shell('cmd package list packages'));
  const installedPackages = new Set<string>();
  for (const line of packagesRaw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (trimmed.startsWith('package:')) {
      installedPackages.add(trimmed.slice('package:'.length).trim());
    }
  }

  const browsers: DeviceBrowserInfo[] = [];
  for (const candidate of KNOWN_ANDROID_BROWSERS) {
    if (!installedPackages.has(candidate.packageName)) {
      continue;
    }
    let versionName = '';
    try {
      const dumpsysOut = decodeShellOutput(
          await webAdbBridge.shell(`dumpsys package ${candidate.packageName}`));
      const match = dumpsysOut.match(/versionName=([^\s\r\n]+)/);
      if (match && match[1]) {
        versionName = match[1].trim();
      }
    } catch {
      // Fall back to empty versionName if dumpsys fails
    }
    const label = versionName ? `${candidate.displayName} (${versionName})` :
                                candidate.displayName;
    browsers.push({
      ...candidate,
      versionName,
      label,
    });
  }
  return browsers;
}

export async function refreshDeviceBrowsers(webAdbBridge: WebAdbBridge):
    Promise<DeviceBrowserInfo[]> {
  const select =
      document.getElementById('simple-browser-select') as HTMLSelectElement |
      null;
  if (!webAdbBridge.isConnected) {
    if (select) {
      select.innerHTML =
          '<option value="">Connect a device to load browsers...</option>';
      select.disabled = true;
    }
    return [];
  }

  if (select) {
    select.innerHTML =
        '<option value="">Detecting installed browsers...</option>';
    select.disabled = true;
  }

  try {
    const browsers = await fetchDeviceBrowsers(webAdbBridge);
    if (select) {
      select.innerHTML = '';
      if (browsers.length === 0) {
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = 'No supported browsers found on device';
        select.appendChild(opt);
        select.disabled = true;
      } else {
        for (const b of browsers) {
          const opt = document.createElement('option');
          opt.value = b.browserArg;
          opt.textContent = b.label;
          select.appendChild(opt);
        }
        select.disabled = false;
        syncSimpleChoicesToDevInputs();
      }
    }
    return browsers;
  } catch (err: any) {
    log(`Failed to query installed browsers: ${err?.message || err}`, 'warn');
    if (select) {
      select.innerHTML =
          '<option value="">Failed to query browsers on device</option>';
      select.disabled = true;
    }
    return [];
  }
}

export function extractTotalRepetitions(benchmarkArgs: string[]): number {
  for (let i = 0; i < benchmarkArgs.length; i++) {
    const arg = benchmarkArgs[i];
    if ((arg === '--repeat' || arg === '-r') && i + 1 < benchmarkArgs.length) {
      const parsed = Number.parseInt(benchmarkArgs[i + 1], 10);
      if (Number.isFinite(parsed) && parsed > 0) {
        return parsed;
      }
    } else if (arg.startsWith('--repeat=')) {
      const parsed = Number.parseInt(arg.slice('--repeat='.length), 10);
      if (Number.isFinite(parsed) && parsed > 0) {
        return parsed;
      }
    }
  }
  return 50;
}

let activeCdpClient: CdpClient|null = null;
let workerClient: PyodideWorkerClient|null = null;
let isWorkerInitialized = false;
let latestResultsZip: Uint8Array|null = null;
let interruptAttempt = 0;
let activeTotalRepetitions = 50;
let completedRepetitions = 0;

export function handleBenchmarkLogProgress(pythonMessage: string): void {
  const runMatch = pythonMessage.match(/\bRUN\s+(\d+)\/(\d+)\b/);
  if (runMatch) {
    const currentRun = Number.parseInt(runMatch[1], 10);
    const totalRuns = Number.parseInt(runMatch[2], 10);
    if (Number.isFinite(currentRun) && Number.isFinite(totalRuns) &&
        totalRuns > 0) {
      activeTotalRepetitions = totalRuns;
      completedRepetitions = Math.max(0, currentRun - 1);
      updateBenchmarkProgressBar(
          completedRepetitions, activeTotalRepetitions,
          `Running repetition ${currentRun} of ${totalRuns}...`);
      return;
    }
  }
  if (pythonMessage.includes('RUNS COMPLETED') ||
      pythonMessage.includes('MERGING PROBE DATA')) {
    completedRepetitions = activeTotalRepetitions;
    updateBenchmarkProgressBar(
        completedRepetitions, activeTotalRepetitions,
        'Analyzing traces & computing scores...');
  }
}

export function getOrCreateWorkerClient(webAdbBridge: WebAdbBridge):
    PyodideWorkerClient {
  if (workerClient) {
    return workerClient;
  }
  const worker = new Worker(
      new URL('./pyodide_worker.ts', import.meta.url), {type: 'module'});
  workerClient = new PyodideWorkerClient(
      worker,
      async (method, args) => {
        if (method === 'shell') {
          const cmd = args[0] as string;
          if (!webAdbBridge.isConnected) {
            throw new Error(
                `ADB device is not connected. Cannot execute shell command: ${
                    cmd}`);
          }
          return await webAdbBridge.shell(cmd);
        }
        if (method === 'startDevTools') {
          if (!webAdbBridge.isConnected) {
            throw new Error(
                'ADB device is not connected. Please connect your Android ' +
                'device first.');
          }
          if (activeCdpClient) {
            try {
              await activeCdpClient.disconnect();
            } catch (err) {
              console.warn('Failed to disconnect active CDP client:', err);
            }
            activeCdpClient = null;
          }
          const maxAttempts = 20;  // 20 attempts * 500ms = 10s timeout
          let lastError: any = null;

          for (let attempt = 1; attempt <= maxAttempts; attempt++) {
            try {
              const socketName = await webAdbBridge.discoverDevToolsSocket();
              const versionInfo =
                  await webAdbBridge.getDevToolsVersion(socketName);
              const upgradePath = getBrowserUpgradePath(versionInfo);
              const socketStream =
                  await webAdbBridge.createDevToolsSocket(socketName);
              const client = new CdpClient(socketStream);
              await client.connect(socketStream, upgradePath);
              await client.initBrowserSession();
              activeCdpClient = client;
              return 'OK';
            } catch (err: any) {
              lastError = err;
              if (activeCdpClient) {
                try {
                  await activeCdpClient.disconnect();
                } catch (discErr) {
                  console.warn(
                      'Failed to disconnect CDP client during retry:', discErr);
                }
                activeCdpClient = null;
              }
              await new Promise((resolve) => setTimeout(resolve, 500));
            }
          }
          const errorMsg =
              `Failed to connect to Chrome DevTools after ${maxAttempts} ` +
              `attempts: ${lastError?.message || lastError}`;
          log(errorMsg, 'error');
          throw new Error(errorMsg);
        }
        if (method === 'stopDevTools') {
          if (activeCdpClient) {
            try {
              await activeCdpClient.disconnect();
            } catch (err) {
              console.warn('Error disconnecting active CDP client:', err);
            }
            activeCdpClient = null;
          }
          return 'OK';
        }
        if (method === 'switchTab') {
          const [url] = args;
          if (!activeCdpClient || !activeCdpClient.isConnected) {
            const errMsg = 'DevTools is not connected. Cannot switch tab.';
            log(`[CDP Error] ${errMsg}`, 'error');
            throw new Error(errMsg);
          }
          try {
            const sessionId =
                await activeCdpClient.switchTab(url || 'about:blank');
            return sessionId;
          } catch (err: any) {
            const errMsg = err?.message || String(err);
            log(`[CDP SwitchTab Error] ${errMsg}`, 'error');
            throw err;
          }
        }
        if (method === 'sendCdpCommand') {
          const [cdpMethod, paramsJson] = args;
          if (!activeCdpClient || !activeCdpClient.isConnected) {
            const errMsg =
                `DevTools is not connected. Cannot send CDP command '${
                    cdpMethod}'`;
            log(`[CDP Error] ${errMsg}`, 'error');
            throw new Error(errMsg);
          }
          const params = paramsJson ? JSON.parse(paramsJson) : {};
          try {
            const res = await activeCdpClient.send(cdpMethod, params);
            return JSON.stringify(res ?? {});
          } catch (err: any) {
            const errMsg = err?.message || String(err);
            log(`[CDP Command Error] ${cdpMethod}: ${errMsg}`, 'error');
            return JSON.stringify({error: errMsg});
          }
        }
        if (method === 'push') {
          const [, dest, fileBytes] = args;
          if (!webAdbBridge.isConnected) {
            throw new Error(
                `ADB device is not connected. Cannot push to ${dest}`);
          }
          if (!(fileBytes instanceof Uint8Array)) {
            throw new TypeError(`push expected Uint8Array for ${dest}, got: ${
                typeof fileBytes}`);
          }
          await webAdbBridge.push(dest, fileBytes);
          return 'OK';
        }
        if (method === 'pull') {
          const [src] = args;
          if (!webAdbBridge.isConnected) {
            throw new Error(`ADB device is not connected. Cannot pull ${src}`);
          }
          return await webAdbBridge.pull(src);
        }
        if (method === 'gcsGetMetadata') {
          const [url] = args;
          const targetUrl = url || getTargetArchiveUrl();
          const cached = await getCachedGcsArchive(targetUrl);
          if (cached) {
            return JSON.stringify({
              name: cached.filename,
              md5Hash: cached.md5Hash,
              size: cached.size,
            });
          }
          const token = getStoredAccessToken();
          const meta = await fetchGcsMetadata(targetUrl, token);
          return JSON.stringify(meta);
        }
        if (method === 'gcsDownloadFile') {
          const [url] = args;
          const targetUrl = url || getTargetArchiveUrl();
          let cached = await getCachedGcsArchive(targetUrl);
          if (!cached) {
            const token = getStoredAccessToken();
            if (!token) {
              throw new Error(`Cannot download ${
                  targetUrl}: No GCP access token provided.`);
            }
            cached = await downloadGcsArchive(targetUrl, token);
          }
          return cached.data;
        }
        if (method === 'spawnProcess') {
          const [cmd] = args;
          if (!webAdbBridge.isConnected) {
            throw new Error(
                `ADB device is not connected. Cannot spawn process: ${cmd}`);
          }
          const procId = await webAdbBridge.spawnProcess(cmd);
          return String(procId);
        }
        if (method === 'readProcessLog') {
          const [procId, offset] = args;
          const status =
              webAdbBridge.readProcessLog(Number(procId), Number(offset));
          return JSON.stringify(status);
        }
        if (method === 'killProcess') {
          const [procId] = args;
          await webAdbBridge.killProcess(Number(procId));
          return 'OK';
        }
        return '';
      },
      (pythonMessage, level) => {
        handleBenchmarkLogProgress(pythonMessage);
        const formatted = pythonMessage.startsWith('[Python]') ?
            pythonMessage :
            `[Python] ${pythonMessage}`;
        log(formatted, level || 'info');
      });
  return workerClient;
}

export const TARGET_ARCHIVE_STORAGE_KEY = 'crossbench_target_archive_url';
export const BENCHMARK_CMD_STORAGE_KEY = 'crossbench_benchmark_cmd';

/**
 * Initializes event listeners for Benchmark Execution, stopping, and results
 * zip download.
 */
export function setupBenchmarkEventListeners(webAdbBridge: WebAdbBridge): void {
  const btnRunBenchmark =
      document.getElementById('btn-run-benchmark') as HTMLButtonElement | null;
  const btnStopBenchmark =
      document.getElementById('btn-stop-benchmark') as HTMLButtonElement | null;
  const btnDownloadResults =
      document.getElementById('btn-download-results') as HTMLButtonElement |
      null;
  const targetArchiveInput =
      document.getElementById('target-archive-input') as HTMLInputElement |
      null;
  const benchmarkCmdInput =
      document.getElementById('benchmark-cmd') as HTMLInputElement | null;
  const simpleVariantSelect =
      document.getElementById('simple-benchmark-variant') as HTMLSelectElement |
      null;
  const simpleBrowserSelect =
      document.getElementById('simple-browser-select') as HTMLSelectElement |
      null;
  const simpleRepetitionsSelect =
      document.getElementById('simple-repetitions-select') as
          HTMLSelectElement |
      null;
  const statusBadge =
      document.getElementById('connection-status') as HTMLElement | null;
  const gcsTokenInput =
      document.getElementById('gcs-token-input') as HTMLInputElement | null;
  const downloadProgressContainer =
      document.getElementById('download-progress-container') as HTMLElement |
      null;

  if (targetArchiveInput) {
    const savedArchive = localStorage.getItem(TARGET_ARCHIVE_STORAGE_KEY);
    if (savedArchive) {
      targetArchiveInput.value = savedArchive;
    }
  }
  if (benchmarkCmdInput) {
    const savedCmd = localStorage.getItem(BENCHMARK_CMD_STORAGE_KEY);
    if (savedCmd) {
      benchmarkCmdInput.value = savedCmd;
    }
  }

  if (simpleVariantSelect) {
    simpleVariantSelect.addEventListener('change', () => {
      syncSimpleChoicesToDevInputs();
    });
  }
  if (simpleBrowserSelect) {
    simpleBrowserSelect.addEventListener('change', () => {
      syncSimpleChoicesToDevInputs();
    });
  }
  if (simpleRepetitionsSelect) {
    simpleRepetitionsSelect.addEventListener('change', () => {
      syncSimpleChoicesToDevInputs();
    });
  }

  if (btnRunBenchmark) {
    btnRunBenchmark.addEventListener('click', async () => {
      if (getRunnerMode() === 'simple') {
        syncSimpleChoicesToDevInputs();
      }
      if (targetArchiveInput && targetArchiveInput.value.trim()) {
        localStorage.setItem(
            TARGET_ARCHIVE_STORAGE_KEY, targetArchiveInput.value.trim());
      }
      if (benchmarkCmdInput && benchmarkCmdInput.value.trim()) {
        localStorage.setItem(
            BENCHMARK_CMD_STORAGE_KEY, benchmarkCmdInput.value.trim());
      }
      if (!webAdbBridge.isConnected) {
        log('Cannot run benchmark: No ADB device connected.', 'error');
        return;
      }

      let benchmarkArgs: string[] = [];
      if (getRunnerMode() === 'simple') {
        const variant = simpleVariantSelect?.value || 'loadline2-phone';
        const browser = simpleBrowserSelect?.value || '';
        const repetitions = simpleRepetitionsSelect?.value || '50';
        if (!browser) {
          log('Cannot run benchmark: No browser selected on the device.',
              'error');
          return;
        }
        benchmarkArgs =
            [variant, '--browser', browser, '--repeat', repetitions];
      } else {
        const rawCmd = benchmarkCmdInput ? benchmarkCmdInput.value.trim() : '';
        benchmarkArgs = parseCommandLine(rawCmd);
        if (benchmarkArgs.length === 0) {
          log('Cannot run benchmark: No benchmark arguments provided.',
              'error');
          return;
        }
      }

      activeTotalRepetitions = extractTotalRepetitions(benchmarkArgs);
      completedRepetitions = 0;
      clearBenchmarkScoreTable();
      updateBenchmarkProgressBar(
          0, activeTotalRepetitions, 'Preparing benchmark environment...');

      btnRunBenchmark.style.display = 'inline-block';
      btnRunBenchmark.disabled = true;
      btnRunBenchmark.innerText = '⏳ Running...';
      setBenchmarkRunning(true);
      if (btnStopBenchmark) {
        btnStopBenchmark.style.display = 'inline-block';
        btnStopBenchmark.disabled = false;
        btnStopBenchmark.innerText = '⏹️ Interrupt Execution';
      }
      if (btnDownloadResults)
        btnDownloadResults.style.display = 'none';
      if (benchmarkCmdInput)
        benchmarkCmdInput.disabled = true;
      if (simpleVariantSelect)
        simpleVariantSelect.disabled = true;
      if (simpleBrowserSelect)
        simpleBrowserSelect.disabled = true;
      if (simpleRepetitionsSelect)
        simpleRepetitionsSelect.disabled = true;
      if (statusBadge) {
        statusBadge.innerText = 'Benchmark in Progress...';
        statusBadge.className = 'status-badge tracing';
      }

      let client: PyodideWorkerClient|null = null;
      try {
        const useWorkerSab = typeof Worker !== 'undefined' &&
            typeof SharedArrayBuffer !== 'undefined' &&
            typeof Atomics !== 'undefined';
        if (!useWorkerSab) {
          const errorMsg =
              'Crossbench requires Web Worker + SharedArrayBuffer for ' +
              'synchronous ADB execution. Cross-Origin-Opener-Policy (COOP) ' +
              'and Cross-Origin-Embedder-Policy (COEP) headers must be set.';
          log(errorMsg, 'error');
          throw new Error(errorMsg);
        }

        // Check WPR Archive cache before launching benchmark
        const targetUrl = getTargetArchiveUrl();
        let cachedArchive = await getCachedGcsArchive(targetUrl);
        if (!cachedArchive) {
          const token = (gcsTokenInput?.value || getStoredAccessToken()).trim();
          if (token) {
            log(`[GCS] Target archive not in cache. Downloading ${
                    targetUrl}...`,
                'info');
            if (downloadProgressContainer) {
              downloadProgressContainer.style.display = 'block';
            }
            try {
              cachedArchive = await downloadGcsArchive(
                  targetUrl, token, (loaded, total) => {
                    updateDownloadProgressBar(
                        loaded, total, 'Auto-downloading');
                  });
              await updateGcsUI();
              log(`[GCS] Downloaded ${cachedArchive.filename} successfully.`,
                  'success');
            } catch (dlErr: any) {
              log(`[GCS Error] Auto-download failed: ${
                      dlErr?.message || dlErr}`,
                  'error');
              throw new Error(
                  'Failed to download required benchmark archive: ' +
                  (dlErr?.message || dlErr));
            } finally {
              if (downloadProgressContainer) {
                downloadProgressContainer.style.display = 'none';
              }
            }
          } else {
            log('WPR Archive is not cached and no GCP token was provided. ' +
                    `If the benchmark requires ${targetUrl}, please paste a ` +
                    'token in Section 2.',
                'warn');
          }
        }

        client = getOrCreateWorkerClient(webAdbBridge);
        client.clearInterrupt();
        if (!isWorkerInitialized) {
          log('Initializing Pyodide WebAssembly runtime...');
          await client.sendRequest('INIT', {
            interruptBuffer: client.getInterruptBuffer(),
            stopFlag: client.getStopFlag(),
          });
          log('Pyodide runtime initialized.', 'success');

          log('Mounting Crossbench Python package into Pyodide virtual ' +
              'filesystem (MEMFS)...');
          const pyFiles = getCrossbenchVirtualFiles();
          await client.sendRequest('MOUNT_FILES', {files: pyFiles});
          const count = Object.keys(pyFiles).length;
          log(`Mounted ${count} Crossbench Python modules into MEMFS.`,
              'success');
          isWorkerInitialized = true;
        } else {
          await client.sendRequest('SET_INTERRUPT_BUFFER', {
            interruptBuffer: client.getInterruptBuffer(),
            stopFlag: client.getStopFlag(),
          });
        }

        // Mount cached WPR archive into Pyodide's /cache/wpr/ directory
        if (cachedArchive && cachedArchive.data) {
          log('Mounting cached WPR archive into Pyodide ' +
              `/cache/wpr/${cachedArchive.filename}...`);
          await client.mountBinaryFile(
              `/cache/wpr/${cachedArchive.filename}`, cachedArchive.data);
          // Also mount with canonical name
          const {objectName} = parseGcsUrl(targetUrl);
          const baseName = objectName.split('/').pop();
          if (baseName && baseName !== cachedArchive.filename) {
            await client.mountBinaryFile(
                `/cache/wpr/${baseName}`, cachedArchive.data);
          }
          const mb = (cachedArchive.size / (1024 * 1024)).toFixed(1);
          log(`Mounted WPR archive (${mb} MB) into MEMFS.`, 'success');
        }

        // Mount prebuilt WPR binary for Android
        log('Fetching and mounting prebuilt WPR binary for Android ' +
            '(/cache/webpagereplay/android/arm64/wpr)...');
        const wprRes = await fetch('/bin/android/arm64/wpr');
        if (!wprRes.ok) {
          throw new Error(
              'Failed to fetch required WPR binary at ' +
              '/bin/android/arm64/wpr: ' + wprRes.status);
        }
        const wprBuf = await wprRes.arrayBuffer();
        const wprBytes = new Uint8Array(wprBuf);
        await client.mountBinaryFile(
            '/cache/webpagereplay/android/arm64/wpr', wprBytes);
        await client.mountBinaryFile(
            '/third_party/webpagereplay/wpr', wprBytes);
        const wprKb = Math.round(wprBytes.length / 1024);
        log(`Mounted prebuilt WPR binary (${wprKb} KB) into MEMFS.`, 'success');

        log(`Executing Crossbench CLI command: cb.py ${
            benchmarkArgs.join(' ')}`);
        updateBenchmarkProgressBar(
            0, activeTotalRepetitions,
            `Starting benchmark (${activeTotalRepetitions} repetitions)...`);
        const result = await client.sendRequest('RUN_BENCHMARK', {
          benchmarkArgs,
        });
        if (result === 'INTERRUPTED') {
          log('Benchmark execution was stopped / interrupted by user.', 'warn');
          updateBenchmarkProgressBar(
              completedRepetitions, activeTotalRepetitions,
              'Benchmark execution interrupted.');
        } else {
          log('Benchmark execution completed successfully!', 'success');
          completedRepetitions = activeTotalRepetitions;
          updateBenchmarkProgressBar(
              activeTotalRepetitions, activeTotalRepetitions,
              'Benchmark completed!');
        }
      } catch (err: any) {
        log(`Benchmark execution error: ${err?.message || err}`, 'error');
        updateBenchmarkProgressBar(
            completedRepetitions, activeTotalRepetitions,
            `Benchmark error: ${err?.message || err}`);
      } finally {
        if (client) {
          client.clearInterrupt();
        }
        if (isWorkerInitialized && client) {
          try {
            const scoreCsv = await client.getBenchmarkScoreCsv();
            if (scoreCsv && scoreCsv.trim()) {
              renderBenchmarkScoreTable(scoreCsv);
            }
          } catch (csvErr: any) {
            log(`Failed to read benchmark_score.csv: ${
                    csvErr?.message || csvErr}`,
                'warn');
          }
          try {
            log('Packaging benchmark results into zip archive...');
            const zipBytes = await client.exportResultsZip();
            if (zipBytes && zipBytes.length > 0) {
              latestResultsZip = zipBytes;
              if (btnDownloadResults) {
                btnDownloadResults.style.display = 'inline-block';
                btnDownloadResults.disabled = false;
              }
              const zipKb = Math.round(zipBytes.length / 1024);
              log(`Results archive ready (${
                      zipKb} KB). Click "Download Results ` +
                      '(.zip)" to save.',
                  'success');
            } else {
              log('No results files found to package.', 'info');
            }
          } catch (zipErr: any) {
            log(`Failed to package results zip: ${zipErr?.message || zipErr}`,
                'warn');
          }
        }
        setBenchmarkRunning(false);
        interruptAttempt = 0;
        if (btnStopBenchmark) {
          btnStopBenchmark.style.display = 'none';
          btnStopBenchmark.disabled = true;
          btnStopBenchmark.innerText = '⏹️ Interrupt Execution';
        }
        btnRunBenchmark.style.display = 'inline-block';
        btnRunBenchmark.disabled = false;
        btnRunBenchmark.innerText = 'Clear Data and Run Benchmark';
        if (benchmarkCmdInput)
          benchmarkCmdInput.disabled = false;
        if (simpleVariantSelect)
          simpleVariantSelect.disabled = false;
        updateUI(true, webAdbBridge.serial);
      }
    });
  }

  if (btnStopBenchmark) {
    btnStopBenchmark.addEventListener('click', () => {
      interruptAttempt++;
      if (interruptAttempt === 1) {
        log('Stopping benchmark execution (sending SIGINT)...', 'warn');
      } else {
        log('Re-sending interrupt signal (SIGINT, attempt ' +
                `#${interruptAttempt})...`,
            'warn');
      }
      if (btnRunBenchmark)
        btnRunBenchmark.innerText = '⏹️ Stopping...';
      if (statusBadge) {
        statusBadge.innerText = 'Stopping Benchmark...';
        statusBadge.className = 'status-badge warning';
      }
      if (workerClient) {
        workerClient.interrupt();
      }
    });
  }

  if (benchmarkCmdInput) {
    benchmarkCmdInput.addEventListener('keydown', (event: KeyboardEvent) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        if (btnRunBenchmark && !btnRunBenchmark.disabled) {
          btnRunBenchmark.click();
        }
      }
    });
  }

  if (btnDownloadResults) {
    btnDownloadResults.addEventListener('click', () => {
      if (!latestResultsZip)
        return;
      const blob =
          new Blob([latestResultsZip as BlobPart], {type: 'application/zip'});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
      a.download = `crossbench_results_${timestamp}.zip`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    });
  }
}
