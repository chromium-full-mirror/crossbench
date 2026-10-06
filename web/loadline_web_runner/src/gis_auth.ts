// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

/**
 * Google Identity Services (GIS) OAuth 2.0 Web Authentication Manager.
 * Implements 1-Click OAuth 2.0 Web Authentication, token lifecycle management,
 * and session persistence for Google Cloud Storage archive access.
 */

export interface GisTokenResponse {
  access_token: string;
  expires_in: number|string;
  scope?: string;
  token_type?: string;
  error?: string;
  error_description?: string;
  error_uri?: string;
  state?: string;
  details?: string;
}

export interface GisAuthSession {
  accessToken: string;
  tokenType: string;
  expiresAt: number;  // Epoch timestamp in ms
  scope: string;
  userEmail?: string;
}

export interface GisAuthConfig {
  clientId: string;
  scope?: string;
  prompt?: string;
}

export interface GisAuthStatus {
  type: 'none'|'gis'|'manual'|'expired';
  token: string;
  email?: string;
  expiresInSeconds: number;
  displayText: string;
}

export const GIS_SESSION_STORAGE_KEY = 'crossbench_gis_auth_session';
export const GIS_CLIENT_ID_STORAGE_KEY = 'crossbench_gis_client_id';
export const DEFAULT_GCS_READONLY_SCOPE =
    'https://www.googleapis.com/auth/devstorage.read_only';
export const DEFAULT_CLIENT_ID =
    '161886483514-ii0p3mlg6na6cbimqs18rqsgc50hj1f7.apps.googleusercontent.com';

declare global {
  interface Window {
    google?: {
      accounts?: {
        oauth2?: {
          initTokenClient:
              (config: {
                client_id: string; scope: string;
                callback: (response: GisTokenResponse) => void;
                error_callback?: (error: any) => void;
                prompt?: string;
                hint?: string;
                enable_serial_consent?: boolean;
              }) => {
                requestAccessToken: (
                    overrideConfig?: {prompt?: string; hint?: string;}) => void;
              };
          revoke: (token: string, done?: () => void) => void;
          hasGrantedAllScopes:
              (tokenResponse: GisTokenResponse, firstScope: string,
               ...restScopes: string[]) => boolean;
          hasGrantedAnyScope:
              (tokenResponse: GisTokenResponse, firstScope: string,
               ...restScopes: string[]) => boolean;
        };
      };
    };
  }
}

/**
 * Loads the Google Identity Services SDK script dynamically if not present.
 */
export function loadGisScript(
    src = 'https://accounts.google.com/gsi/client',
    timeoutMs = 10000,
    ): Promise<void> {
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return Promise.resolve();
  }

  if (window.google?.accounts?.oauth2) {
    return Promise.resolve();
  }

  return new Promise((resolve, reject) => {
    const existingScript = document.querySelector(`script[src="${src}"]`);
    if (existingScript) {
      if (window.google?.accounts?.oauth2) {
        return resolve();
      }
      existingScript.addEventListener('load', () => resolve());
      existingScript.addEventListener(
          'error',
          () => reject(
              new Error(`Failed to load Google Identity Services from ${src}`),
              ),
      );
      return;
    }

    const script = document.createElement('script');
    script.src = src;
    script.async = true;
    script.defer = true;

    const timer = setTimeout(() => {
      reject(
          new Error('Timed out waiting for Google Identity Services script.'),
      );
    }, timeoutMs);

    script.onload = () => {
      clearTimeout(timer);
      resolve();
    };

    script.onerror = () => {
      clearTimeout(timer);
      reject(new Error(`Failed to load Google Identity Services from ${src}`));
    };

    document.head.appendChild(script);
  });
}

/**
 * Retrieves the configured OAuth 2.0 Web Client ID.
 */
