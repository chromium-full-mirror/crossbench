// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

/**
 * Authentication and Google Cloud Storage WPR archive UI controller.
 */

import {type CachedGcsArchive, clearStoredAccessToken, deleteCachedGcsArchive, downloadGcsArchive, getCachedGcsArchive, getManualAccessToken, getStoredAccessToken, setStoredAccessToken, TARGET_GCS_ARCHIVE_URL,} from './gcs_cache';
import {getStoredAuthSession, gisAuthManager, isSessionExpired,} from './gis_auth';
import {getRunnerMode, log as uiLog, updateDownloadProgressBar} from './ui_state';

const loadlineNetworkConfigs =
    import.meta.glob(
        '../../../config/benchmark/loadline2/network_config_*.hjson', {
          query: '?raw',
          import: 'default',
          eager: true,
        }) as Record<string, string>;

export type LogLevel = 'info'|'warn'|'error'|'success';
export type Logger = (message: string, level?: LogLevel) => void;

export const SIMPLE_VARIANT_STORAGE_KEY = 'crossbench_simple_variant';

let authLogger: Logger|null = null;

export function setAuthLogger(fn: Logger): void {
  authLogger = fn;
}

export function log(message: string, level: LogLevel = 'info'): void {
  if (authLogger) {
    authLogger(message, level);
    return;
  }
  if (typeof document !== 'undefined' &&
      document.getElementById('log-output')) {
    uiLog(message, level);
    return;
  }
  if (level === 'error') {
    console.error(message);
  } else if (level === 'warn') {
    console.warn(message);
  } else {
    console.log(message);
  }
}

export function setDownloadError(errorMessage: string|null): void {
  if (typeof document === 'undefined') {
    return;
  }
  const errorIds = ['simple-download-error', 'download-error'];
  for (const id of errorIds) {
    const el = document.getElementById(id) as HTMLElement | null;
    if (!el) {
      continue;
    }
    if (errorMessage) {
      el.innerText = errorMessage;
      el.style.display = 'block';
    } else {
      el.innerText = '';
      el.style.display = 'none';
    }
  }
}

export function getArchiveUrlForVariant(variant: string): string {
  const suffix = variant === 'loadline2-tablet' ?
      'network_config_tablet.hjson' :
      'network_config_phone.hjson';
  for (const [path, content] of Object.entries(loadlineNetworkConfigs)) {
    if (path.endsWith(suffix)) {
      const match = content.match(/"url"\s*:\s*"(gs:\/\/[^"]+)"/);
      if (match && match[1]) {
        return match[1].trim();
      }
    }
  }
  return TARGET_GCS_ARCHIVE_URL;
}

export function syncSimpleChoicesToDevInputs(): void {
  if (typeof document === 'undefined') {
    return;
  }
  const simpleVariantSelect = document.getElementById(
                                  'simple-benchmark-variant',
                                  ) as HTMLSelectElement |
      null;
  const simpleBrowserSelect = document.getElementById(
                                  'simple-browser-select',
                                  ) as HTMLSelectElement |
      null;
  const simpleRepetitionsSelect = document.getElementById(
                                      'simple-repetitions-select',
                                      ) as HTMLSelectElement |
      null;
  if (!simpleVariantSelect && !simpleBrowserSelect &&
      !simpleRepetitionsSelect) {
    return;
  }

  const variant = simpleVariantSelect?.value || 'loadline2-phone';
  const browser = simpleBrowserSelect?.value || 'cdp:chrome';
  const repetitions = simpleRepetitionsSelect?.value || '50';

  const targetArchiveInput = document.getElementById(
                                 'target-archive-input',
                                 ) as HTMLInputElement |
      null;
  if (targetArchiveInput && simpleVariantSelect) {
    const archiveUrl = getArchiveUrlForVariant(variant);
    targetArchiveInput.value = archiveUrl;
    try {
      localStorage.setItem('crossbench_target_archive_url', archiveUrl);
    } catch {
      // Ignore storage errors
    }
  }

  const benchmarkCmdInput = document.getElementById(
                                'benchmark-cmd',
                                ) as HTMLInputElement |
      null;
  if (benchmarkCmdInput) {
    const cmd = `${variant} --browser ${browser} --repeat ${repetitions}`;
    benchmarkCmdInput.value = cmd;
    try {
      localStorage.setItem('crossbench_benchmark_cmd', cmd);
    } catch {
      // Ignore storage errors
    }
  }
}

