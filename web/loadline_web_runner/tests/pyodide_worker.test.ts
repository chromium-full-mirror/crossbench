// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {beforeEach, describe, expect, it, vi} from 'vitest';

import {PyodideRunner, PyodideWorkerClient, type WebAdbProxy,} from '../src/pyodide_worker.js';

describe('PyodideRunner', () => {
  let mockPyodide: any;
  let mockWebAdb: WebAdbProxy;
  let mockLoadPyodide: any;

  beforeEach(() => {
    mockPyodide = {
      loadPackage: vi.fn().mockResolvedValue(undefined),
      registerJsModule: vi.fn(),
      runPython: vi.fn(),
      runPythonAsync: vi.fn().mockResolvedValue(
          JSON.stringify({
            status: 'SUCCESS',
            version: '1.0.0',
            url: 'about:blank',
            iterations: 1,
          }),
          ),
      FS: {
        mkdirTree: vi.fn(),
        writeFile: vi.fn(),
      },
    };
    mockLoadPyodide = vi.fn().mockResolvedValue(mockPyodide as any);

    mockWebAdb = {
      serial: 'webadb-mock-123',
      shell: vi.fn().mockReturnValue('mock shell output'),
      push: vi.fn(),
      pull: vi.fn(),
    };
  });

  it('initializes and registers webadb JS module', async () => {
    const runner = new PyodideRunner(mockWebAdb, undefined, mockLoadPyodide);
    await runner.init();
    expect(mockLoadPyodide).toHaveBeenCalled();
    expect(mockPyodide.registerJsModule)
        .toHaveBeenCalledWith(
            'js',
            expect.objectContaining({
              webadb: mockWebAdb,
            }),
        );
  });

  it('mounts virtual filesystem files into Pyodide FS', async () => {
    const runner = new PyodideRunner(undefined, undefined, mockLoadPyodide);
    await runner.init();
    await runner.mountFiles({
      '/crossbench/__init__.py': '__version__ = "1.0.0"',
      '/crossbench/main.py': 'print("hello")',
    });
    expect(mockPyodide.FS.mkdirTree).toHaveBeenCalledWith('/crossbench');
    expect(mockPyodide.FS.writeFile)
        .toHaveBeenCalledWith(
            '/crossbench/__init__.py',
            '__version__ = "1.0.0"',
        );
    expect(mockPyodide.FS.writeFile)
        .toHaveBeenCalledWith(
            '/crossbench/main.py',
            'print("hello")',
        );
  });

  it('executes Crossbench benchmark via CLI arguments', async () => {
    const runner = new PyodideRunner(mockWebAdb, undefined, mockLoadPyodide);
    await runner.init();
    await runner.runCrossbench(['loadline2-phone', '--browser', 'cdp:chrome']);
    expect(mockPyodide.runPythonAsync).toHaveBeenCalled();
    const script = vi.mocked(mockPyodide.runPythonAsync).mock.lastCall![0];
    expect(script).toContain('from crossbench.cli.cli import CrossBenchCLI');
    expect(script).toContain('loadline2-phone');
    expect(script).toContain('--browser');
  });

  it('captures stdout and stderr via onLog handler', async () => {
    const logs: Array<{msg: string; level?: string}> = [];
    const runner = new PyodideRunner(mockWebAdb, (msg, level) => {
      logs.push({msg, level});
    }, mockLoadPyodide);
    await runner.init();
    expect(mockLoadPyodide).toHaveBeenCalled();

    const loadOpts = vi.mocked(mockLoadPyodide).mock.lastCall![0] as any;
    expect(loadOpts.stdout).toBeDefined();
    expect(loadOpts.stderr).toBeDefined();

    loadOpts.stdout('Testing stdout output from Python');
    loadOpts.stderr('Testing stderr error from Python');

    expect(logs).toEqual([
      {msg: 'Testing stdout output from Python', level: 'info'},
      {msg: 'Testing stderr error from Python', level: 'error'},
    ]);
  });

  it('exports results zip via Python zipfile', async () => {
    const runner = new PyodideRunner(mockWebAdb, undefined, mockLoadPyodide);
    mockPyodide.runPythonAsync =
        vi.fn().mockResolvedValue(new Uint8Array([80, 75, 3, 4]));
    await runner.init();
    const zipBytes = await runner.exportResultsZip('/results/run1');
    expect(zipBytes).toEqual(new Uint8Array([80, 75, 3, 4]));
    expect(mockPyodide.runPythonAsync).toHaveBeenCalled();
  });

  it('sets interrupt buffer on pyodide when configured', async () => {
    mockPyodide.setInterruptBuffer = vi.fn();
    const runner = new PyodideRunner(mockWebAdb, undefined, mockLoadPyodide);
    const sab = new SharedArrayBuffer(1);
    const buf = new Uint8Array(sab);
    runner.setInterruptBuffer(buf);
    await runner.init();
    expect(mockPyodide.setInterruptBuffer).toHaveBeenCalledWith(buf);
  });

  it('handles interrupted execution returning INTERRUPTED', async () => {
    const runner = new PyodideRunner(mockWebAdb, undefined, mockLoadPyodide);
    mockPyodide.runPythonAsync = vi.fn().mockResolvedValue('INTERRUPTED');
    await runner.init();
    const res = await runner.runCrossbench(['loadline2-phone']);
    expect(res).toBe('INTERRUPTED');
  });

  it('throws error if methods called before init', async () => {
    const runner = new PyodideRunner(undefined, undefined, mockLoadPyodide);
    await expect(runner.runScript('print(1)'))
        .rejects.toThrow(
            'Pyodide not initialized',
        );
    await expect(
        runner.mountFiles({'/test.py': 'pass'}),
        )
        .rejects.toThrow('Pyodide not initialized');
  });

  it('throws error when CLI exit code indicates error or failure', async () => {
    const runner = new PyodideRunner(mockWebAdb, undefined, mockLoadPyodide);
    mockPyodide.runPythonAsync = vi.fn().mockResolvedValue(
        'SYSTEM_EXIT_2:\nUsage error: unknown option');
    await runner.init();
    await expect(runner.runCrossbench(['--invalid-flag']))
        .rejects.toThrow('SYSTEM_EXIT_2');
  });

  it('acknowledges interrupt cleanly without recursion', async () => {
    const acknowledgeInterruptSpy = vi.fn();
    const customAdb: any = {
      acknowledgeInterrupt: acknowledgeInterruptSpy,
    };
    const runner = new PyodideRunner(customAdb, undefined, mockLoadPyodide);
    const sab = new SharedArrayBuffer(8);
    const interruptBuf = new Uint8Array(sab, 0, 1);
    runner.setInterruptBuffer(interruptBuf);
    await runner.init();

    runner.interrupt();
    expect(runner.isInterrupted()).toBe(true);

    runner.acknowledgeInterrupt();
    expect(runner.isInterrupted()).toBe(false);
    expect(runner.wasInterrupted()).toBe(true);
    expect(acknowledgeInterruptSpy).toHaveBeenCalled();
  });
});

