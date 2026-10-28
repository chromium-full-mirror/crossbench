-- Copyright 2026 The Chromium Authors
-- Use of this source code is governed by a BSD-style license that can be
-- found in the LICENSE file.

-- Single-row post-destroy WebView browser and renderer heapdump memory metrics
-- (android.heapprofd native allocations + android.java_hprof Java heap graphs).
-- Every column is a stable scalar metric ending in _bytes or _count.

INCLUDE PERFETTO MODULE callstacks.stack_profile;

WITH
  profiled_upids AS (
    SELECT DISTINCT upid FROM heap_profile_allocation
    UNION
    SELECT DISTINCT upid FROM heap_graph_object
  ),
  java_final_ts AS MATERIALIZED (
    SELECT
      upid,
      MAX(graph_sample_ts) AS final_ts
    FROM heap_graph_object
    GROUP BY upid
  ),
  java_role_hints AS MATERIALIZED (
    SELECT
      o.upid,
      MAX(
        CASE
          WHEN
            c.name GLOB 'org.chromium.webview_shell.*'
            OR COALESCE(c.deobfuscated_name, c.name) GLOB '*AwContents*'
            OR COALESCE(c.deobfuscated_name, c.name) GLOB '*WebViewChromium*'
            THEN 1
          ELSE 0
        END) AS has_browser_java,
      MAX(
        CASE
          WHEN
            COALESCE(c.deobfuscated_name, c.name) GLOB '*SandboxedProcess*'
            OR COALESCE(c.deobfuscated_name, c.name) GLOB '*ChildProcessService*'
            THEN 1
          ELSE 0
        END) AS has_renderer_java
    FROM heap_graph_object o
    JOIN java_final_ts jft
      ON o.upid = jft.upid AND o.graph_sample_ts = jft.final_ts
    JOIN heap_graph_class c
      ON o.type_id = c.id
    WHERE NOT (c.name GLOB 'java.lang.Class<*>')
    GROUP BY o.upid
  ),
  first_seen AS (
    SELECT
      upid,
      MIN(ts) AS first_ts
    FROM (
      SELECT upid, MIN(ts) AS ts FROM heap_profile_allocation GROUP BY upid
      UNION ALL
      SELECT upid, MIN(graph_sample_ts) AS ts FROM heap_graph_object GROUP BY upid
    )
    GROUP BY upid
  ),
  classified_processes AS (
    SELECT
      pu.upid,
      ROW_NUMBER() OVER (ORDER BY fs.first_ts ASC, p.pid ASC, pu.upid ASC) AS spawn_order,
      CASE
        -- Tier 1: Explicit process name / cmdline from linux.process_stats
        WHEN
          p.name GLOB '*sandboxed_process*'
          OR p.cmdline GLOB '*sandboxed_process*'
          OR p.name GLOB '*SandboxedProcessService*'
          OR p.cmdline GLOB '*SandboxedProcessService*'
          THEN 'renderer'
        WHEN
          p.name GLOB '*webview_shell*'
          OR p.cmdline GLOB '*webview_shell*'
          THEN 'browser'
        -- Tier 2: Android isolated process UID range or Java heap class hints
        WHEN (p.uid % 100000) >= 90000 THEN 'renderer'
        WHEN
          COALESCE(jh.has_renderer_java, 0) = 1
          AND COALESCE(jh.has_browser_java, 0) = 0
          THEN 'renderer'
        WHEN COALESCE(jh.has_browser_java, 0) = 1 THEN 'browser'
        ELSE NULL
      END AS inferred_role
    FROM profiled_upids pu
    LEFT JOIN process p
      ON pu.upid = p.upid
    LEFT JOIN java_role_hints jh
      ON pu.upid = jh.upid
    LEFT JOIN first_seen fs
      ON pu.upid = fs.upid
  ),
  process_roles AS MATERIALIZED (
    SELECT
      upid,
      COALESCE(
        inferred_role,
        -- Tier 3: Spawn order fallback (browser shell starts before renderer)
        IIF(spawn_order = 1, 'browser', 'renderer')
      ) AS process_role
    FROM classified_processes
  ),
  -- Native heap (android.heapprofd): Perfetto stores delta sizes/counts per dump ts.
  -- Summing across all ts <= MAX(ts) yields cumulative unreleased allocations at the final
  -- (post-destroy) dump; summing at MIN(ts) yields the initial (post-startup) baseline.
  heapprofd_bounds AS (
    SELECT
      upid,
      heap_name,
      MIN(ts) AS startup_ts
    FROM heap_profile_allocation
    GROUP BY upid, heap_name
  ),
  startup_callsites AS (
    SELECT
      a.upid,
      a.heap_name,
      a.callsite_id,
      SUM(a.size) AS startup_bytes
    FROM heap_profile_allocation a
    JOIN heapprofd_bounds b
      ON a.upid = b.upid AND a.heap_name = b.heap_name AND a.ts <= b.startup_ts
    GROUP BY a.upid, a.heap_name, a.callsite_id
    HAVING SUM(a.size) > 0
  ),
  final_callsites AS MATERIALIZED (
    SELECT
      a.upid,
      a.heap_name,
      a.callsite_id,
      SUM(a.size) AS retained_bytes,
      SUM(a.count) AS retained_count
    FROM heap_profile_allocation a
    GROUP BY a.upid, a.heap_name, a.callsite_id
    HAVING SUM(a.size) > 0
  ),
  startup_by_role AS MATERIALIZED (
    SELECT
      pr.process_role,
      SUM(sc.startup_bytes) AS startup_bytes
    FROM startup_callsites sc
    JOIN process_roles pr
      ON sc.upid = pr.upid
    GROUP BY pr.process_role
  ),
  final_by_role AS MATERIALIZED (
    SELECT
      pr.process_role,
      SUM(fc.retained_bytes) AS retained_bytes,
      SUM(fc.retained_count) AS retained_count
    FROM final_callsites fc
    JOIN process_roles pr
      ON fc.upid = pr.upid
    GROUP BY pr.process_role
  ),
  -- Walk symbolized callstack frames from leaf upward to attribute each retained
  -- callsite to the nearest major subsystem (Blink, V8, Skia, Android WebView).
  callsite_frames AS (
    SELECT
      cs.callsite_id,
      f.id,
      f.parent_id,
      f.name,
      f.source_file,
      0 AS depth
    FROM (SELECT DISTINCT callsite_id FROM final_callsites) cs
    JOIN _callstack_spc_forest f
      ON cs.callsite_id = f.callsite_id
      AND f.is_leaf_function_in_callsite_frame = 1
    UNION ALL
    SELECT
      cf.callsite_id,
      p.id,
      p.parent_id,
      p.name,
      p.source_file,
      cf.depth + 1 AS depth
    FROM callsite_frames cf
    JOIN _callstack_spc_forest p
      ON cf.parent_id = p.id
    WHERE cf.depth < 64
  ),
  ranked_subsystem_frames AS (
    SELECT
      callsite_id,
      CASE
        WHEN
          COALESCE(source_file, '') GLOB '*third_party/blink/*'
          OR name GLOB 'blink::*'
          THEN 'blink'
        WHEN
          COALESCE(source_file, '') GLOB '*v8/*'
          OR name GLOB 'v8::*'
          OR name GLOB 'JS:*'
          OR name GLOB 'V8:*'
          OR name GLOB 'WASM:*'
          OR name GLOB 'REGEXP:*'
          THEN 'v8'
        WHEN
          COALESCE(source_file, '') GLOB '*third_party/skia/*'
          OR name GLOB 'skia::*'
          OR name GLOB 'Sk*'
          OR name GLOB 'Gr*'
          OR name GLOB 'skgpu::*'
          THEN 'skia'
        WHEN
          COALESCE(source_file, '') GLOB '*android_webview/*'
          OR name GLOB 'android_webview::*'
          THEN 'android_webview'
        ELSE NULL
      END AS subsystem,
      depth
    FROM callsite_frames
    WHERE
      NOT (name GLOB 'WTF::Partitions::*')
      AND NOT (name GLOB 'WTF::FastMalloc*')
      AND NOT (COALESCE(source_file, '') GLOB '*partition_alloc/*')
      AND NOT (COALESCE(source_file, '') GLOB '*base/allocator/*')
  ),
  callsite_subsystem AS (
    SELECT
      callsite_id,
      subsystem
    FROM (
      SELECT
        callsite_id,
        subsystem,
        ROW_NUMBER() OVER (PARTITION BY callsite_id ORDER BY depth ASC) AS rn
      FROM ranked_subsystem_frames
      WHERE subsystem IS NOT NULL
    )
    WHERE rn = 1
  ),
  native_subsystems AS MATERIALIZED (
    SELECT
      SUM(
        IIF(
          pr.process_role = 'renderer' AND cs.subsystem = 'blink',
          fc.retained_bytes,
          0)) AS renderer_blink_bytes,
      SUM(
        IIF(
          pr.process_role = 'renderer' AND cs.subsystem = 'v8',
          fc.retained_bytes,
          0)) AS renderer_v8_bytes,
      SUM(
        IIF(
          pr.process_role = 'renderer' AND cs.subsystem = 'skia',
          fc.retained_bytes,
          0)) AS renderer_skia_bytes,
      SUM(
        IIF(
          pr.process_role = 'browser' AND cs.subsystem = 'android_webview',
          fc.retained_bytes,
          0)) AS browser_aw_bytes
    FROM final_callsites fc
    JOIN process_roles pr
      ON fc.upid = pr.upid
    LEFT JOIN callsite_subsystem cs
      ON fc.callsite_id = cs.callsite_id
  ),
  -- Java heap (android.java_hprof): inspect the final (post-destroy) snapshot per process.
  java_final_by_role AS MATERIALIZED (
    SELECT
      pr.process_role,
      SUM(o.self_size) AS java_bytes,
      COUNT() AS java_count,
      SUM(o.native_size) AS native_alloc_bytes,
      SUM(
        CASE
          WHEN
            COALESCE(c.deobfuscated_name, c.name) GLOB 'org.chromium.*'
            OR COALESCE(c.deobfuscated_name, c.name) GLOB 'com.android.webview.chromium.*'
            OR COALESCE(c.deobfuscated_name, c.name) GLOB 'WV.*'
            OR COALESCE(c.deobfuscated_name, c.name) = 'J.N'
            OR COALESCE(c.deobfuscated_name, c.name) GLOB 'J.N$*'
            THEN o.self_size
          ELSE 0
        END) AS chromium_bytes,
      SUM(
        CASE
          WHEN
            COALESCE(c.deobfuscated_name, c.name) = 'org.chromium.android_webview.AwContents'
            OR COALESCE(c.deobfuscated_name, c.name) GLOB '*.AwContents'
            THEN 1
          ELSE 0
        END) AS aw_contents_count
    FROM heap_graph_object o
    JOIN java_final_ts jft
      ON o.upid = jft.upid AND o.graph_sample_ts = jft.final_ts
    JOIN heap_graph_class c
      ON o.type_id = c.id
    JOIN process_roles pr
      ON o.upid = pr.upid
    WHERE o.reachable != 0
    GROUP BY pr.process_role
  )