export function getTargetArchiveUrl(): string {
  if (getRunnerMode() === 'simple') {
    const variantSelect = document.getElementById(
                              'simple-benchmark-variant',
                              ) as HTMLSelectElement |
        null;
    if (variantSelect && variantSelect.value) {
      return getArchiveUrlForVariant(variantSelect.value);
    }
  }
  const input = document.getElementById(
                    'target-archive-input',
                    ) as HTMLInputElement |
      null;
  if (input && input.value && input.value.trim()) {
    return input.value.trim();
  }
  return TARGET_GCS_ARCHIVE_URL;
}

export async function updateGcsUI(): Promise<CachedGcsArchive|null> {
  const manualToken = getManualAccessToken();
  const tokenInput = document.getElementById(
                         'gcs-token-input',
                         ) as HTMLInputElement |
      null;
  if (tokenInput && (!tokenInput.value || tokenInput.value !== manualToken)) {
    tokenInput.value = manualToken;
  }

  const authBadge = document.getElementById(
                        'auth-status',
                        ) as HTMLElement |
      null;
  const signInBtn = document.getElementById(
                        'btn-gis-signin',
                        ) as HTMLButtonElement |
      null;
  const signOutBtn = document.getElementById(
                         'btn-gis-signout',
                         ) as HTMLButtonElement |
      null;
  const refreshBtn = document.getElementById(
                         'btn-gis-refresh',
                         ) as HTMLButtonElement |
      null;
  const clearTokenBtn = document.getElementById(
                            'btn-clear-token',
                            ) as HTMLButtonElement |
      null;

  const authStatus = gisAuthManager.getAuthStatus(manualToken);

  if (authBadge) {
    authBadge.innerText = authStatus.displayText;
    if (authStatus.type === 'gis') {
      authBadge.className = 'status-badge connected';
    } else if (authStatus.type === 'expired') {
      authBadge.className = 'status-badge warning';
    } else if (authStatus.type === 'manual') {
      authBadge.className = 'status-badge connected';
    } else {
      authBadge.className = 'status-badge';
    }
  }

  if (signInBtn && signOutBtn && refreshBtn) {
    if (authStatus.type === 'gis') {
      signInBtn.style.display = 'none';
      signOutBtn.style.display = 'inline-block';
      refreshBtn.style.display = 'none';
    } else if (authStatus.type === 'expired') {
      signInBtn.style.display = 'none';
      signOutBtn.style.display = 'inline-block';
      refreshBtn.style.display = 'inline-block';
    } else {
      signInBtn.style.display = 'inline-flex';
      signOutBtn.style.display = 'none';
      refreshBtn.style.display = 'none';
    }
  }

  if (clearTokenBtn) {
    clearTokenBtn.style.display = manualToken ? 'inline-block' : 'none';
  }

  const targetUrl = getTargetArchiveUrl();
  const cached = await getCachedGcsArchive(targetUrl);
  const isCached = Boolean(cached && cached.data && cached.data.length > 0);

  const simpleArchiveReady = document.getElementById(
                                 'simple-archive-ready',
                                 ) as HTMLElement |
      null;
  const simpleArchiveMissing = document.getElementById(
                                   'simple-archive-missing',
                                   ) as HTMLElement |
      null;
  if (simpleArchiveReady) {
    simpleArchiveReady.style.display = isCached ? 'block' : 'none';
  }
  if (simpleArchiveMissing) {
    simpleArchiveMissing.style.display = isCached ? 'none' : 'block';
  }

  const cacheBadge = document.getElementById(
                         'cache-status',
                         ) as HTMLElement |
      null;
  const downloadBtn = document.getElementById(
                          'btn-download-archive',
                          ) as HTMLButtonElement |
      null;
  const clearCacheBtn = document.getElementById(
                            'btn-clear-cache',
                            ) as HTMLButtonElement |
      null;

  if (cacheBadge) {
    if (isCached && cached) {
      const mb = (cached.size / (1024 * 1024)).toFixed(1);
      cacheBadge.innerText = `Cached (${mb} MB)`;
      cacheBadge.className = 'status-badge connected';
      if (downloadBtn) {
        downloadBtn.innerText = 'Re-download Archive';
      }
      if (clearCacheBtn) {
        clearCacheBtn.style.display = 'inline-block';
      }
    } else {
      cacheBadge.innerText = 'Not Cached';
      cacheBadge.className = 'status-badge';
      if (downloadBtn) {
        downloadBtn.innerText = 'Download & Cache Archive';
      }
      if (clearCacheBtn) {
        clearCacheBtn.style.display = 'none';
      }
    }
  }
  return cached;
}