describe('PyodideWorkerClient', () => {
  it('supports interrupt() and clearInterrupt() on shared buffer', () => {
    const mockWorker = {
      postMessage: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      onmessage: null as any,
    };
    const client = new PyodideWorkerClient(mockWorker as any, vi.fn());
    const buf = client.getInterruptBuffer();
    expect(buf).toBeDefined();
    if (buf) {
      expect(buf[0]).toBe(0);
      expect(client.isInterrupted()).toBe(false);

      client.interrupt();
      expect(buf[0]).toBe(2);
      expect(client.isInterrupted()).toBe(true);

      client.clearInterrupt();
      expect(buf[0]).toBe(0);
      expect(client.isInterrupted()).toBe(false);
    }
  });

  it('exports results zip via worker request and returns Uint8Array',
     async () => {
       const mockWorker = {
         postMessage: vi.fn(),
         addEventListener: vi.fn(),
         removeEventListener: vi.fn(),
         onmessage: null as any,
       };
       const client = new PyodideWorkerClient(mockWorker as any, vi.fn());
       const expectedBytes = new Uint8Array([80, 75, 3, 4]);

       mockWorker.postMessage = vi.fn().mockImplementation((req: any) => {
         if (req.type === 'EXPORT_RESULTS_ZIP') {
           mockWorker.onmessage({
             data: {
               type: 'EXPORT_RESULTS_ZIP_DONE',
               id: req.id,
               result: expectedBytes,
               zipBytes: expectedBytes,
             },
           });
         }
       });

       const zip = await client.exportResultsZip('/results/run1');
       expect(zip).toEqual(expectedBytes);
     });

  it('fetches benchmark_score.csv via worker request and returns string',
     async () => {
       const mockWorker = {
         postMessage: vi.fn(),
         addEventListener: vi.fn(),
         removeEventListener: vi.fn(),
         onmessage: null as any,
       };
       const client = new PyodideWorkerClient(mockWorker as any, vi.fn());
       const expectedCsv = 'benchmark,score\nTOTAL_SCORE,95.2\n';

       mockWorker.postMessage = vi.fn().mockImplementation((req: any) => {
         if (req.type === 'GET_BENCHMARK_SCORE_CSV') {
           mockWorker.onmessage({
             data: {
               type: 'GET_BENCHMARK_SCORE_CSV_DONE',
               id: req.id,
               result: expectedCsv,
             },
           });
         }
       });

       const csv = await client.getBenchmarkScoreCsv('/results/run1');
       expect(csv).toBe(expectedCsv);
     });

  it('throws error in exportResultsZip when response is invalid', async () => {
    const mockWorker = {
      postMessage: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      onmessage: null as any,
    };
    const client = new PyodideWorkerClient(mockWorker as any, vi.fn());

    mockWorker.postMessage = vi.fn().mockImplementation((req: any) => {
      if (req.type === 'EXPORT_RESULTS_ZIP') {
        mockWorker.onmessage({
          data: {
            type: 'EXPORT_RESULTS_ZIP_DONE',
            id: req.id,
            result: 'invalid-string',
          },
        });
      }
    });

    await expect(client.exportResultsZip('/results/run1'))
        .rejects.toThrow('Invalid exportResultsZip response');
  });

  it('supports init(), mountFiles(), runScript(), runBenchmark() typed proxy' +
         ' methods',
     async () => {
       const mockWorker = {
         postMessage: vi.fn(),
         addEventListener: vi.fn(),
         removeEventListener: vi.fn(),
         onmessage: null as any,
       };
       const client = new PyodideWorkerClient(mockWorker as any, vi.fn());

       mockWorker.postMessage = vi.fn().mockImplementation((req: any) => {
         if (req.type === 'INIT') {
           mockWorker.onmessage({data: {type: 'INIT_DONE', id: req.id}});
         } else if (req.type === 'MOUNT_FILES') {
           mockWorker.onmessage({data: {type: 'MOUNT_DONE', id: req.id}});
         } else if (req.type === 'RUN_SCRIPT') {
           mockWorker.onmessage({
             data: {type: 'SCRIPT_DONE', id: req.id, result: 42},
           });
         } else if (req.type === 'RUN_BENCHMARK') {
           mockWorker.onmessage({
             data: {type: 'BENCHMARK_DONE', id: req.id, result: 'SUCCESS'},
           });
         }
       });

       await client.init();
       expect(mockWorker.postMessage)
           .toHaveBeenCalledWith(expect.objectContaining({type: 'INIT'}));

       await client.mountFiles({'/a.txt': 'hello'});
       expect(mockWorker.postMessage)
           .toHaveBeenCalledWith(expect.objectContaining({
             type: 'MOUNT_FILES',
             files: {'/a.txt': 'hello'},
           }));

       const scriptRes = await client.runScript('2 + 2');
       expect(scriptRes).toBe(42);

       const benchRes = await client.runBenchmark(['loadline']);
       expect(benchRes).toBe('SUCCESS');
     });
});

