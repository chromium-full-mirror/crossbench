// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

/**
 * Pyodide Web Worker entry point.
 */

import {LogLevel, PyodideRunner, type PyodideWorkerRequest, type PyodideWorkerResponse,} from './pyodide_runner';
import {SynchronousWorkerAdbBridge} from './sync_rpc_bridge';

export * from './pyodide_bootstrap';
export * from './sync_rpc_bridge';
export * from './pyodide_runner';
export * from './worker_client';

if (typeof self !== 'undefined' && typeof Window === 'undefined' &&
    'onmessage' in self) {
  const adbBridge = new SynchronousWorkerAdbBridge();
  const runner = new PyodideRunner(
      adbBridge,
      (message: string, level?: LogLevel) => {
        self.postMessage({
          type: 'LOG',
          message,
          level: level ?? 'info',
        } satisfies PyodideWorkerResponse);
      },
  );
  adbBridge.setFs(() => runner.getFS());
  self.onmessage = async (event: MessageEvent<PyodideWorkerRequest>) => {
    const {
      type,
      id,
      files,
      binaryPath,
      binaryData,
      script,
      runDir,
      interruptBuffer,
      stopFlag,
    } = event.data;
    try {
      if (type === 'INIT') {
        if (interruptBuffer) {
          runner.setInterruptBuffer(interruptBuffer, stopFlag);
          adbBridge.setInterruptBuffer(interruptBuffer, stopFlag);
        }
        await runner.init();
        self.postMessage({
          type: 'INIT_DONE',
          id,
        } satisfies PyodideWorkerResponse);
      } else if (type === 'SET_INTERRUPT_BUFFER') {
        if (interruptBuffer) {
          runner.setInterruptBuffer(interruptBuffer, stopFlag);
          adbBridge.setInterruptBuffer(interruptBuffer, stopFlag);
        }
        self.postMessage({
          type: 'INTERRUPT_DONE',
          id,
        } satisfies PyodideWorkerResponse);
      } else if (type === 'MOUNT_FILES' && files) {
        await runner.mountFiles(files);
        self.postMessage({
          type: 'MOUNT_DONE',
          id,
        } satisfies PyodideWorkerResponse);
      } else if (type === 'MOUNT_BINARY_FILE' && binaryPath && binaryData) {
        await runner.mountBinaryFile(binaryPath, binaryData);
        self.postMessage({
          type: 'MOUNT_BINARY_FILE_DONE',
          id,
        } satisfies PyodideWorkerResponse);
      } else if (type === 'RUN_SCRIPT' && script) {
        const result = await runner.runScript(script);
        self.postMessage({
          type: 'SCRIPT_DONE',
          id,
          result,
        } satisfies PyodideWorkerResponse);
      } else if (type === 'RUN_BENCHMARK') {
        const benchmarkArgs = event.data.benchmarkArgs || [];
        const result = await runner.runCrossbench(benchmarkArgs);
        self.postMessage({
          type: 'BENCHMARK_DONE',
          id,
          result,
        } satisfies PyodideWorkerResponse);
      } else if (type === 'EXPORT_RESULTS_ZIP') {
        const zipBytes = await runner.exportResultsZip(runDir);
        self.postMessage({
          type: 'EXPORT_RESULTS_ZIP_DONE',
          id,
          result: zipBytes,
          zipBytes,
        } satisfies PyodideWorkerResponse);
      } else if (type === 'GET_BENCHMARK_SCORE_CSV') {
        const csvText = await runner.getBenchmarkScoreCsv(runDir);
        self.postMessage({
          type: 'GET_BENCHMARK_SCORE_CSV_DONE',
          id,
          result: csvText,
        } satisfies PyodideWorkerResponse);
      } else {
        throw new Error(`Unknown worker request type: ${type}`);
      }
    } catch (err: any) {
      self.postMessage({
        type: 'ERROR',
        id,
        error: err?.message || String(err),
      } satisfies PyodideWorkerResponse);
    }
  };
}