export function getClientId(): string {
  try {
    const customId = localStorage.getItem(GIS_CLIENT_ID_STORAGE_KEY);
    if (customId && customId.trim()) {
      return customId.trim();
    }
  } catch (err) {
    console.warn('Failed to read GIS client ID from localStorage:', err);
  }
  return DEFAULT_CLIENT_ID;
}

/**
 * Persists a custom OAuth 2.0 Web Client ID.
 */
export function setClientId(clientId: string): void {
  try {
    if (clientId && clientId.trim() && clientId.trim() !== DEFAULT_CLIENT_ID) {
      localStorage.setItem(GIS_CLIENT_ID_STORAGE_KEY, clientId.trim());
    } else {
      localStorage.removeItem(GIS_CLIENT_ID_STORAGE_KEY);
    }
  } catch (err) {
    console.warn('Failed to save GIS client ID:', err);
  }
}

/**
 * Retrieves the current GIS Auth session from localStorage.
 */
export function getStoredAuthSession(): GisAuthSession|null {
  try {
    const raw = localStorage.getItem(GIS_SESSION_STORAGE_KEY);
    if (!raw)
      return null;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed.accessToken === 'string' &&
        typeof parsed.expiresAt === 'number') {
      return parsed as GisAuthSession;
    }
  } catch (err) {
    console.warn('Failed to parse stored GIS auth session:', err);
  }
  return null;
}

/**
 * Persists the GIS Auth session to localStorage.
 */
export function setStoredAuthSession(session: GisAuthSession|null): void {
  try {
    if (session) {
      const serialized = JSON.stringify(session);
      localStorage.setItem(GIS_SESSION_STORAGE_KEY, serialized);
    } else {
      localStorage.removeItem(GIS_SESSION_STORAGE_KEY);
    }
  } catch (err) {
    console.warn('Failed to store GIS auth session:', err);
  }
}

/**
 * Clears the active GIS session.
 */
export function clearAuthSession(): void {
  try {
    localStorage.removeItem(GIS_SESSION_STORAGE_KEY);
  } catch (err) {
    console.warn('Failed to clear GIS auth session:', err);
  }
}

/**
 * Checks if a session is expired or within the safety buffer window.
 */
export function isSessionExpired(
    session: GisAuthSession|null,
    bufferSeconds = 60,
    ): boolean {
  if (!session || !session.accessToken) {
    return true;
  }
  const remainingMs = session.expiresAt - Date.now();
  return remainingMs <= bufferSeconds * 1000;
}

/**
 * Attempts to retrieve user identity / email associated with the access token.
 */
export async function fetchUserEmail(
    token: string,
    ): Promise<string|undefined> {
  if (!token || !token.trim()) {
    return undefined;
  }
  try {
    const encodedToken = encodeURIComponent(token.trim());
    const tokenInfoUrl =
        `https://www.googleapis.com/oauth2/v3/tokeninfo?access_token=` +
        encodedToken;
    const res = await fetch(tokenInfoUrl);
    if (res.ok) {
      const data = await res.json();
      if (data && data.email) {
        return String(data.email);
      }
    }
  } catch (err) {
    console.warn('Failed to fetch user email from tokeninfo:', err);
  }
  return undefined;
}

/**
 * Returns the active GIS token if valid and not expired.
 */
export function getEffectiveGisToken(): string {
  const session = getStoredAuthSession();
  if (session && !isSessionExpired(session)) {
    return session.accessToken;
  }
  return '';
}

/**
 * Manages Google Identity Services OAuth 2.0 Token Client workflow.
 */
export class GisAuthManager {
  private clientId: string;
  private scope: string;

  constructor(config?: Partial<GisAuthConfig>) {
    this.clientId = config?.clientId || getClientId();
    this.scope = config?.scope || DEFAULT_GCS_READONLY_SCOPE;
  }

  public getClientId(): string {
    return this.clientId;
  }

  public setClientId(clientId: string): void {
    this.clientId = clientId.trim() || DEFAULT_CLIENT_ID;
    setClientId(this.clientId);
  }

  public getScope(): string {
    return this.scope;
  }

