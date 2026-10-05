// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

/**
 * LoadLine / Crossbench Web Runner - Interactive UI Controller & Main Entry
 * Point.
 */

import {setupAuthUIEventListeners, startGcsUpdateInterval, updateGcsUI,} from './auth_ui';
import {setupBenchmarkEventListeners} from './benchmark_controller';
import {isTestEnvironment, log, setInitializing, setupUIEventListeners, updateUI,} from './ui_state';
import {isWebUsbSupported, WebAdbBridge} from './webadb_bridge';

export * from './ui_state';
export * from './benchmark_controller';
export {type Logger, type LogLevel, getTargetArchiveUrl, setupAuthUIEventListeners, setAuthLogger, startGcsUpdateInterval, stopGcsUpdateInterval, updateGcsUI,} from './auth_ui';

// Global state instance
export const webAdbBridge = new WebAdbBridge();

export function setupDeviceEventListeners(): void {
  const btnConnect =
      document.getElementById('btn-connect') as HTMLButtonElement | null;
  const btnDisconnect =
      document.getElementById('btn-disconnect') as HTMLButtonElement | null;

  if (btnConnect) {
    btnConnect.addEventListener('click', async () => {
      if (!isWebUsbSupported()) {
        const errMsg =
            'Cannot connect device: WebUSB is not supported in this browser. ' +
            'Please use a browser with WebUSB support ' +
            '(e.g. Google Chrome).';
        log(errMsg, 'error');
        updateUI(false, null, errMsg);
        return;
      }
      updateUI(false);
      try {
        log('Prompting for USB Android device selection...');
        const device = await webAdbBridge.requestDevice();
        if (!device) {
          log('Device selection cancelled by user.', 'warn');
          return;
        }

        log('Establishing ADB transport connection...');
        await webAdbBridge.connect(device);
        log(`Successfully connected to Android device (${webAdbBridge.serial})`,
            'success');
        updateUI(true, webAdbBridge.serial);
      } catch (err: any) {
        const errorMsg = `Connection failed: ${err?.message || err}. `;
        log(errorMsg, 'error');
        updateUI(false, null, errorMsg);
      }
    });
  }

  if (btnDisconnect) {
    btnDisconnect.addEventListener('click', async () => {
      try {
        log('Disconnecting ADB USB session...');
        await webAdbBridge.disconnect();
        log('Device disconnected.', 'info');
        updateUI(false);
      } catch (err: any) {
        log(`Error during disconnect: ${err?.message || err}`, 'error');
        updateUI(false);
      }
    });
  }
}

export async function initApp(): Promise<void> {
  setInitializing(true);
  try {
    setupDeviceEventListeners();
    setupAuthUIEventListeners();
    setupBenchmarkEventListeners(webAdbBridge);
    setupUIEventListeners();

    await updateGcsUI();
    if (isWebUsbSupported()) {
      log('LoadLine Web Runner initialized. Ready to authenticate or connect ' +
          'USB device.');
    } else {
      const unsupportedMsg =
          'WebUSB is not supported in this browser. Please use a browser ' +
          'with WebUSB support (e.g. Google Chrome).';
      log(unsupportedMsg, 'warn');
    }
    startGcsUpdateInterval();
  } catch (err) {
    console.error('Initialization error:', err);
  } finally {
    setInitializing(false);
    updateUI(webAdbBridge.isConnected, webAdbBridge.serial);
  }
}

if (typeof window !== 'undefined' && typeof document !== 'undefined' &&
    Boolean(document.getElementById('init-overlay')) && !isTestEnvironment) {
  initApp();
}
