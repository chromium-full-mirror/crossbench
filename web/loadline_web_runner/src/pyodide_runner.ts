// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

/**
 * Pyodide WebAssembly runner and Crossbench benchmark executor.
 */

import {loadPyodide, type PyodideInterface} from 'pyodide';

import {initHjsonParser, PYTHON_BOOTSTRAP_SCRIPT} from './pyodide_bootstrap';
import {type WebAdbProxy} from './sync_rpc_bridge';
import {TraceProcessorWasmEngine} from './trace_processor_wasm';

export type LogLevel = 'info'|'warn'|'error'|'success';
export type LogHandler = (message: string, level?: LogLevel) => void;

export interface PyodideWorkerRequest {
  type:|'INIT'|'MOUNT_FILES'|'MOUNT_BINARY_FILE'|'RUN_SCRIPT'|'RUN_BENCHMARK'|
      'EXPORT_RESULTS_ZIP'|'GET_BENCHMARK_SCORE_CSV'|'SET_INTERRUPT_BUFFER';
  id?: number;
  files?: Record<string, string>;
  binaryPath?: string;
  binaryData?: Uint8Array;
  script?: string;
  benchmarkArgs?: string[];
  runDir?: string;
  interruptBuffer?: Uint8Array;
  stopFlag?: Int32Array;
}

export interface PyodideWorkerResponse {
  type:|'INIT_DONE'|'MOUNT_DONE'|'MOUNT_BINARY_FILE_DONE'|'SCRIPT_DONE'|
      'BENCHMARK_DONE'|'EXPORT_RESULTS_ZIP_DONE'|'GET_BENCHMARK_SCORE_CSV_DONE'|
      'INTERRUPT_DONE'|'ERROR'|'LOG'|'ADB_CALL'|'SYNC_RPC_REQUEST';
  id?: number;
  result?: any;
  zipBytes?: Uint8Array;
  error?: string;
  message?: string;
  level?: LogLevel;
  method?: string;
  args?: any[];
  sab?: SharedArrayBuffer;
}

export class PyodideRunner {
  private tpEngine: TraceProcessorWasmEngine = new TraceProcessorWasmEngine();
  private pyodide: PyodideInterface|null = null;
  private webAdb: WebAdbProxy|null = null;
  private onLog?: LogHandler;
  private interruptBuffer: Uint8Array|null = null;
  private stopFlag: Int32Array|null = null;
  private pendingInterrupt: boolean = false;
  private wasInterruptedFlag: boolean = false;

  private loadPyodideFn: typeof loadPyodide = loadPyodide;

  constructor(
      webAdb?: WebAdbProxy, onLog?: LogHandler,
      loadPyodideFn?: typeof loadPyodide) {
    if (webAdb) {
      this.webAdb = webAdb;
    }
    if (onLog) {
      this.onLog = onLog;
    }
    if (loadPyodideFn) {
      this.loadPyodideFn = loadPyodideFn;
    }
  }

  setInterruptBuffer(buffer: Uint8Array, stopFlag?: Int32Array): void {
    this.interruptBuffer = buffer;
    if (stopFlag !== undefined) {
      this.stopFlag = stopFlag;
    } else if (buffer && buffer.buffer.byteLength >= 8) {
      try {
        this.stopFlag = new Int32Array(buffer.buffer, 4, 1);
      } catch {
        this.stopFlag = null;
      }
    }
    if (this.webAdb &&
        typeof (this.webAdb as any).setInterruptBuffer === 'function') {
      (this.webAdb as any).setInterruptBuffer(buffer, this.stopFlag);
    }
    if (this.pyodide &&
        typeof (this.pyodide as any).setInterruptBuffer === 'function') {
      (this.pyodide as any).setInterruptBuffer(buffer);
    }
  }

  isInterrupted(): boolean {
    return Boolean(
        (this.interruptBuffer && this.interruptBuffer[0] === 2) ||
        this.pendingInterrupt);
  }

  wasInterrupted(): boolean {
    return Boolean(
        (this.stopFlag && Atomics.load(this.stopFlag, 0) === 1) ||
        this.wasInterruptedFlag);
  }

  acknowledgeInterrupt(): void {
    if (this.interruptBuffer) {
      this.interruptBuffer[0] = 0;
    }
    this.pendingInterrupt = false;
    this.wasInterruptedFlag = true;
    if (this.webAdb &&
        typeof (this.webAdb as any).acknowledgeInterrupt === 'function') {
      (this.webAdb as any).acknowledgeInterrupt();
    }
  }