SELECT
  -- Native Heap (android.heapprofd) — Post-Destroy
  CAST(COALESCE((SELECT retained_bytes FROM final_by_role WHERE process_role = 'browser'), 0) AS INTEGER) AS native_retained_browser_bytes,
  CAST(COALESCE((SELECT retained_count FROM final_by_role WHERE process_role = 'browser'), 0) AS INTEGER) AS native_retained_browser_count,
  CAST(
    COALESCE((SELECT retained_bytes FROM final_by_role WHERE process_role = 'browser'), 0)
    - COALESCE((SELECT startup_bytes FROM startup_by_role WHERE process_role = 'browser'), 0)
    AS INTEGER
  ) AS native_post_startup_retained_browser_bytes,
  CAST(COALESCE((SELECT retained_bytes FROM final_by_role WHERE process_role = 'renderer'), 0) AS INTEGER) AS native_retained_renderer_bytes,
  CAST(COALESCE((SELECT retained_count FROM final_by_role WHERE process_role = 'renderer'), 0) AS INTEGER) AS native_retained_renderer_count,
  CAST(
    COALESCE((SELECT retained_bytes FROM final_by_role WHERE process_role = 'renderer'), 0)
    - COALESCE((SELECT startup_bytes FROM startup_by_role WHERE process_role = 'renderer'), 0)
    AS INTEGER
  ) AS native_post_startup_retained_renderer_bytes,
  CAST(COALESCE((SELECT renderer_blink_bytes FROM native_subsystems), 0) AS INTEGER) AS native_retained_renderer_blink_bytes,
  CAST(COALESCE((SELECT renderer_v8_bytes FROM native_subsystems), 0) AS INTEGER) AS native_retained_renderer_v8_bytes,
  CAST(COALESCE((SELECT renderer_skia_bytes FROM native_subsystems), 0) AS INTEGER) AS native_retained_renderer_skia_bytes,
  CAST(COALESCE((SELECT browser_aw_bytes FROM native_subsystems), 0) AS INTEGER) AS native_retained_browser_aw_bytes,
  -- Java Heap (android.java_hprof) — Post-Destroy
  CAST(COALESCE((SELECT java_bytes FROM java_final_by_role WHERE process_role = 'browser'), 0) AS INTEGER) AS java_retained_browser_bytes,
  CAST(COALESCE((SELECT java_count FROM java_final_by_role WHERE process_role = 'browser'), 0) AS INTEGER) AS java_retained_browser_count,
  CAST(COALESCE((SELECT native_alloc_bytes FROM java_final_by_role WHERE process_role = 'browser'), 0) AS INTEGER) AS java_retained_browser_native_alloc_bytes,
  CAST(COALESCE((SELECT chromium_bytes FROM java_final_by_role WHERE process_role = 'browser'), 0) AS INTEGER) AS java_retained_browser_chromium_bytes,
  CAST(COALESCE((SELECT aw_contents_count FROM java_final_by_role WHERE process_role = 'browser'), 0) AS INTEGER) AS java_retained_browser_aw_contents_count,
  CAST(COALESCE((SELECT java_bytes FROM java_final_by_role WHERE process_role = 'renderer'), 0) AS INTEGER) AS java_retained_renderer_bytes,
  CAST(COALESCE((SELECT java_count FROM java_final_by_role WHERE process_role = 'renderer'), 0) AS INTEGER) AS java_retained_renderer_count,
  CAST(COALESCE((SELECT native_alloc_bytes FROM java_final_by_role WHERE process_role = 'renderer'), 0) AS INTEGER) AS java_retained_renderer_native_alloc_bytes,
  CAST(COALESCE((SELECT chromium_bytes FROM java_final_by_role WHERE process_role = 'renderer'), 0) AS INTEGER) AS java_retained_renderer_chromium_bytes;
