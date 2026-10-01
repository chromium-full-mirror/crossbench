// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as fs from 'node:fs';
import * as path from 'node:path';
import {describe, expect, it, vi} from 'vitest';

import {PyodideRunner, WebAdbProxy} from '../src/pyodide_worker';

function getCrossbenchFilesFromDisk(): Record<string, string> {
  const repoRoot = path.resolve(__dirname, '../../..');
  const files: Record<string, string> = {};

  function scanDir(dirPath: string, prefix: string) {
    if (!fs.existsSync(dirPath))
      return;
    const entries = fs.readdirSync(dirPath, {withFileTypes: true});
    for (const entry of entries) {
      const fullPath = path.join(dirPath, entry.name);
      if (entry.isDirectory()) {
        if (entry.name !== '__pycache__' && entry.name !== 'node_modules' &&
            entry.name !== 'dist') {
          scanDir(fullPath, prefix);
        }
      } else {
        const relPath = path.relative(path.join(repoRoot, prefix), fullPath);
        const fsPath = '/' + prefix + '/' + relPath.split(path.sep).join('/');
        files[fsPath] = fs.readFileSync(fullPath, 'utf8');
      }
    }
  }

  scanDir(path.join(repoRoot, 'crossbench'), 'crossbench');
  scanDir(path.join(repoRoot, 'config'), 'config');
  scanDir(path.join(repoRoot, 'third_party/protoc'), 'third_party/protoc');
  scanDir(path.join(repoRoot, 'tools/protoc'), 'tools/protoc');
  return files;
}