describe('SynchronousWorkerAdbBridge', () => {
  it('throws BenchmarkExecutionInterrupted immediately if interrupted',
     async () => {
       const {SynchronousWorkerAdbBridge} =
           await import('../src/pyodide_worker.js');
       const sab = new SharedArrayBuffer(8);
       const interruptBuf = new Uint8Array(sab, 0, 1);
       interruptBuf[0] = 2;

       const bridge = new SynchronousWorkerAdbBridge(
           'webusb-device', undefined, interruptBuf);
       expect(bridge.isInterrupted()).toBe(true);
       expect(() => bridge.shell('ls'))
           .toThrow('BenchmarkExecutionInterrupted');
       // Once consumed, the one-shot signal wire is reset to 0,
       // so isInterrupted becomes false while wasInterrupted remains true
       expect(interruptBuf[0]).toBe(0);
       expect(bridge.isInterrupted()).toBe(false);
       expect(bridge.wasInterrupted()).toBe(true);

       bridge.clearInterrupt();
       expect(bridge.isInterrupted()).toBe(false);
       expect(bridge.wasInterrupted()).toBe(false);
     });

  it('supports atomic stopFlag and permits subsequent teardown RPC calls ' +
         'after signal is consumed',
     async () => {
       const {SynchronousWorkerAdbBridge} =
           await import('../src/pyodide_worker.js');
       const sab = new SharedArrayBuffer(8);
       const interruptBuf = new Uint8Array(sab, 0, 1);
       const stopFlag = new Int32Array(sab, 4, 1);

       const bridge = new SynchronousWorkerAdbBridge(
           'webusb-device', undefined, interruptBuf, stopFlag);

       // Trigger interrupt
       stopFlag[0] = 1;
       interruptBuf[0] = 2;

       expect(bridge.isInterrupted()).toBe(true);

       // First call sees the signal, consumes it, and throws
       expect(() => bridge.shell('active_story_call'))
           .toThrow('BenchmarkExecutionInterrupted');
       expect(interruptBuf[0]).toBe(0);
       expect(bridge.isInterrupted()).toBe(false);

       // Subsequent call (teardown) does not throw
       // BenchmarkExecutionInterrupted because the one-shot signal was already
       // consumed.
       let postedMsg: any = null;
       const originalSelf = (globalThis as any).self;
       (globalThis as any).self = {
         postMessage: (msg: any) => {
           postedMsg = msg;
           const rpcInt32 = new Int32Array(msg.sab);
           const rpcUint8 = new Uint8Array(msg.sab);
           const resp = new TextEncoder().encode('OK');
           rpcUint8.set(resp, 8);
           rpcInt32[1] = resp.length;
           rpcInt32[0] = 1;  // Success
           Atomics.notify(rpcInt32, 0, 1);
         },
       };

       try {
         const out = bridge.shell('am force-stop com.android.chrome');
         expect(new TextDecoder().decode(out)).toBe('OK');
         expect(postedMsg?.method).toBe('shell');
         expect(postedMsg?.args).toEqual(['am force-stop com.android.chrome']);
       } finally {
         (globalThis as any).self = originalSelf;
       }

       // During and after teardown, isInterrupted is false, while
       // wasInterrupted remains true!
       expect(bridge.isInterrupted()).toBe(false);
       expect(bridge.wasInterrupted()).toBe(true);

       bridge.clearInterrupt();
       expect(bridge.isInterrupted()).toBe(false);
       expect(bridge.wasInterrupted()).toBe(false);
       expect(stopFlag[0]).toBe(0);
     });

  it('throws error in push when Pyodide FS getter is not set', async () => {
    const {SynchronousWorkerAdbBridge} =
        await import('../src/pyodide_worker.js');
    const bridge = new SynchronousWorkerAdbBridge('webusb-device');
    expect(() => bridge.push('/test.txt', '/sdcard/test.txt'))
        .toThrow('Pyodide FS getter is not set');
  });

  it('throws error in push when Pyodide FS fails to read file', async () => {
    const {SynchronousWorkerAdbBridge} =
        await import('../src/pyodide_worker.js');
    const bridge = new SynchronousWorkerAdbBridge('webusb-device');
    bridge.setFs(() => ({
                   readFile: () => {
                     throw new Error('File not found in FS');
                   },
                 }));
    expect(() => bridge.push('/nonexistent.txt', '/sdcard/test.txt'))
        .toThrow('File not found in FS');
  });

  it('throws error in pull when Pyodide FS getter is not set', async () => {
    const {SynchronousWorkerAdbBridge} =
        await import('../src/pyodide_worker.js');
    const bridge = new SynchronousWorkerAdbBridge('webusb-device');
    expect(() => bridge.pull('/sdcard/test.txt', '/test.txt'))
        .toThrow('Pyodide FS getter is not set');
  });

  it('throws error in gcsDownloadFile when Pyodide FS getter is not set',
     async () => {
       const {SynchronousWorkerAdbBridge} =
           await import('../src/pyodide_worker.js');
       const bridge = new SynchronousWorkerAdbBridge('webusb-device');
       expect(() => bridge.gcsDownloadFile('gs://bucket/file', '/dest.txt'))
           .toThrow('Pyodide FS getter is not set');
     });

  it('throws error in spawnProcess when PID is NaN', async () => {
    const {SynchronousWorkerAdbBridge} =
        await import('../src/pyodide_worker.js');
    const bridge = new SynchronousWorkerAdbBridge('webusb-device');
    (bridge as any).callSyncRpc = vi.fn().mockReturnValue('invalid-pid');
    expect(() => bridge.spawnProcess('ls'))
        .toThrow('Failed to parse process PID');
  });
});

describe('Hjson parser fast fail', () => {
  it('throws error in parseHjson when syntax is invalid', async () => {
    const {initHjsonParser} = await import('../src/pyodide_bootstrap.js');
    await initHjsonParser();
    expect(() => (globalThis as any).parseHjson('{"unclosed: ')).toThrow();
  });
});