  public setScope(scope: string): void {
    this.scope = scope.trim() || DEFAULT_GCS_READONLY_SCOPE;
  }

  /**
   * Initiates the OAuth 2.0 Token Client popup consent flow.
   * When running in an isolated browser context (COOP: same-origin), opens the
   * non-isolated /auth.html popup relay and communicates via
   * BroadcastChannel/storage.
   */
  public async signIn(
      options?: {prompt?: string; hint?: string; direct?: boolean;}):
      Promise<GisAuthSession> {
    if (!options?.prompt && !options?.direct) {
      const existingSession = getStoredAuthSession();
      if (existingSession && !isSessionExpired(existingSession)) {
        return existingSession;
      }
    }

    const isBrowser = typeof window !== 'undefined' &&
        typeof window.open === 'function' &&
        typeof window.location !== 'undefined' && Boolean(window.location.href);

    if (isBrowser && !options?.direct) {
      return new Promise<GisAuthSession>((resolve, reject) => {
        let isResolved = false;
        let authWindow: Window|null = null;
        let timer: ReturnType<typeof setInterval>|null = null;
        let pollTimer: ReturnType<typeof setInterval>|null = null;
        let closedTimer: ReturnType<typeof setTimeout>|null = null;
        let broadcastChannel: BroadcastChannel|null = null;
        let popupReportedOpen = Boolean(window.crossOriginIsolated);
        const initialSession = getStoredAuthSession();

        const isNewOrUpdatedSession =
            (session: GisAuthSession|null): session is GisAuthSession => {
              if (!session || isSessionExpired(session)) {
                return false;
              }
              if (!initialSession) {
                return true;
              }
              return session.accessToken !== initialSession.accessToken ||
                  session.expiresAt !== initialSession.expiresAt;
            };

        const cleanup = () => {
          if (timer) {
            clearInterval(timer);
            timer = null;
          }
          if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
          }
          if (closedTimer) {
            clearTimeout(closedTimer);
            closedTimer = null;
          }
          if (broadcastChannel) {
            try {
              broadcastChannel.postMessage({type: 'GIS_AUTH_CLOSE_POPUP'});
              broadcastChannel.close();
            } catch (err) {
              console.warn('Failed to close BroadcastChannel:', err);
            }
          }
          window.removeEventListener('storage', onStorage);
        };

        const handleSuccess = (session: GisAuthSession) => {
          if (isResolved)
            return;
          isResolved = true;
          cleanup();
          setStoredAuthSession(session);
          if (authWindow && !authWindow.closed) {
            try {
              authWindow.close();
            } catch (err) {
              console.warn('Failed to close authWindow:', err);
            }
          }
          resolve(session);
        };

        const handleError = (errMsg: string) => {
          if (isResolved)
            return;
          isResolved = true;
          cleanup();
          if (authWindow && !authWindow.closed) {
            try {
              authWindow.close();
            } catch (err) {
              console.warn('Failed to close authWindow:', err);
            }
          }
          reject(new Error(`Google Sign-In failed: ${errMsg}`));
        };

        const scheduleWindowClosedCheck = () => {
          if (closedTimer) {
            clearTimeout(closedTimer);
          }
          closedTimer = setTimeout(() => {
            if (!isResolved) {
              const storedSession = getStoredAuthSession();
              if (isNewOrUpdatedSession(storedSession)) {
                handleSuccess(storedSession);
              } else {
                handleError('Sign-in window was closed by user.');
              }
            }
          }, 600);
        };

        const markPopupOpen = () => {
          popupReportedOpen = true;
          if (timer) {
            clearInterval(timer);
            timer = null;
          }
          if (closedTimer) {
            clearTimeout(closedTimer);
            closedTimer = null;
          }
        };

        if (typeof BroadcastChannel !== 'undefined') {
          try {
            broadcastChannel = new BroadcastChannel('crossbench_gis_auth');
            broadcastChannel.onmessage = (event) => {
              if (event.data?.type === 'GIS_AUTH_SUCCESS' &&
                  event.data.session) {
                handleSuccess(event.data.session);
              } else if (event.data?.type === 'GIS_AUTH_POPUP_OPENED') {
                markPopupOpen();
              } else if (event.data?.type === 'GIS_AUTH_WINDOW_CLOSED') {
                scheduleWindowClosedCheck();
              }
            };
          } catch (err) {
            console.warn(
                'Failed to initialize BroadcastChannel for GIS auth:',
                err,
            );
          }
        }

        const onStorage = (e: StorageEvent) => {
          const isAuthKey = e.key === 'crossbench_gis_auth_broadcast' ||
              e.key === GIS_SESSION_STORAGE_KEY;
          if (isAuthKey && e.newValue) {
            try {
              const data = JSON.parse(e.newValue);
              if (data?.type === 'GIS_AUTH_SUCCESS' && data.session) {
                handleSuccess(data.session);
              } else if (data?.type === 'GIS_AUTH_POPUP_OPENED') {
                markPopupOpen();
              } else if (data?.type === 'GIS_AUTH_WINDOW_CLOSED') {
                scheduleWindowClosedCheck();
              } else if (data?.accessToken && data?.expiresAt) {
                handleSuccess(data as GisAuthSession);
              }
            } catch (err) {
              console.warn('Failed to parse storage event data:', err);
            }
          }
        };
        window.addEventListener('storage', onStorage);

        pollTimer = setInterval(() => {
          const session = getStoredAuthSession();
          if (isNewOrUpdatedSession(session)) {
            handleSuccess(session);
          }
        }, 400);

        const authUrl = `/auth.html?client_id=${
            encodeURIComponent(
                this.clientId,
                )}&scope=${encodeURIComponent(this.scope)}&prompt=${
            encodeURIComponent(
                options?.prompt ?? 'consent',
                )}${
            options?.hint ? `&hint=${encodeURIComponent(options.hint)}` : ''}`;

        const width = 500;
        const height = 650;
        const left = Math.max(0, (window.screen.width - width) / 2);
        const top = Math.max(0, (window.screen.height - height) / 2);

        authWindow = window.open(
            authUrl,
            'crossbench_gis_auth_popup',
            `width=${width},height=${height},top=${top},left=${left},` +
                'status=no,resizable=yes',
        );

        if (!authWindow) {
          cleanup();
          return reject(
              new Error(
                  'Failed to open Google Sign-In window. ' +
                      'Please allow popups for this site.',
                  ),
          );
        }

        if (!popupReportedOpen) {
          timer = setInterval(() => {
            if (popupReportedOpen) {
              clearInterval(timer!);
              timer = null;
              return;
            }
            if (authWindow && authWindow.closed) {
              clearInterval(timer!);
              timer = null;
              scheduleWindowClosedCheck();
            }
          }, 500);
        }
      });
    }

