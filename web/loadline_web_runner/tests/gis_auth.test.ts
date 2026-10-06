// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {beforeEach, describe, expect, it, vi} from 'vitest';

import {clearAuthSession, DEFAULT_CLIENT_ID, DEFAULT_GCS_READONLY_SCOPE, fetchUserEmail, getClientId, getEffectiveGisToken, getStoredAuthSession, GIS_CLIENT_ID_STORAGE_KEY, GIS_SESSION_STORAGE_KEY, GisAuthManager, type GisAuthSession, isSessionExpired, loadGisScript, setClientId, setStoredAuthSession,} from '../src/gis_auth';

describe('Google Identity Services (GIS) OAuth 2.0 Auth', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.restoreAllMocks();
    delete (window as any).google;
  });

  describe('Client ID Configuration', () => {
    it('returns DEFAULT_CLIENT_ID when no custom ID is configured', () => {
      expect(getClientId()).toBe(DEFAULT_CLIENT_ID);
    });

    it('sets and retrieves custom client ID from localStorage', () => {
      const customId = '123456-custom.apps.googleusercontent.com';
      setClientId(customId);
      expect(getClientId()).toBe(customId);
      expect(localStorage.getItem(GIS_CLIENT_ID_STORAGE_KEY)).toBe(customId);
    });

    it('clears custom client ID when empty string is passed', () => {
      setClientId('custom-id');
      expect(getClientId()).toBe('custom-id');
      setClientId('');
      expect(getClientId()).toBe(DEFAULT_CLIENT_ID);
      expect(localStorage.getItem(GIS_CLIENT_ID_STORAGE_KEY)).toBeNull();
    });
  });

  describe('Session Storage Management', () => {
    it('stores, retrieves, and clears auth session in localStorage', () => {
      expect(getStoredAuthSession()).toBeNull();

      const session: GisAuthSession = {
        accessToken: 'mock_token_test_access_token_123',
        tokenType: 'Bearer',
        expiresAt: Date.now() + 3600 * 1000,
        scope: DEFAULT_GCS_READONLY_SCOPE,
        userEmail: 'engineer@google.com',
      };

      setStoredAuthSession(session);
      const retrieved = getStoredAuthSession();
      expect(retrieved).not.toBeNull();
      expect(retrieved?.accessToken).toBe('mock_token_test_access_token_123');
      expect(retrieved?.userEmail).toBe('engineer@google.com');
      expect(
          localStorage.getItem(GIS_SESSION_STORAGE_KEY),
          )
          .toContain('mock_token_test_access_token_123');

      clearAuthSession();
      expect(getStoredAuthSession()).toBeNull();
      expect(localStorage.getItem(GIS_SESSION_STORAGE_KEY)).toBeNull();
    });

    it('handles corrupted JSON in localStorage safely', () => {
      localStorage.setItem(GIS_SESSION_STORAGE_KEY, '{ invalid json');
      expect(getStoredAuthSession()).toBeNull();
    });
  });

  describe('isSessionExpired', () => {
    it('returns true for null or empty sessions', () => {
      expect(isSessionExpired(null)).toBe(true);
      expect(
          isSessionExpired({
            accessToken: '',
            tokenType: 'Bearer',
            expiresAt: Date.now() + 3600000,
            scope: DEFAULT_GCS_READONLY_SCOPE,
          }),
          )
          .toBe(true);
    });

    it('returns false when session expires in the future (> buffer)', () => {
      const session: GisAuthSession = {
        accessToken: 'mock_token_active',
        tokenType: 'Bearer',
        expiresAt: Date.now() + 3600 * 1000,
        scope: DEFAULT_GCS_READONLY_SCOPE,
      };
      expect(isSessionExpired(session)).toBe(false);
    });

    it('returns true when session is within the safety buffer window', () => {
      const session: GisAuthSession = {
        accessToken: 'mock_token_expiring_soon',
        tokenType: 'Bearer',
        expiresAt: Date.now() + 30 * 1000,  // 30s remaining (< 60s buffer)
        scope: DEFAULT_GCS_READONLY_SCOPE,
      };
      expect(isSessionExpired(session, 60)).toBe(true);
    });

    it('returns true when session is already in the past', () => {
      const session: GisAuthSession = {
        accessToken: 'mock_token_expired',
        tokenType: 'Bearer',
        expiresAt: Date.now() - 1000,
        scope: DEFAULT_GCS_READONLY_SCOPE,
      };
      expect(isSessionExpired(session)).toBe(true);
    });
  });

  describe('getEffectiveGisToken', () => {
    it('returns token if active session exists and is not expired', () => {
      const session: GisAuthSession = {
        accessToken: 'mock_token_effective_valid_token',
        tokenType: 'Bearer',
        expiresAt: Date.now() + 3600 * 1000,
        scope: DEFAULT_GCS_READONLY_SCOPE,
      };
      setStoredAuthSession(session);
      expect(getEffectiveGisToken()).toBe('mock_token_effective_valid_token');
    });

    it('returns empty string if session is expired or missing', () => {
      const session: GisAuthSession = {
        accessToken: 'mock_token_expired',
        tokenType: 'Bearer',
        expiresAt: Date.now() - 10000,
        scope: DEFAULT_GCS_READONLY_SCOPE,
      };
      setStoredAuthSession(session);
      expect(getEffectiveGisToken()).toBe('');
    });
  });

  describe('fetchUserEmail', () => {
    it('returns email from tokeninfo endpoint', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          email: 'testuser@chromium.org',
          scope: DEFAULT_GCS_READONLY_SCOPE,
        }),
      });

      const email = await fetchUserEmail('mock_token_mock_token');
      expect(email).toBe('testuser@chromium.org');
    });

    it('returns undefined if token is empty or fetch fails', async () => {
      expect(await fetchUserEmail('')).toBeUndefined();

      global.fetch = vi.fn().mockRejectedValue(new Error('Network error'));
      expect(await fetchUserEmail('mock_token_bad')).toBeUndefined();
    });
  });

  describe('loadGisScript', () => {
    it('resolves immediately if google.accounts.oauth2 is already present',
       async () => {
         (window as any).google = {
           accounts: {
             oauth2: {
               initTokenClient: vi.fn(),
             },
           },
         };

         await expect(loadGisScript()).resolves.toBeUndefined();
       });

    it('dynamically appends script element and resolves on load', async () => {
      const appendSpy = vi.spyOn(document.head, 'appendChild');

      const testUrl = 'https://accounts.google.com/gsi/client-test';
      const promise = loadGisScript(testUrl);
      const addedScript = appendSpy.mock.calls[0][0] as HTMLScriptElement;
      expect(addedScript.src).toContain(testUrl);

      // Simulate script load
      addedScript.onload?.(new Event('load'));
      await expect(promise).resolves.toBeUndefined();
    });
  });

  describe('GisAuthManager', () => {
    let authManager: GisAuthManager;

    beforeEach(() => {
      authManager = new GisAuthManager();
    });

    it('configures custom client ID and scope', () => {
      authManager.setClientId('custom-client-123.apps.googleusercontent.com');
      const customClient = 'custom-client-123.apps.googleusercontent.com';
      expect(authManager.getClientId()).toBe(customClient);

      const fullScope =
          'https://www.googleapis.com/auth/devstorage.full_control';
      authManager.setScope(fullScope);
      expect(authManager.getScope())
          .toBe(
              'https://www.googleapis.com/auth/devstorage.full_control',
          );
    });

    it('signs in successfully using GIS OAuth 2.0 initTokenClient',
       async () => {
         let capturedConfig: any = null;
         let requestedPrompt: string|undefined = undefined;

         (window as any).google = {
           accounts: {
             oauth2: {
               initTokenClient: (config: any) => {
                 capturedConfig = config;
                 return {
                   requestAccessToken: (override: any) => {
                     requestedPrompt = override?.prompt;
                     // Simulate successful async callback
                     setTimeout(() => {
                       config.callback({
                         access_token: 'mock_token_gis_login_success',
                         expires_in: '3600',
                         scope: DEFAULT_GCS_READONLY_SCOPE,
                         token_type: 'Bearer',
                       });
                     }, 0);
                   },
                 };
               },
             },
           },
         };

         global.fetch = vi.fn().mockResolvedValue({
           ok: true,
           json: async () => ({
             email: 'partner@example.com',
           }),
         });

         const session = await authManager.signIn({
           prompt: 'consent',
           direct: true,
         });

         expect(capturedConfig.client_id).toBe(authManager.getClientId());
         expect(requestedPrompt).toBe('consent');
         expect(session.accessToken).toBe('mock_token_gis_login_success');
         expect(session.userEmail).toBe('partner@example.com');
         expect(getStoredAuthSession()?.accessToken)
             .toBe(
                 'mock_token_gis_login_success',
             );
       });

    it('rejects on OAuth error from GIS response', async () => {
      (window as any).google = {
        accounts: {
          oauth2: {
            initTokenClient: (config: any) => ({
              requestAccessToken: () => {
                setTimeout(() => {
                  config.callback({
                    error: 'access_denied',
                    error_description: 'User denied storage access',
                  });
                }, 0);
              },
            }),
          },
        },
      };

      await expect(authManager.signIn({direct: true}))
          .rejects.toThrow(
              /Google Sign-In failed: User denied storage access/,
          );
    });

    describe('Popup Relay Flow', () => {
      it('rejects when popup window is blocked by browser', async () => {
        vi.spyOn(window, 'open').mockReturnValue(null);
        await expect(authManager.signIn())
            .rejects.toThrow(
                /Failed to open Google Sign-In window\./,
            );
        await expect(authManager.signIn())
            .rejects.toThrow(
                /Please allow popups for this site\./,
            );
      });

      it('rejects when popup window is closed by user', async () => {
        const mockPopup = {
          closed: true,
          close: vi.fn(),
        } as any;
        vi.spyOn(window, 'open').mockReturnValue(mockPopup);

        vi.useFakeTimers();
        try {
          const promise = expect(authManager.signIn())
                              .rejects.toThrow(
                                  /Sign-in window was closed by user\./,
                              );
          await vi.advanceTimersByTimeAsync(1500);
          await promise;
        } finally {
          vi.useRealTimers();
        }
      });

      it('resolves on successful BroadcastChannel message', async () => {
        const mockPopup = {
          closed: false,
          close: vi.fn(),
        } as any;
        vi.spyOn(window, 'open').mockReturnValue(mockPopup);

        const mockSession: GisAuthSession = {
          accessToken: 'mock_token_broadcast_success',
          tokenType: 'Bearer',
          expiresAt: Date.now() + 3600 * 1000,
          scope: DEFAULT_GCS_READONLY_SCOPE,
          userEmail: 'user@example.com',
        };

        const channel = new BroadcastChannel('crossbench_gis_auth');
        setTimeout(() => {
          channel.postMessage({
            type: 'GIS_AUTH_SUCCESS',
            session: mockSession,
          });
        }, 20);

        const session = await authManager.signIn();
        channel.close();

        expect(session.accessToken).toBe('mock_token_broadcast_success');
        expect(session.userEmail).toBe('user@example.com');
        expect(getStoredAuthSession()?.accessToken)
            .toBe(
                'mock_token_broadcast_success',
            );
        expect(mockPopup.close).toHaveBeenCalled();
      });

      it('reuses existing valid session without opening popup', async () => {
        const existingSession: GisAuthSession = {
          accessToken: 'mock_token_already_authenticated',
          tokenType: 'Bearer',
          expiresAt: Date.now() + 3600 * 1000,
          scope: DEFAULT_GCS_READONLY_SCOPE,
          userEmail: 'existing@google.com',
        };
        setStoredAuthSession(existingSession);
        const openSpy = vi.spyOn(window, 'open');

        const session = await authManager.signIn();
        expect(session.accessToken).toBe('mock_token_already_authenticated');
        expect(openSpy).not.toHaveBeenCalled();
      });

      it('waits for BroadcastChannel completion when COOP severs popup',
         async () => {
           const originalIsolated = window.crossOriginIsolated;
           Object.defineProperty(window, 'crossOriginIsolated', {
             value: true,
             configurable: true,
             writable: true,
           });

           // Simulate COOP severing the popup reference immediately (closed =
           // true)
           const mockPopup = {
             closed: true,
             close: vi.fn(),
           } as any;
           vi.spyOn(window, 'open').mockReturnValue(mockPopup);

           const mockSession: GisAuthSession = {
             accessToken: 'mock_token_coop_isolated_success',
             tokenType: 'Bearer',
             expiresAt: Date.now() + 3600 * 1000,
             scope: DEFAULT_GCS_READONLY_SCOPE,
             userEmail: 'coop@google.com',
           };

           vi.useFakeTimers();
           try {
             const signInPromise = authManager.signIn();

             // Advance past the old 1.1s premature close timeout; promise must
             // still be pending while user completes sign-in in the popup.
             await vi.advanceTimersByTimeAsync(2500);

             const channel = new BroadcastChannel('crossbench_gis_auth');
             channel.postMessage({
               type: 'GIS_AUTH_SUCCESS',
               session: mockSession,
             });
             channel.close();

             const session = await signInPromise;
             expect(session.accessToken)
                 .toBe('mock_token_coop_isolated_success');
             expect(getStoredAuthSession()?.accessToken)
                 .toBe('mock_token_coop_isolated_success');
           } finally {
             vi.useRealTimers();
             Object.defineProperty(window, 'crossOriginIsolated', {
               value: originalIsolated,
               configurable: true,
               writable: true,
             });
           }
         });
    });

    it('signs out and revokes active token', async () => {
      let revokedToken = '';
      (window as any).google = {
        accounts: {
          oauth2: {
            revoke: (token: string, cb: () => void) => {
              revokedToken = token;
              cb();
            },
          },
        },
      };

      const session: GisAuthSession = {
        accessToken: 'mock_token_token_to_revoke',
        tokenType: 'Bearer',
        expiresAt: Date.now() + 3600 * 1000,
        scope: DEFAULT_GCS_READONLY_SCOPE,
      };
      setStoredAuthSession(session);

      await authManager.signOut();

      expect(revokedToken).toBe('mock_token_token_to_revoke');
      expect(getStoredAuthSession()).toBeNull();
    });

    it('signOut does not hang if revoke callback never fires', async () => {
      (window as any).google = {
        accounts: {
          oauth2: {
            revoke: vi.fn(),  // never calls done
          },
        },
      };
      const session: GisAuthSession = {
        accessToken: 'mock_token_hang_token',
        tokenType: 'Bearer',
        expiresAt: Date.now() + 3600 * 1000,
        scope: DEFAULT_GCS_READONLY_SCOPE,
      };
      setStoredAuthSession(session);

      vi.useFakeTimers();
      try {
        const signOutPromise = authManager.signOut();
        await vi.advanceTimersByTimeAsync(3500);
        await expect(signOutPromise).resolves.toBeUndefined();
      } finally {
        vi.useRealTimers();
      }
      expect(getStoredAuthSession()).toBeNull();
    });

    it('getAuthStatus returns accurate display status for all scenarios',
       () => {
         // 1. No token
         let status = authManager.getAuthStatus('');
         expect(status.type).toBe('none');
         expect(status.displayText).toBe('No Token');

         // 2. Manual token
         status = authManager.getAuthStatus('mock_token_manual_token');
         expect(status.type).toBe('manual');
         expect(status.displayText).toBe('Manual Token Set');

         // 3. Valid GIS token with email
         const validSession: GisAuthSession = {
           accessToken: 'mock_token_valid_gis',
           tokenType: 'Bearer',
           expiresAt: Date.now() + 50 * 60 * 1000,  // 50 mins left
           scope: DEFAULT_GCS_READONLY_SCOPE,
           userEmail: 'user@google.com',
         };
         setStoredAuthSession(validSession);
         status = authManager.getAuthStatus();
         expect(status.type).toBe('gis');
         expect(status.email).toBe('user@google.com');
         expect(status.displayText)
             .toContain('Authenticated (user@google.com)');
         expect(status.displayText).toContain('50m left');

         // 4. Expired GIS token
         const expiredSession: GisAuthSession = {
           accessToken: 'mock_token_expired_gis',
           tokenType: 'Bearer',
           expiresAt: Date.now() - 10000,
           scope: DEFAULT_GCS_READONLY_SCOPE,
           userEmail: 'user@google.com',
         };
         setStoredAuthSession(expiredSession);
         status = authManager.getAuthStatus();
         expect(status.type).toBe('expired');
         expect(status.displayText)
             .toContain(
                 'OAuth Token Expired (user@google.com)',
             );
       });
  });
});
