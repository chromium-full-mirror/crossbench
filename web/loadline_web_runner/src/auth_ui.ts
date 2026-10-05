// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

/**
 * Authentication and Google Cloud Storage WPR archive UI controller.
 */

import {type CachedGcsArchive, clearStoredAccessToken, deleteCachedGcsArchive, downloadGcsArchive, getCachedGcsArchive, getManualAccessToken, getStoredAccessToken, setStoredAccessToken, TARGET_GCS_ARCHIVE_URL,} from './gcs_cache';
import {getStoredAuthSession, gisAuthManager, isSessionExpired,} from './gis_auth';
import {log as uiLog} from './ui_state';

export type LogLevel = 'info'|'warn'|'error'|'success';
export type Logger = (message: string, level?: LogLevel) => void;

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

export function getTargetArchiveUrl(): string {
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
    if (cached && cached.data && cached.data.length > 0) {
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

  const targetArchiveInput = document.getElementById(
                                 'target-archive-input',
                                 ) as HTMLInputElement |
      null;
  if (targetArchiveInput) {
    targetArchiveInput.addEventListener('input', () => updateGcsUI());
    targetArchiveInput.addEventListener('change', () => updateGcsUI());
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
  const downloadProgressContainer = document.getElementById(
                                        'download-progress-container',
                                        ) as HTMLElement |
      null;
  const downloadStatusText = document.getElementById(
                                 'download-status-text',
                                 ) as HTMLElement |
      null;
  const downloadPercentage = document.getElementById(
                                 'download-percentage',
                                 ) as HTMLElement |
      null;
  const downloadProgressBar = document.getElementById(
                                  'download-progress-bar',
                                  ) as HTMLElement |
      null;

  if (btnDownloadArchive) {
    btnDownloadArchive.addEventListener('click', async () => {
      const targetUrl = getTargetArchiveUrl();
      let token = (gcsTokenInput?.value || getStoredAccessToken()).trim();
      if (!token) {
        log('No active GCP token. Prompting for Google Sign-In...');
        try {
          const session = await gisAuthManager.signIn();
          token = session.accessToken;
          await updateGcsUI();
        } catch (authErr: any) {
          log(
              `Cannot download archive: ${
                  authErr?.message || 'No GCP access token provided.'}`,
              'error',
          );
          gcsTokenInput?.focus();
          return;
        }
      }

      btnDownloadArchive.disabled = true;
      if (btnSaveToken)
        btnSaveToken.disabled = true;
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
              if (total > 0) {
                const pct = Math.min(100, Math.round((loaded / total) * 100));
                const loadedMb = (loaded / (1024 * 1024)).toFixed(1);
                const totalMb = (total / (1024 * 1024)).toFixed(1);
                if (downloadStatusText) {
                  downloadStatusText.innerText =
                      `Downloading: ${loadedMb} MB / ${totalMb} MB (${pct}%)`;
                }
                if (downloadPercentage)
                  downloadPercentage.innerText = `${pct}%`;
                if (downloadProgressBar) {
                  downloadProgressBar.style.width = `${pct}%`;
                }
              } else {
                const loadedMb = (loaded / (1024 * 1024)).toFixed(1);
                if (downloadStatusText) {
                  downloadStatusText.innerText =
                      `Downloading: ${loadedMb} MB...`;
                }
              }
            });

        const mb = (cached.size / (1024 * 1024)).toFixed(1);
        log(
            `[GCS] Successfully downloaded and cached ${cached.filename} (${
                mb} MB).`,
            'success',
        );
        await updateGcsUI();
      } catch (err: any) {
        log(`[GCS Error] Download failed: ${err?.message || err}`, 'error');
        const session = getStoredAuthSession();
        if (session && isSessionExpired(session)) {
          log(
              'Your OAuth token has expired. Click "Renew Session" or ' +
                  '"Sign in with Google" to refresh.',
              'warn',
          );
        }
      } finally {
        btnDownloadArchive.disabled = false;
        if (btnSaveToken)
          btnSaveToken.disabled = false;
        setTimeout(() => {
          if (downloadProgressContainer) {
            downloadProgressContainer.style.display = 'none';
          }
        }, 3000);
      }
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