    await loadGisScript();

    if (!window.google?.accounts?.oauth2) {
      throw new Error(
          'Google Identity Services SDK is not loaded. ' +
              'Please verify your internet connection.',
      );
    }

    return new Promise((resolve, reject) => {
      try {
        const client = window.google!.accounts!.oauth2!.initTokenClient({
          client_id: this.clientId,
          scope: this.scope,
          callback: async (response: GisTokenResponse) => {
            if (response.error) {
              const errMsg = response.error_description || response.details ||
                  response.error ||
                  'OAuth authorization was cancelled or failed.';
              return reject(new Error(`Google Sign-In failed: ${errMsg}`));
            }

            const rawExpiresIn = parseInt(
                String(response.expires_in || '3599'),
                10,
            );
            const expiresIn =
                isNaN(rawExpiresIn) || rawExpiresIn <= 0 ? 3599 : rawExpiresIn;
            const expiresAt = Date.now() + expiresIn * 1000;

            const session: GisAuthSession = {
              accessToken: response.access_token,
              tokenType: response.token_type || 'Bearer',
              expiresAt,
              scope: response.scope || this.scope,
            };

            // Attempt to retrieve user identity if possible
            try {
              const email = await fetchUserEmail(session.accessToken);
              if (email) {
                session.userEmail = email;
              }
            } catch (err) {
              console.warn('Failed to populate user email:', err);
            }

            setStoredAuthSession(session);
            resolve(session);
          },
          error_callback: (err: any) => {
            reject(
                new Error(
                    `Google Sign-In error: ` +
                        `${err?.message || err?.type || JSON.stringify(err)}`,
                    ),
            );
          },
        });

        client.requestAccessToken({
          prompt: options?.prompt ?? 'consent',
          hint: options?.hint,
        });
      } catch (err: any) {
        reject(
            new Error(
                `Failed to initiate Google OAuth 2.0 flow: ${
                    err?.message || err}`,
                ),
        );
      }
    });
  }

  /**
   * Signs out the user and revokes the active token if supported.
   */
  public async signOut(): Promise<void> {
    try {
      const session = getStoredAuthSession();
      const hasRevoke = Boolean(
          window.google?.accounts?.oauth2?.revoke,
      );
      if (session && session.accessToken && hasRevoke) {
        try {
          await new Promise<void>((resolve) => {
            const timer = setTimeout(() => {
              console.warn(
                  'Timeout waiting for Google OAuth token revocation.',
              );
              resolve();
            }, 3000);
            window.google!.accounts!.oauth2!.revoke(session.accessToken, () => {
              clearTimeout(timer);
              resolve();
            });
          });
        } catch (err) {
          console.warn('Failed to revoke Google OAuth token:', err);
        }
      }
    } finally {
      clearAuthSession();
    }
  }

  /**
   * Returns a valid access token. If expired and interactive is requested,
   * launches the GIS consent flow to refresh.
   */
  public async getValidAccessToken(options?: {
    interactive?: boolean;
    prompt?: string;
  }): Promise<string|null> {
    const session = getStoredAuthSession();
    if (session && !isSessionExpired(session)) {
      return session.accessToken;
    }

    if (options?.interactive) {
      const newSession = await this.signIn({
        prompt: options?.prompt ?? '',
      });
      return newSession.accessToken;
    }

    return null;
  }

  /**
   * Returns detailed current authorization status for UI badges and
   * diagnostics.
   */
  public getAuthStatus(manualToken = ''): GisAuthStatus {
    const session = getStoredAuthSession();

    if (session && session.accessToken) {
      const remainingMs = session.expiresAt - Date.now();
      const remainingSeconds = Math.max(0, Math.floor(remainingMs / 1000));
      const isExpired = remainingSeconds <= 0;

      if (!isExpired) {
        const minutes = Math.floor(remainingSeconds / 60);
        const emailLabel = session.userEmail ? ` (${session.userEmail})` : '';
        const timeLabel = minutes > 0 ? ` [${minutes}m left]` : ` [<1m left]`;
        return {
          type: 'gis',
          token: session.accessToken,
          email: session.userEmail,
          expiresInSeconds: remainingSeconds,
          displayText: `Authenticated${emailLabel}${timeLabel}`,
        };
      }

      const emailSuffix = session.userEmail ? ` (${session.userEmail})` : '';
      return {
        type: 'expired',
        token: session.accessToken,
        email: session.userEmail,
        expiresInSeconds: 0,
        displayText: `OAuth Token Expired${emailSuffix}`,
      };
    }

    if (manualToken && manualToken.trim()) {
      return {
        type: 'manual',
        token: manualToken.trim(),
        expiresInSeconds: Infinity,
        displayText: 'Manual Token Set',
      };
    }

    return {
      type: 'none',
      token: '',
      expiresInSeconds: 0,
      displayText: 'No Token',
    };
  }
}

export const gisAuthManager = new GisAuthManager();
