// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

/**
 * Pyodide Python environment shims, module mocks, and bootstrap scripts.
 */

// @ts-ignore
import hjsonBundle from '../../../third_party/hjson_js/bundle/hjson.js?raw';

/**
 * Initializes the Hjson parser in the global scope if not already present.
 */
export async function initHjsonParser(): Promise<void> {
  const isNode = typeof process !== 'undefined' && process.versions != null &&
      process.versions.node != null;

  if (typeof (globalThis as any).Hjson === 'undefined') {
    let bundleCode = typeof hjsonBundle === 'string' ? hjsonBundle : '';
    if (!bundleCode && isNode) {
      const fsMod = await import('node:fs');
      const pathMod = await import('node:path');
      const {fileURLToPath} = await import('node:url');
      const currentDir = pathMod.dirname(fileURLToPath(import.meta.url));
      const candidate = pathMod.resolve(
          currentDir, '../../../third_party/hjson_js/bundle/hjson.js');
      if (fsMod.existsSync(candidate)) {
        bundleCode = fsMod.readFileSync(candidate, 'utf-8');
      }
    }
    if (bundleCode) {
      const moduleObj = {exports: {}};
      const fn = new Function(
          'module', 'exports', 'window', 'global', 'self', 'globalThis',
          `
        ${bundleCode};
        return (module.exports && module.exports.parse) ? module.exports : ` +
              `(globalThis.Hjson || self.Hjson || global.Hjson);
      `);
      (globalThis as any).Hjson =
          fn(moduleObj, moduleObj.exports, globalThis, globalThis, globalThis,
             globalThis);
    }
  }

  (globalThis as any).parseHjson = (text: string) => {
    const hjsonParser = (globalThis as any).Hjson;
    if (!hjsonParser || typeof hjsonParser.parse !== 'function') {
      throw new Error('Hjson parser is not available');
    }
    const res = hjsonParser.parse(text);
    return JSON.stringify(res);
  };
}

/**
 * Python bootstrap script executed during Pyodide initialization.
 * Defines module mocks for unavailable C-extensions or heavy libraries,
 * and sets up trace processor resolver shims and interruptible sleep.
 */