  interrupt(): void {
    if (this.stopFlag) {
      Atomics.store(this.stopFlag, 0, 1);
    }
    if (this.interruptBuffer) {
      this.interruptBuffer[0] = 2;
    }
    this.pendingInterrupt = true;
    this.wasInterruptedFlag = true;
    if (this.webAdb && typeof (this.webAdb as any).interrupt === 'function') {
      (this.webAdb as any).interrupt();
    }
  }

  clearInterrupt(): void {
    this.pendingInterrupt = false;
    this.wasInterruptedFlag = false;
    if (this.stopFlag) {
      Atomics.store(this.stopFlag, 0, 0);
    }
    if (this.interruptBuffer) {
      this.interruptBuffer[0] = 0;
    }
    if (this.webAdb &&
        typeof (this.webAdb as any).clearInterrupt === 'function') {
      (this.webAdb as any).clearInterrupt();
    }
  }

  setOnLog(onLog: LogHandler): void {
    this.onLog = onLog;
  }

  async init(): Promise<void> {
    await initHjsonParser();

    const isNode = typeof process !== 'undefined' && process.versions != null &&
        process.versions.node != null;

    const stdoutHandler = (msg: string) => {
      if (this.onLog) {
        this.onLog(msg, 'info');
      } else {
        console.log(`[Python] ${msg}`);
      }
    };
    const stderrHandler = (msg: string) => {
      if (this.onLog) {
        this.onLog(msg, 'error');
      } else {
        console.error(`[Python] ${msg}`);
      }
    };

    let loadOpts: any = {
      indexURL: 'https://cdn.jsdelivr.net/pyodide/v0.29.3/full/',
      stdout: stdoutHandler,
      stderr: stderrHandler,
    };
    if (isNode) {
      const {createRequire} = await import('node:module');
      const pathMod = await import('node:path');
      const req = createRequire(import.meta.url);
      try {
        const undici = req('undici');
        if (undici?.fetch) {
          globalThis.fetch = undici.fetch;
          globalThis.Headers = undici.Headers;
          globalThis.Request = undici.Request;
          globalThis.Response = undici.Response;
        }
      } catch {
        // undici not available
      }
      loadOpts = {
        indexURL: pathMod.dirname(req.resolve('pyodide')) + '/',
        stdout: stdoutHandler,
        stderr: stderrHandler,
      };
    }
    this.pyodide = await this.loadPyodideFn(loadOpts);
    if (this.interruptBuffer &&
        typeof (this.pyodide as any).setInterruptBuffer === 'function') {
      (this.pyodide as any).setInterruptBuffer(this.interruptBuffer);
    }
    if (typeof this.pyodide?.setStdout === 'function') {
      this.pyodide.setStdout({batched: stdoutHandler});
    }
    if (typeof this.pyodide?.setStderr === 'function') {
      this.pyodide.setStderr({batched: stderrHandler});
    }
    await this.tpEngine.initialize();
    try {
      await this.pyodide.loadPackage([
        'typing-extensions',
        'packaging',
        'protobuf',
        'micropip',
        'numpy',
        'pandas',
        'scipy',
        'tabulate',
      ]);
    } catch {
      await this.pyodide.loadPackage([
        'typing-extensions',
        'packaging',
        'protobuf',
        'micropip',
        'numpy',
        'pandas',
        'scipy',
      ]);
    }
    try {
      if (typeof this.pyodide.pyimport === 'function') {
        const micropip = this.pyodide.pyimport('micropip');
        await micropip.install(['xlsxwriter', 'tabulate']);
      }
    } catch (err) {
      console.warn('Failed to load packages via micropip:', err);
    }
    this.registerWebAdb(this.webAdb || ({} as WebAdbProxy));
    if (typeof this.pyodide?.runPythonAsync === 'function') {
      await this.pyodide.runPythonAsync(PYTHON_BOOTSTRAP_SCRIPT);
    }
  }