let gcsUpdateInterval: ReturnType<typeof setInterval>|null = null;

export function stopGcsUpdateInterval(): void {
  if (gcsUpdateInterval) {
    clearInterval(gcsUpdateInterval);
    gcsUpdateInterval = null;
  }
}

export function startGcsUpdateInterval(intervalMs = 30000): void {
  stopGcsUpdateInterval();
  gcsUpdateInterval = setInterval(() => {
    updateGcsUI();
  }, intervalMs);
}

/**
 * Initializes event listeners for GIS Auth and GCS archive management.
 */
export function setupAuthUIEventListeners(): void {
  if (typeof window !== 'undefined') {
    if (typeof BroadcastChannel !== 'undefined') {
      try {
        const globalAuthChannel = new BroadcastChannel('crossbench_gis_auth');
        globalAuthChannel.onmessage = (event) => {
          if (event.data?.type === 'GIS_AUTH_SUCCESS') {
            updateGcsUI();
          }
        };
      } catch (err) {
        console.warn(
            'Failed to initialize BroadcastChannel for GIS auth:',
            err,
        );
      }
    }
    window.addEventListener('storage', (e) => {
      if (e.key === 'crossbench_gis_auth_session' ||
          e.key === 'crossbench_gis_auth_broadcast' ||
          e.key === 'crossbench_gcs_access_token') {
        updateGcsUI();
      }
    });
  }

  const simpleVariantSelect = document.getElementById(
                                  'simple-benchmark-variant',
                                  ) as HTMLSelectElement |
      null;
  if (simpleVariantSelect) {
    try {
      const savedVariant = localStorage.getItem(SIMPLE_VARIANT_STORAGE_KEY);
      if (savedVariant === 'loadline2-phone' ||
          savedVariant === 'loadline2-tablet') {
        simpleVariantSelect.value = savedVariant;
      }
    } catch {
      // Ignore storage errors
    }
    simpleVariantSelect.addEventListener('change', () => {
      try {
        localStorage.setItem(
            SIMPLE_VARIANT_STORAGE_KEY, simpleVariantSelect.value);
      } catch {
        // Ignore storage errors
      }
      setDownloadError(null);
      syncSimpleChoicesToDevInputs();
      updateGcsUI();
    });
  }

  const targetArchiveInput = document.getElementById(
                                 'target-archive-input',
                                 ) as HTMLInputElement |
      null;
  if (targetArchiveInput) {
    targetArchiveInput.addEventListener('input', () => {
      setDownloadError(null);
      updateGcsUI();
    });
    targetArchiveInput.addEventListener('change', () => {
      setDownloadError(null);
      updateGcsUI();
    });
  }

  const btnGisSignIn = document.getElementById(
                           'btn-gis-signin',
                           ) as HTMLButtonElement |
      null;
  if (btnGisSignIn) {
    btnGisSignIn.addEventListener('click', async () => {
      btnGisSignIn.disabled = true;
      try {
        log(
            'Initiating Google Identity Services (GIS) OAuth 2.0 ' +
                'authorization...',
        );
        const session = await gisAuthManager.signIn();
        const emailLabel = session.userEmail ? ` (${session.userEmail})` : '';
        log(
            `Successfully authenticated via Google Identity Services${
                emailLabel}.`,
            'success',
        );
        await updateGcsUI();
      } catch (err: any) {
        log(`Google Sign-In failed: ${err?.message || err}`, 'error');
        await updateGcsUI();
      } finally {
        btnGisSignIn.disabled = false;
      }
    });
  }

  const btnGisSignOut = document.getElementById(
                            'btn-gis-signout',
                            ) as HTMLButtonElement |
      null;
  if (btnGisSignOut) {
    btnGisSignOut.addEventListener('click', async () => {
      btnGisSignOut.disabled = true;
      try {
        log('Signing out and revoking Google OAuth session...');
        await gisAuthManager.signOut();
        log('Signed out of Google session.', 'info');
        await updateGcsUI();
      } catch (err: any) {
        log(`Error during sign out: ${err?.message || err}`, 'warn');
      } finally {
        btnGisSignOut.disabled = false;
      }
    });
  }

  const btnGisRefresh = document.getElementById(
                            'btn-gis-refresh',
                            ) as HTMLButtonElement |
      null;
  if (btnGisRefresh) {
    btnGisRefresh.addEventListener('click', async () => {
      btnGisRefresh.disabled = true;
      try {
        log('Renewing Google OAuth 2.0 access token...');
        const session = await gisAuthManager.signIn({
          prompt: 'select_account',
        });
        const emailLabel = session.userEmail ? ` (${session.userEmail})` : '';
        log(`Google OAuth token renewed successfully${emailLabel}.`, 'success');
        await updateGcsUI();
      } catch (err: any) {
        log(`Token renewal failed: ${err?.message || err}`, 'error');
        await updateGcsUI();
      } finally {
        btnGisRefresh.disabled = false;
      }
    });
  }

  const btnSaveToken = document.getElementById(
                           'btn-save-token',
                           ) as HTMLButtonElement |
      null;
  const gcsTokenInput = document.getElementById(
                            'gcs-token-input',
                            ) as HTMLInputElement |
      null;
  if (btnSaveToken) {
    btnSaveToken.addEventListener('click', () => {
      const rawVal = gcsTokenInput ? gcsTokenInput.value.trim() : '';
      setStoredAccessToken(rawVal);
      updateGcsUI();
      if (rawVal) {
        log('Manual GCP access token saved successfully.', 'success');
      } else {
        log('Manual GCP access token cleared.', 'info');
      }
    });
  }

  const btnClearToken = document.getElementById(
                            'btn-clear-token',
                            ) as HTMLButtonElement |
      null;
  if (btnClearToken) {
    btnClearToken.addEventListener('click', () => {
      clearStoredAccessToken();
      const tokenInp = document.getElementById(
                           'gcs-token-input',
                           ) as HTMLInputElement |
          null;
      if (tokenInp) {
        tokenInp.value = '';
      }
      log('Manual GCP access token cleared.', 'info');
      updateGcsUI();
    });
  }

  const btnDownloadArchive = document.getElementById(
                                 'btn-download-archive',
                                 ) as HTMLButtonElement |
      null;
  const btnSimpleDownloadArchive = document.getElementById(
                                       'btn-simple-download-archive',
                                       ) as HTMLButtonElement |
      null;
  const downloadProgressContainer = document.getElementById(
                                        'download-progress-container',
                                        ) as HTMLElement |
      null;
  const downloadStatusText = document.getElementById(
                                 'download-status-text',
                                 ) as HTMLElement |
      null;

  const runArchiveDownload = async (
      targetUrl: string, token: string, triggerBtn: HTMLButtonElement) => {
    setDownloadError(null);
    triggerBtn.disabled = true;
    if (btnSaveToken) {
      btnSaveToken.disabled = true;
    }
    if (downloadProgressContainer) {
      downloadProgressContainer.style.display = 'block';
    }

    try {
      log(`[GCS] Fetching metadata for ${targetUrl}...`);
      if (downloadStatusText) {
        downloadStatusText.innerText = 'Connecting to GCS...';
      }

      const cached =
          await downloadGcsArchive(targetUrl, token, (loaded, total) => {
            updateDownloadProgressBar(loaded, total, 'Downloading');
          });

      const mb = (cached.size / (1024 * 1024)).toFixed(1);
      log(
          `[GCS] Successfully downloaded and cached ${cached.filename} (${
              mb} MB).`,
          'success',
      );
      setDownloadError(null);
      await updateGcsUI();
    } catch (err: any) {
      const errDetail = err?.message || String(err);
      log(`[GCS Error] Download failed: ${errDetail}`, 'error');
      let uiErrorMsg = `Download failed: ${errDetail}`;
      const session = getStoredAuthSession();
      if (session && isSessionExpired(session)) {
        const expiredNote =
            'Your OAuth token has expired. Click "Renew Session" or ' +
            '"Sign in with Google" to refresh.';
        log(expiredNote, 'warn');
        uiErrorMsg += ` ${expiredNote}`;
      }
      setDownloadError(uiErrorMsg);
    } finally {
      triggerBtn.disabled = false;
      if (btnSaveToken) {
        btnSaveToken.disabled = false;
      }
      setTimeout(() => {
        if (downloadProgressContainer) {
          downloadProgressContainer.style.display = 'none';
        }
      }, 3000);
    }
  };

  if (btnSimpleDownloadArchive) {
    btnSimpleDownloadArchive.addEventListener('click', async () => {
      setDownloadError(null);
      const targetUrl = getTargetArchiveUrl();
      let token = (gcsTokenInput?.value || getStoredAccessToken()).trim();
      if (!token) {
        btnSimpleDownloadArchive.disabled = true;
        try {
          log('Prompting for Google authorization to download archive...');
          const session = await gisAuthManager.signIn();
          token = session.accessToken;
          await updateGcsUI();
        } catch (authErr: any) {
          const errDetail =
              authErr?.message || 'Authorization cancelled or failed.';
          log(`Cannot download archive: ${errDetail}`, 'error');
          setDownloadError(`Download failed: ${errDetail}`);
          btnSimpleDownloadArchive.disabled = false;
          return;
        }
      }
      await runArchiveDownload(targetUrl, token, btnSimpleDownloadArchive);
    });
  }

  if (btnDownloadArchive) {
    btnDownloadArchive.addEventListener('click', async () => {
      setDownloadError(null);
      const targetUrl = getTargetArchiveUrl();
      let token = (gcsTokenInput?.value || getStoredAccessToken()).trim();
      if (!token) {
        log('No active GCP token. Prompting for Google Sign-In...');
        try {
          const session = await gisAuthManager.signIn();
          token = session.accessToken;
          await updateGcsUI();
        } catch (authErr: any) {
          const errDetail = authErr?.message || 'No GCP access token provided.';
          log(`Cannot download archive: ${errDetail}`, 'error');
          setDownloadError(`Download failed: ${errDetail}`);
          gcsTokenInput?.focus();
          return;
        }
      }
      await runArchiveDownload(targetUrl, token, btnDownloadArchive);
    });
  }

  const btnClearCache = document.getElementById(
                            'btn-clear-cache',
                            ) as HTMLButtonElement |
      null;
  if (btnClearCache) {
    btnClearCache.addEventListener('click', async () => {
      const targetUrl = getTargetArchiveUrl();
      await deleteCachedGcsArchive(targetUrl);
      log(`[GCS] Cleared cached archive: ${targetUrl}`, 'info');
      await updateGcsUI();
    });
  }
}
