// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

/**
 * Main-thread client proxy for communicating with the Pyodide Web Worker.
 */

import {type LogHandler, type PyodideWorkerRequest, type PyodideWorkerResponse,} from './pyodide_runner';

export class PyodideWorkerClient {
  private worker: Worker;
  private idCounter = 1;
  private pendingRequests = new Map < number, {
    resolve: (res: any) => void;
    reject: (err: any) => void
  }
  >();
  private interruptBuffer?: Uint8Array;
  private stopFlag?: Int32Array;

  constructor(
      workerUrlOrWorker: string|Worker,
      private adbHandler: (method: string, args: any[]) => Promise<any>,
      private onLog?: LogHandler,
  ) {
    if (typeof SharedArrayBuffer !== 'undefined') {
      try {
        const sab = new SharedArrayBuffer(8);
        this.interruptBuffer = new Uint8Array(sab, 0, 1);
        this.stopFlag = new Int32Array(sab, 4, 1);
      } catch {
        // SharedArrayBuffer not available
      }
    }
    this.worker = typeof workerUrlOrWorker === 'string' ?
        new Worker(workerUrlOrWorker, {type: 'module'}) :
        workerUrlOrWorker;
    this.worker.onmessage =
        async (event: MessageEvent<PyodideWorkerResponse>) => {
      const data = event.data;
      if (data.type === 'LOG' && data.message) {
        if (this.onLog) {
          this.onLog(data.message, data.level || 'info');
        } else {
          console.log(`[Python] ${data.message}`);
        }
        return;
      }

      if (data.type === 'SYNC_RPC_REQUEST' && data.sab && data.method) {
        const sab = data.sab;
        const int32View = new Int32Array(sab);
        const uint8View = new Uint8Array(sab);

        const writeError = (errMsg: string) => {
          int32View[0] = 2;  // Error status
          const errBytes = new TextEncoder().encode(errMsg);
          const maxLen = Math.min(errBytes.length, sab.byteLength - 8);
          uint8View.set(errBytes.subarray(0, maxLen), 8);
          int32View[1] = maxLen;
          Atomics.notify(int32View, 0, 1);
        };

        if (this.interruptBuffer && this.interruptBuffer[0] === 2) {
          this.interruptBuffer[0] = 0;
          writeError('BenchmarkExecutionInterrupted: Stopped by user');
          return;
        }

        try {
          const res = await this.adbHandler(data.method, data.args || []);
          let resBytes: Uint8Array;
          if (res instanceof Uint8Array) {
            resBytes = res;
          } else {
            const resStr = String(res ?? '');
            resBytes = new TextEncoder().encode(resStr);
          }
          if (resBytes.length > sab.byteLength - 8) {
            throw new Error(
                `RPC response size (${resBytes.length} bytes) exceeds buffer ` +
                `capacity (${sab.byteLength - 8} bytes)`);
          }
          uint8View.set(resBytes, 8);
          int32View[1] = resBytes.length;
          int32View[0] = 1;
          Atomics.notify(int32View, 0, 1);
        } catch (err: any) {
          const errStr = err?.message || String(err);
          writeError(errStr);
        }
        return;
      }

      if (data.id && this.pendingRequests.has(data.id)) {
        const {resolve, reject} = this.pendingRequests.get(data.id)!;
        this.pendingRequests.delete(data.id);
        if (data.type === 'ERROR') {
          reject(new Error(data.error));
        } else {
          resolve(data.result !== undefined ? data.result : data);
        }
      }
    };
  }

  isInterrupted(): boolean {
    return Boolean(
        (this.stopFlag && Atomics.load(this.stopFlag, 0) === 1) ||
        (this.interruptBuffer && this.interruptBuffer[0] === 2));
  }

  wasInterrupted(): boolean {
    return Boolean(this.stopFlag && Atomics.load(this.stopFlag, 0) === 1);
  }

  interrupt(): void {
    if (this.stopFlag) {
      Atomics.store(this.stopFlag, 0, 1);
    }
    if (this.interruptBuffer) {
      this.interruptBuffer[0] = 2;  // SIGINT / KeyboardInterrupt
    }
  }

  clearInterrupt(): void {
    if (this.stopFlag) {
      Atomics.store(this.stopFlag, 0, 0);
    }
    if (this.interruptBuffer) {
      this.interruptBuffer[0] = 0;
    }
  }

  getInterruptBuffer(): Uint8Array|undefined {
    return this.interruptBuffer;
  }

  getStopFlag(): Int32Array|undefined {
    return this.stopFlag;
  }

  async init(interruptBuffer?: Uint8Array, stopFlag?: Int32Array):
      Promise<void> {
    const buf = interruptBuffer ?? this.interruptBuffer;
    const flag = stopFlag ?? this.stopFlag;
    await this.sendRequest('INIT', {
      interruptBuffer: buf,
      stopFlag: flag,
    });
  }

  async mountFiles(files: Record<string, string>): Promise<void> {
    await this.sendRequest('MOUNT_FILES', {files});
  }

  async runScript(script: string): Promise<any> {
    return await this.sendRequest('RUN_SCRIPT', {script});
  }

  async runBenchmark(benchmarkArgs: string[] = []): Promise<any> {
    return await this.sendRequest('RUN_BENCHMARK', {benchmarkArgs});
  }

  async exportResultsZip(runDir?: string): Promise<Uint8Array> {
    const res = await this.sendRequest('EXPORT_RESULTS_ZIP', {runDir});
    if (res instanceof Uint8Array) {
      return res;
    }
    if (res?.zipBytes instanceof Uint8Array) {
      return res.zipBytes;
    }
    throw new Error(
        'Invalid exportResultsZip response: expected Uint8Array, ' +
        `got ${typeof res}`);
  }

  async getBenchmarkScoreCsv(runDir?: string): Promise<string> {
    const res = await this.sendRequest('GET_BENCHMARK_SCORE_CSV', {runDir});
    return typeof res === 'string' ? res : '';
  }

  async mountBinaryFile(path: string, data: Uint8Array): Promise<void> {
    await this.sendRequest('MOUNT_BINARY_FILE', {
      binaryPath: path,
      binaryData: data,
    });
  }

  async sendRequest(
      type: PyodideWorkerRequest['type'],
      payload: Partial<PyodideWorkerRequest> = {}): Promise<any> {
    const id = this.idCounter++;
    return new Promise((resolve, reject) => {
      this.pendingRequests.set(id, {resolve, reject});
      this.worker.postMessage({type, id, ...payload});
    });
  }
}