  registerWebAdb(webAdb: WebAdbProxy): void {
    this.webAdb = webAdb;
    if (webAdb && typeof webAdb === 'object') {
      if (typeof (webAdb as any).isInterrupted !== 'function') {
        (webAdb as any).isInterrupted = () => this.isInterrupted();
      }
      if (typeof (webAdb as any).wasInterrupted !== 'function') {
        (webAdb as any).wasInterrupted = () => this.wasInterrupted();
      }
    }
    const jsExports = {
      webadb: webAdb,
      parseHjson: (globalThis as any).parseHjson,
      tp_parse: (chunk: any) => {
        const bytes = chunk instanceof Uint8Array ? chunk :
            chunk?.toJs                           ? chunk.toJs() :
                                                    new Uint8Array(chunk || []);
        this.tpEngine.appendTraceData(bytes);
      },
      tp_finalize: () => this.tpEngine.finalizeTraceData(),
      tp_reset: () => this.tpEngine.reset(),
      tp_register_sql_package: (packageName: string, modules: any) => {
        const rawModules = modules?.toJs ?
            modules.toJs({dict_converter: Object.fromEntries}) :
            modules;
        if (!Array.isArray(rawModules)) {
          throw new Error(
              'tp_register_sql_package: expected array of modules for ' +
              `package "${packageName}"`);
        }
        const modArray: Array<{name: string; sql: string}> =
            rawModules.map((m: any) => {
              const name = m?.name ??
                  (typeof m?.get === 'function' ? m.get('name') : undefined);
              const sql = m?.sql ??
                  (typeof m?.get === 'function' ? m.get('sql') : undefined);
              if (typeof name !== 'string' || typeof sql !== 'string') {
                throw new Error(
                    'tp_register_sql_package: invalid module entry in ' +
                    `package "${packageName}"`);
              }
              return {name, sql};
            });
        this.tpEngine.registerSqlPackage(packageName, modArray);
      },
      tp_query: (sql: string) => {
        const res = this.tpEngine.query(sql);
        return JSON.stringify(res);
      },
      tp_compute_metric: (metrics: any) => {
        const mList: string[] = Array.isArray(metrics) ? metrics :
            metrics?.toJs                              ? metrics.toJs() :
                                                         [String(metrics)];
        const res = this.tpEngine.computeMetric(mList);
        return JSON.stringify({bytes: Array.from(res)});
      },
    };
    Object.assign(globalThis, jsExports);
    if (this.pyodide) {
      this.pyodide.registerJsModule('js', jsExports);
    }
  }

  async mountFiles(files: Record<string, string>): Promise<void> {
    if (!this.pyodide) {
      throw new Error('Pyodide not initialized');
    }
    for (const [path, content] of Object.entries(files)) {
      const dir = path.substring(0, path.lastIndexOf('/'));
      if (dir) {
        const analyze = this.pyodide.FS.analyzePath;
        if (!analyze || !analyze(dir).exists) {
          try {
            this.pyodide.FS.mkdirTree(dir);
          } catch (err: any) {
            if (err?.code !== 'EEXIST') {
              throw err;
            }
          }
        }
      }
      this.pyodide.FS.writeFile(path, content);
    }
    if (typeof this.pyodide.runPython === 'function') {
      this.pyodide.runPython('import importlib; importlib.invalidate_caches()');
    }
  }

  async mountBinaryFile(path: string, data: Uint8Array): Promise<void> {
    if (!this.pyodide) {
      throw new Error('Pyodide not initialized');
    }
    const dir = path.substring(0, path.lastIndexOf('/'));
    if (dir) {
      const analyze = this.pyodide.FS.analyzePath;
      if (!analyze || !analyze(dir).exists) {
        try {
          this.pyodide.FS.mkdirTree(dir);
        } catch (err: any) {
          if (err?.code !== 'EEXIST') {
            throw err;
          }
        }
      }
    }
    this.pyodide.FS.writeFile(path, data);
    if (typeof this.pyodide.runPython === 'function') {
      this.pyodide.runPython('import importlib; importlib.invalidate_caches()');
    }
  }

  async runScript(script: string): Promise<any> {
    if (!this.pyodide) {
      throw new Error('Pyodide not initialized');
    }
    return await this.pyodide.runPythonAsync(script);
  }

  async runCrossbench(benchmarkArgs: string[] = []): Promise<any> {
    if (!this.pyodide) {
      throw new Error('Pyodide not initialized');
    }
    this.clearInterrupt();
    const argsJson = JSON.stringify(benchmarkArgs);
    const script = `
def _run_cb():
    import json
    import sys
    import traceback
    import js
    from crossbench.cli.cli import CrossBenchCLI

    webadb = getattr(js, "webadb", None)
    def _check_interrupted_result():
        if hasattr(webadb, "wasInterrupted") and webadb.wasInterrupted():
            return True
        if hasattr(webadb, "isInterrupted") and webadb.isInterrupted():
            return True
        return False

    try:
        args = json.loads(${JSON.stringify(argsJson)})
        cli = CrossBenchCLI()
        cli.run(args)
        if _check_interrupted_result():
            return "INTERRUPTED"
        return "SUCCESS"
    except SystemExit as e:
        if _check_interrupted_result():
            return "INTERRUPTED"
        if e.code not in (0, None):
            return f"SYSTEM_EXIT_{e.code}:\\n" + traceback.format_exc()
        return "SUCCESS"
    except KeyboardInterrupt:
        return "INTERRUPTED"
    except Exception as e:
        if _check_interrupted_result() or (
            "BenchmarkExecutionInterrupted" in str(e)
        ):
            return "INTERRUPTED"
        return f"ERROR ({type(e).__name__}: {e}):\\n" + traceback.format_exc()

_run_cb()
`;
    const res = await this.pyodide.runPythonAsync(script);
    if (typeof res === 'string' &&
        (res.startsWith('ERROR') || res.startsWith('SYSTEM_EXIT'))) {
      console.error(res);
      throw new Error(res);
    }
    return res;
  }