describe('Pyodide Integration Test (Real WebAssembly)', () => {
  it('loads real Pyodide, mounts crossbench, runs loading story, ' +
         'and tests TraceProcessor probe',
     async () => {
       const mockWebAdb: WebAdbProxy = {
         serial: 'mock-usb-device',
         shell: vi.fn().mockImplementation((cmd: string) => {
           if (cmd.includes('getprop ro.build.version.release')) {
             return '14\n';
           }
           if (cmd.includes('getprop ro.build.version.sdk'))
             return '34\n';
           if (cmd.includes('getprop ro.product.model'))
             return 'Pixel 8\n';
           if (cmd.includes('getprop ro.product.cpu.abi')) {
             return 'arm64-v8a\n';
           }
           if (cmd.includes('getprop')) {
             return '[ro.build.version.release]: [14]\n';
           }
           if (cmd.includes('get-current-user'))
             return '0\n';
           if (cmd.includes('list users')) {
             return 'UserInfo{0:null:4c13} running\n';
           }
           if (cmd.includes('list packages')) {
             return (
                 'package:com.android.chrome\n' +
                 'package:com.google.android.apps.chrome\n');
           }
           if (cmd.includes('dumpsys package')) {
             return 'versionName=120.0.6099.144\n';
           }
           if (cmd.includes('dumpsys window displays --proto')) {
             const repoRoot = path.resolve(__dirname, '../../..');
             const fileBuf = fs.readFileSync(path.join(
                 repoRoot, 'tests/crossbench/plt/pb/display/1080p.pb'));
             return new Uint8Array(
                 fileBuf.buffer, fileBuf.byteOffset, fileBuf.byteLength);
           }
           if (cmd.includes('dumpsys window')) {
             return 'mAppBounds=Rect(0, 0 - 1080, 2400)\n';
           }
           if (cmd.includes('dumpsys power')) {
             return 'mHoldingDisplaySuspendBlocker=true\n';
           }
           if (cmd.includes('dumpsys battery')) {
             return 'level: 100\ntemperature: 250\n';
           }
           if (cmd.includes('uname -m'))
             return 'aarch64\n';
           if (cmd.includes('cat') && cmd.includes('chrome-command-line')) {
             return '';
           }
           if (cmd.includes('am set-debug-app'))
             return 'Success\n';
           if (cmd.includes('am start')) {
             return (
                 'Starting: Intent { act=android.intent.action.VIEW ' +
                 'dat=about:blank pkg=com.android.chrome }\n');
           }
           if (cmd.includes('pm clear') || cmd.includes('am stop-app') ||
               cmd.includes('am force-stop')) {
             return 'Success\n';
           }
           return '';
         }),
         push: vi.fn(),
         pull: vi.fn(),
         startDevTools: vi.fn().mockReturnValue('devtools-socket-1234'),
         stopDevTools: vi.fn().mockReturnValue('ok'),
         switchTab: vi.fn().mockReturnValue(
             'ws://localhost:9222/devtools/page/tab123'),
         sendCdpCommand: vi.fn().mockImplementation((method: string) => {
           if (method === 'Target.getTargets') {
             return JSON.stringify({
               targetInfos: [
                 {
                   targetId: 'tab123',
                   type: 'page',
                   title: 'Mock Page',
                   url: 'about:blank',
                   webSocketDebuggerUrl:
                       'ws://localhost:9222/devtools/page/tab123',
                 },
               ],
             });
           }
           if (method === 'Page.navigate') {
             return JSON.stringify({frameId: 'frame123'});
           }
           if (method === 'Runtime.evaluate') {
             return JSON.stringify({result: {type: 'boolean', value: true}});
           }
           return JSON.stringify({});
         }),
       };

       const logs: string[] = [];
       const runner = new PyodideRunner(mockWebAdb, (msg) => {
         logs.push(msg);
       });
       await runner.init();

       const pyFiles = getCrossbenchFilesFromDisk();
       expect(Object.keys(pyFiles).length).toBeGreaterThan(400);

       await runner.mountFiles(pyFiles);

       // Test running Crossbench CLI describe subcommand
       await runner.runCrossbench(['describe', 'loadline2-phone']);
       expect(logs.some((l) => l.includes('loadline2-phone'))).toBe(true);

       // Test running Crossbench loading benchmark with cdp:chrome
       await runner.runCrossbench([
         'loading',
         '--browser',
         'cdp:chrome',
         '--url',
         'https://www.google.com',
         '--env-validation=warn',
         '--fast',
         '--throw',
       ]);
       expect(mockWebAdb.shell).toHaveBeenCalled();
       expect(mockWebAdb.startDevTools).toHaveBeenCalled();
       expect(mockWebAdb.sendCdpCommand).toHaveBeenCalled();

       // Test Perfetto probe trace config serialization with real protobuf
       const perfettoTestScript = `
import google.protobuf.text_format as proto_text_format
from crossbench import path as pth
from crossbench.probes.cb_perfetto.perfetto import TraceConfig

cfg = TraceConfig.parse_path(
    pth.LocalPath('/config/probe/perfetto/trace_config/default.txtpb')
)
text = proto_text_format.MessageToString(cfg.trace_config)
assert isinstance(text, str) and len(text) > 0, (
    f"Expected str trace config, got {type(text)}"
)
"OK"
`;
       const perfettoRes = await runner.runScript(perfettoTestScript);
       expect(perfettoRes).toBe('OK');

       // Test Perfetto TraceProcessor in Pyodide with real pandas, numpy, scipy
       const tpTestScript = `
import pandas as pd
import numpy as np
import scipy.stats
from perfetto.trace_processor.api import TraceProcessor

tp = TraceProcessor()
sql = (
    "SELECT 'amazon_product_visual' AS metric, 100.0 AS value, "
    "'browser_1' AS cb_browser, 0 AS cb_run UNION ALL "
    "SELECT 'amazon_product_interactive' AS metric, 200.0 AS value, "
    "'browser_1' AS cb_browser, 0 AS cb_run"
)
df = tp.query(sql).as_pandas_dataframe()
assert isinstance(df, pd.DataFrame), f"Expected DataFrame, got {type(df)}"
assert len(df) == 2, f"Expected 2 rows, got {len(df)}"
assert list(df['metric']) == [
    'amazon_product_visual',
    'amazon_product_interactive',
]

# Test including ext.loadline2_score SQL module registered via
# TPM_REGISTER_SQL_PACKAGE
ext_sql = (
    "INCLUDE PERFETTO MODULE ext.loadline2_score; "
    "SELECT * FROM loadline2_score;"
)
ext_df = tp.query(ext_sql).as_pandas_dataframe()
assert isinstance(ext_df, pd.DataFrame)
assert list(ext_df.columns) == ['metric', 'value']

# Test TraceProcessor with trace parsing then query
tp_with_trace = TraceProcessor(trace="/dev/null")
trace_df = tp_with_trace.query(ext_sql).as_pandas_dataframe()
assert isinstance(trace_df, pd.DataFrame)

# Test non-existent trace raises FileNotFoundError
try:
    TraceProcessor(trace="/nonexistent_trace.perfetto-trace")
    assert False, "Expected FileNotFoundError for non-existent trace"
except FileNotFoundError:
    pass

# Test trace_summary and metric serialization
summary = tp.trace_summary()
assert hasattr(summary, "SerializeToString")
assert isinstance(summary.SerializeToString(), bytes)

from google.protobuf.json_format import MessageToJson
m = tp.metric(["trace_metadata"])
assert isinstance(MessageToJson(m), str)

# Test LoadLine 2 score processing with real scipy.stats
from crossbench.benchmarks.loadline.loadline_2 import process_scores
scores_df = process_scores(df, expected_metrics=2)
assert isinstance(scores_df, pd.DataFrame)
assert not scores_df.empty

# Test tabulate on scores DataFrame
from tabulate import tabulate
tab_str = tabulate(scores_df.reset_index(), headers="keys", tablefmt="plain")
assert "Metric" in tab_str
assert "TOTAL_SCORE" in tab_str
assert "browser_1" in tab_str
"OK"
`;
       const tpRes = await runner.runScript(tpTestScript);
       expect(tpRes).toBe('OK');

       // Test exporting results zip
       const zipBytes = await runner.exportResultsZip();
       expect(zipBytes).toBeInstanceOf(Uint8Array);
       expect(zipBytes.length).toBeGreaterThan(0);
       // Standard zip magic number is PK\x03\x04 (0x50, 0x4b, 0x03, 0x04)
       expect(zipBytes[0]).toBe(0x50);
       expect(zipBytes[1]).toBe(0x4b);
     },
     60000);
});