export const PYTHON_BOOTSTRAP_SCRIPT = `
import gzip
import json
import logging
import os
import sys
import time
from importlib.abc import MetaPathFinder, Loader
from importlib.machinery import ModuleSpec
from types import ModuleType

import js
import pandas as pd

sys.path.insert(0, "/")
sys.path.insert(0, "/third_party/protoc/gen")

try:
    from google.protobuf import runtime_version
    runtime_version.ValidateProtobufRuntimeVersion = (
        lambda *args, **kwargs: None
    )
except (ImportError, AttributeError):
    pass

# Heavy native dependencies, system monitoring tools, and network libraries
# (such as psutil, requests, selenium, mobly) are unavailable in Pyodide.
# DummyFinder intercepts imports for these packages and returns recursive dummy
# objects to satisfy module imports without breaking benchmark runs.
DUMMY_ROOTS = (
    "autotest_lib",
    "colorama",
    "common",
    "googleapiclient",
    "mcp",
    "mobly",
    "platformdirs",
    "psutil",
    "pyfakefs",
    "pygments",
    "requests",
    "selenium",
    "snippet_uiautomator",
    "sqlalchemy",
    "uinput",
    "urllib3",
    "websocket",
    "websockets",
    "yaml",
)

class DummyMeta(type):
    def __getattr__(cls, name):
        subcls = DummyMeta(
            name,
            (UniversalDummy,),
            {"__module__": cls.__name__, "__name__": name},
        )
        setattr(cls, name, subcls)
        mod_name = f"{cls.__name__}.{name}"
        is_non_pb_google = (
            mod_name.split(".")[0] == "google"
            and not mod_name.startswith("google.protobuf")
        )
        if mod_name.split(".")[0] in DUMMY_ROOTS or is_non_pb_google:
            sys.modules[mod_name] = subcls
        return subcls
    def __getitem__(cls, item):
        return cls
    def __setitem__(cls, key, value):
        pass
    def __contains__(cls, item):
        return True
    def __iter__(cls):
        return iter([])
    def __len__(cls):
        return 0
    def __bool__(cls):
        return True
    def __enter__(cls):
        return cls
    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

class UniversalDummy(object, metaclass=DummyMeta):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.__path__ = []
        self.__file__ = "/dummy.py"
    def __getattr__(self, name):
        return self
    def __getitem__(self, item):
        return self
    def __setitem__(self, key, value):
        pass
    def __contains__(self, item):
        return True
    def __len__(self):
        return 0
    def __bool__(self):
        return True
    def __int__(self):
        return 0
    def __float__(self):
        return 0.0
    def __str__(self):
        return ""
    def __repr__(self):
        return "<UniversalDummy>"
    def __call__(self, *args, **kwargs):
        return self
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        return False
    def __iter__(self):
        return iter([])
    def __mro_entries__(self, bases):
        return (UniversalDummy,)

class DummyFinder(MetaPathFinder, Loader):
    def find_spec(self, fullname, path=None, target=None):
        is_pb = (
            fullname == "google.protobuf"
            or fullname.startswith("google.protobuf.")
        )
        if is_pb:
            return None
        root = fullname.split(".")[0]
        if root in (
            "scipy", "numpy", "pandas", "perfetto", "protoc", "immutabledict"
        ):
            return None
        if root in DUMMY_ROOTS or (root == "google" and not is_pb):
            return ModuleSpec(fullname, self, is_package=True)
        return None
    def create_module(self, spec):
        mod = DummyMeta(
            spec.name,
            (UniversalDummy,),
            {"__module__": spec.name, "__name__": spec.name},
        )
        sys.modules[spec.name] = mod
        return mod
    def exec_module(self, module):
        pass

sys.meta_path.append(DummyFinder())

# immutabledict is not packaged in the Pyodide WebAssembly distribution.
# This shim provides a minimal dictionary subclass implementing a dummy hash
# method to satisfy type and hashability checks.
class immutabledict(dict):
    def __hash__(self):
        return 0
im_mod = ModuleType("immutabledict")
im_mod.immutabledict = immutabledict
sys.modules["immutabledict"] = im_mod

# xlsxwriter is installed via micropip, which may fail in offline or sandboxed
# environments. When missing, this fallback provides a stub Workbook class so
# benchmarks that optionally export Excel spreadsheets can complete.
try:
    import xlsxwriter
except ImportError:
    class _DummyWorkbook:
        def __init__(self, *args, **kwargs):
            pass
        def add_worksheet(self, *args, **kwargs):
            return self
        def write(self, *args, **kwargs):
            pass
        def close(self):
            pass
    xlsx_mod = ModuleType("xlsxwriter")
    xlsx_mod.Workbook = _DummyWorkbook
    xlsx_util_mod = ModuleType("xlsxwriter.utility")
    xlsx_util_mod.xl_rowcol_to_cell = (
        lambda row, col, *args, **kwargs: f"A{row+1}"
    )
    xlsx_mod.utility = xlsx_util_mod
    sys.modules["xlsxwriter"] = xlsx_mod
    sys.modules["xlsxwriter.utility"] = xlsx_util_mod

_orig_json_default = json.JSONEncoder.default
def _dummy_json_default(self, o):
    if isinstance(o, (DummyMeta, UniversalDummy)):
        return str(o)
    return _orig_json_default(self, o)
json.JSONEncoder.default = _dummy_json_default

# The hjson C-extension package is not available in Pyodide.
# This shim bridges loads/load to the bundled JavaScript Hjson parser
# and deserializes the resulting JSON string into Python objects.
hjson_mod = ModuleType("hjson")

def hjson_loads(s, object_pairs_hook=None, **kwargs):
    return json.loads(js.parseHjson(s), object_pairs_hook=object_pairs_hook)

def hjson_load(fp, object_pairs_hook=None, **kwargs):
    return hjson_loads(
        fp.read(), object_pairs_hook=object_pairs_hook, **kwargs
    )

hjson_mod.loads = hjson_loads
hjson_mod.load = hjson_load
sys.modules["hjson"] = hjson_mod

# ordered_set is not packaged in Pyodide.
# This shim provides a list-backed OrderedSet implementation that maintains
# insertion order and prevents duplicate entries.
class OrderedSet(list):
    def add(self, i):
        if i not in self:
            self.append(i)
    def discard(self, i):
        if i in self:
            self.remove(i)
    def update(self, iterable):
        for i in iterable:
            self.add(i)

os_mod = ModuleType("ordered_set")
os_mod.OrderedSet = OrderedSet
sys.modules["ordered_set"] = os_mod

# The native perfetto Python SDK relies on trace_processor_shell and a local
# RPC daemon, which cannot run in browser WebAssembly.
# This shim implements TraceProcessor and BatchTraceProcessor backed by our
# in-browser WebAssembly Trace Processor engine.
perfetto_mod = ModuleType("perfetto")
tp_mod = ModuleType("perfetto.trace_processor")
tp_api_mod = ModuleType("perfetto.trace_processor.api")
resolver_mod = ModuleType("perfetto.trace_uri_resolver")
resolver_res_mod = ModuleType("perfetto.trace_uri_resolver.resolver")
resolver_path_mod = ModuleType("perfetto.trace_uri_resolver.path")
resolver_reg_mod = ModuleType("perfetto.trace_uri_resolver.registry")
btp_mod = ModuleType("perfetto.batch_trace_processor")
btp_api_mod = ModuleType("perfetto.batch_trace_processor.api")

class TraceUriResolver:
    class Result:
        def __init__(self, trace, metadata=None):
            self.trace = trace
            self.metadata = metadata or {}
        @property
        def generator(self):
            return self._gen()
        def _gen(self):
            if isinstance(self.trace, (bytes, bytearray, memoryview)):
                yield bytes(self.trace)
            elif hasattr(self.trace, "read"):
                while True:
                    chunk = self.trace.read(2 * 1024 * 1024)
                    if not chunk:
                        break
                    yield chunk
            else:
                path_str = str(self.trace)
                if path_str in ("/dev/null", "dev/null"):
                    yield b""
                elif not os.path.exists(path_str):
                    raise FileNotFoundError(
                        f"Trace file not found: {path_str}"
                    )
                else:
                    opener = gzip.open if path_str.endswith(".gz") else open
                    with opener(path_str, "rb") as f:
                        while chunk := f.read(2 * 1024 * 1024):
                            yield chunk

class PathUriResolver(TraceUriResolver):
    pass

class ResolverRegistry:
    def __init__(self, resolvers=None):
        self.resolvers = list(resolvers or [])
    def resolve(self, trace):
        if hasattr(trace, "resolve"):
            return trace.resolve()
        return [TraceUriResolver.Result(trace)]

resolver_res_mod.TraceUriResolver = TraceUriResolver
resolver_path_mod.PathUriResolver = PathUriResolver
resolver_reg_mod.ResolverRegistry = ResolverRegistry
resolver_mod.TraceUriResolver = TraceUriResolver
resolver_mod.PathUriResolver = PathUriResolver
resolver_mod.ResolverRegistry = ResolverRegistry

class TraceProcessorConfig:
    def __init__(self, bin_path=None, unique_port=False, verbose=False,
                 ingest_ftrace_in_raw=True, enable_dev_features=True,
                 resolver_registry=None, load_timeout=10, extra_flags=None,
                 add_sql_packages=None, **kwargs):
        self.bin_path = bin_path
        self.resolver_registry = resolver_registry
        self.extra_flags = extra_flags or []
        self.add_sql_packages = add_sql_packages or []

class QueryResultIterator:
    def __init__(self, cols, rows, metadata=None):
        self.column_names = list(cols)
        self.rows = list(rows)
        self.row_count = len(self.rows)
        self.column_count = len(self.column_names)
        self.metadata = metadata or {}
        self._idx = 0

    def as_pandas_dataframe(self):
        if self.row_count == 0:
            df = pd.DataFrame(columns=self.column_names)
        else:
            df = pd.DataFrame(self.rows, columns=self.column_names)
        if self.metadata and isinstance(self.metadata, dict):
            for k, v in self.metadata.items():
                if k not in df.columns:
                    df[k] = v
        return df

    def __len__(self):
        return self.row_count

    def __iter__(self):
        self._idx = 0
        return self

    def __next__(self):
        if self._idx >= self.row_count:
            raise StopIteration
        row_vals = self.rows[self._idx]
        self._idx += 1
        class Row:
            pass
        r = Row()
        for col_name, val in zip(self.column_names, row_vals):
            setattr(r, col_name, val)
        return r

class TraceProcessor:
    QueryResultIterator = QueryResultIterator

    def __init__(self, trace=None, config=None, addr=None, file_path=None):
        self.config = config or TraceProcessorConfig()
        self.resolver_registry = (
            self.config.resolver_registry or ResolverRegistry()
        )
        self._metadata = {}

        js.tp_reset()

        target_trace = trace if trace is not None else file_path
        if target_trace is not None:
            self._parse_trace(target_trace)
        else:
            js.tp_finalize()
            self._register_sql_packages()

    def _register_sql_packages(self):
        packages_to_register = [
            "/crossbench/probes/trace_processor/modules/ext"
        ]
        if self.config.extra_flags:
            flags = list(self.config.extra_flags)
            for idx, flag in enumerate(flags):
                if flag == "--add-sql-package" and idx + 1 < len(flags):
                    packages_to_register.append(flags[idx + 1])
                elif flag.startswith("--add-sql-package="):
                    packages_to_register.append(flag.split("=", 1)[1])
        if self.config.add_sql_packages:
            packages_to_register.extend(self.config.add_sql_packages)

        registered = set()
        for pkg_path in packages_to_register:
            pkg_path = os.path.abspath(str(pkg_path))
            if pkg_path in registered:
                continue
            registered.add(pkg_path)
            if os.path.isdir(pkg_path):
                pkg_name = os.path.basename(os.path.normpath(pkg_path))
                modules = []
                for root, _, files in os.walk(pkg_path):
                    for fname in files:
                        if fname.endswith(".sql"):
                            full_file_path = os.path.join(root, fname)
                            rel_path = os.path.relpath(
                                full_file_path, pkg_path
                            )
                            mod_rel = rel_path[:-4].replace(
                                os.path.sep, "."
                            )
                            with open(
                                full_file_path, "r", encoding="utf-8"
                            ) as f:
                                modules.append(
                                    {"name": mod_rel, "sql": f.read()}
                                )
                if modules and hasattr(js, "tp_register_sql_package"):
                    js.tp_register_sql_package(pkg_name, modules)

    def _parse_trace(self, trace):
        resolved_lst = []
        if hasattr(trace, "resolve"):
            resolved_lst = trace.resolve()
        elif self.resolver_registry:
            resolved_lst = self.resolver_registry.resolve(trace)
        if not resolved_lst:
            resolved_lst = [TraceUriResolver.Result(trace)]

        for res in resolved_lst:
            self._metadata = getattr(res, "metadata", {}) or {}
            for chunk in res.generator:
                js.tp_parse(chunk)
        js.tp_finalize()
        self._register_sql_packages()

    def query(self, sql):
        self._register_sql_packages()
        res_str = js.tp_query(sql)
        res_data = json.loads(res_str)
        if "error" in res_data and res_data["error"]:
            raise Exception(
                f"TraceProcessor query error: {res_data['error']}"
            )
        return QueryResultIterator(
            res_data.get("columns", []),
            res_data.get("rows", []),
            metadata=self._metadata,
        )

    def _trace_summary_msg(self):
        from protos.perfetto.trace_summary.file_pb2 import TraceSummary
        return TraceSummary()

    def metric(self, metrics):
        return self._trace_summary_msg()

    def trace_summary(
        self, specs=None, metric_ids=None, metadata_query_id=None
    ):
        return self._trace_summary_msg()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        pass

class BatchTraceProcessorConfig(TraceProcessorConfig):
    pass

class BatchTraceProcessor:
    def __init__(self, traces=None, config=None):
        self.traces = traces or []
        self.config = config or BatchTraceProcessorConfig()
    def query(self, sql):
        return QueryResultIterator([], [])
    def query_and_flatten(self, sql):
        return pd.DataFrame()
    def metric(self, metrics):
        return []
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def close(self):
        pass

tp_api_mod.TraceProcessor = TraceProcessor
tp_api_mod.TraceProcessorConfig = TraceProcessorConfig
tp_api_mod.QueryResultIterator = QueryResultIterator
tp_api_mod.TraceProcessorException = Exception

tp_mod.TraceProcessor = TraceProcessor
tp_mod.TraceProcessorConfig = TraceProcessorConfig
tp_mod.QueryResultIterator = QueryResultIterator
tp_mod.TraceProcessorException = Exception

perfetto_mod.TraceProcessor = TraceProcessor
perfetto_mod.TraceProcessorConfig = TraceProcessorConfig

btp_api_mod.BatchTraceProcessor = BatchTraceProcessor
btp_api_mod.BatchTraceProcessorConfig = BatchTraceProcessorConfig
btp_mod.BatchTraceProcessor = BatchTraceProcessor
btp_mod.BatchTraceProcessorConfig = BatchTraceProcessorConfig

sys.modules["perfetto"] = perfetto_mod
perfetto_mod.trace_processor = tp_mod
perfetto_mod.trace_processor.api = tp_api_mod
perfetto_mod.trace_uri_resolver = resolver_mod
perfetto_mod.trace_uri_resolver.resolver = resolver_res_mod
perfetto_mod.trace_uri_resolver.path = resolver_path_mod
perfetto_mod.trace_uri_resolver.registry = resolver_reg_mod
perfetto_mod.batch_trace_processor = btp_mod
perfetto_mod.batch_trace_processor.api = btp_api_mod

sys.modules["perfetto.trace_processor"] = tp_mod
sys.modules["perfetto.trace_processor.api"] = tp_api_mod
sys.modules["perfetto.trace_uri_resolver"] = resolver_mod
sys.modules["perfetto.trace_uri_resolver.resolver"] = resolver_res_mod
sys.modules["perfetto.trace_uri_resolver.path"] = resolver_path_mod
sys.modules["perfetto.trace_uri_resolver.registry"] = resolver_reg_mod
sys.modules["perfetto.batch_trace_processor"] = btp_mod
sys.modules["perfetto.batch_trace_processor.api"] = btp_api_mod

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    stream=sys.stdout,
    force=True,
)

_orig_time_sleep = time.sleep
def _check_interrupted():
    webadb = getattr(js, "webadb", None)
    if hasattr(webadb, "isInterrupted") and webadb.isInterrupted():
        if hasattr(webadb, "acknowledgeInterrupt"):
            webadb.acknowledgeInterrupt()
        raise KeyboardInterrupt("Benchmark execution interrupted by user")

def _pyodide_interruptible_sleep(secs):
    _check_interrupted()
    start = time.time()
    while time.time() - start < secs:
        _check_interrupted()
        step = min(0.05, secs - (time.time() - start))
        if step <= 0:
            break
        _orig_time_sleep(step)
time.sleep = _pyodide_interruptible_sleep
`;