  async exportResultsZip(runDir?: string): Promise<Uint8Array> {
    if (!this.pyodide) {
      throw new Error('Pyodide not initialized');
    }
    const escapedRunDir = runDir ? JSON.stringify(runDir) : 'None';
    const pyScript = `
import io
import os
import zipfile

def _cb_zip_results(target_dir):
    if not target_dir or target_dir == "None":
        if not os.path.exists("/results"):
            raise FileNotFoundError("Results directory /results not found")
        entries = [os.path.join("/results", d) for d in os.listdir("/results")]
        dirs = [d for d in entries if os.path.isdir(d)]
        if dirs:
            target_dir = max(dirs, key=os.path.getmtime)
        else:
            target_dir = "/results"
    if not os.path.exists(target_dir):
        raise FileNotFoundError(f"Target directory {target_dir} not found")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(target_dir):
            for d in list(dirs):
                full_dir_path = os.path.join(root, d)
                if os.path.islink(full_dir_path):
                    arcname = os.path.relpath(full_dir_path, target_dir)
                    link_target = os.readlink(full_dir_path)
                    zinfo = zipfile.ZipInfo(arcname)
                    zinfo.create_system = 3  # Unix
                    zinfo.external_attr = (0o120777 << 16)
                    zf.writestr(zinfo, link_target)
                    dirs.remove(d)
            for f in files:
                full_path = os.path.join(root, f)
                arcname = os.path.relpath(full_path, target_dir)
                if os.path.islink(full_path):
                    link_target = os.readlink(full_path)
                    zinfo = zipfile.ZipInfo(arcname)
                    zinfo.create_system = 3  # Unix
                    zinfo.external_attr = (0o120777 << 16)
                    zf.writestr(zinfo, link_target)
                else:
                    zf.write(full_path, arcname)
    return buf.getvalue()

_cb_zip_results(${escapedRunDir})
`;
    const res = await this.pyodide.runPythonAsync(pyScript);
    if (res instanceof Uint8Array) {
      return res;
    }
    if (typeof res?.toJs === 'function') {
      return res.toJs();
    }
    if (res instanceof ArrayBuffer) {
      return new Uint8Array(res);
    }
    throw new Error(
        `Failed to export results zip: unexpected result type ${typeof res}`);
  }

  async getBenchmarkScoreCsv(runDir?: string): Promise<string> {
    if (!this.pyodide) {
      throw new Error('Pyodide not initialized');
    }
    const escapedRunDir = runDir ? JSON.stringify(runDir) : 'None';
    const pyScript = `
import os

def _cb_get_score_csv(target_dir):
    if not target_dir or target_dir == "None":
        if not os.path.exists("/results"):
            return ""
        entries = [os.path.join("/results", d) for d in os.listdir("/results")]
        dirs = [d for d in entries if os.path.isdir(d)]
        if dirs:
            target_dir = max(dirs, key=os.path.getmtime)
        else:
            target_dir = "/results"
    if not os.path.exists(target_dir):
        return ""
    direct_path = os.path.join(target_dir, "benchmark_score.csv")
    if os.path.isfile(direct_path):
        with open(direct_path, "r", encoding="utf-8") as f:
            return f.read()
    for root, _, files in os.walk(target_dir):
        if "benchmark_score.csv" in files:
            full_path = os.path.join(root, "benchmark_score.csv")
            with open(full_path, "r", encoding="utf-8") as f:
                return f.read()
    return ""

_cb_get_score_csv(${escapedRunDir})
`;
    const res = await this.pyodide.runPythonAsync(pyScript);
    return typeof res === 'string' ? res : String(res ?? '');
  }

  getFS(): any {
    if (!this.pyodide) {
      throw new Error('Pyodide not initialized');
    }
    return this.pyodide.FS;
  }
}
