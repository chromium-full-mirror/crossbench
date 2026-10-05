-- Copyright 2026 The Chromium Authors
-- Use of this source code is governed by a BSD-style license that can be
-- found in the LICENSE file.

INCLUDE PERFETTO MODULE ext.web_power_rails;

SELECT
  CASE
    WHEN thread.name = 'CrRendererMain' THEN 'CrRendererMain'
    WHEN thread.name = 'CrGpuMain' THEN 'CrGpuMain'
    -- Browser main thread identification:
    -- On some platforms (e.g. Android), the browser main thread doesn't use the
    -- 'CrBrowserMain' string (it truncates the package name instead, e.g.
    -- '.android.chrome'). We explicitly match the main thread of the root browser
    -- process by filtering out colons (':%') which denote sandboxed renderer/GPU
    -- processes, and filtering out zygotes.
    WHEN thread.name = 'CrBrowserMain' OR (
      thread.is_main_thread = 1
      AND (process.name LIKE '%chrome%' OR process.name LIKE '%chromium%')
      AND process.name NOT LIKE '%:%'
      AND process.name NOT LIKE '%zygote'
    ) THEN 'CrBrowserMain'
  END AS thread_name,
  SUM(
    MIN(tsb.ts + tsb.dur, interval.end_ts) -
    MAX(tsb.ts, interval.start_ts)
  ) / 1e6 AS cpu_time_ms
FROM
  thread_state tsb
JOIN
  thread USING (utid)
JOIN
  process USING (upid)
CROSS JOIN
  ext_web_power_measured_interval AS interval
WHERE
  tsb.state = 'Running'
  AND (
    thread.name IN ('CrRendererMain', 'CrBrowserMain', 'CrGpuMain')
    OR (
      thread.is_main_thread = 1
      AND (process.name LIKE '%chrome%' OR process.name LIKE '%chromium%')
      AND process.name NOT LIKE '%:%'
      AND process.name NOT LIKE '%zygote'
    )
  )
  AND tsb.ts < interval.end_ts
  AND (tsb.ts + tsb.dur) > interval.start_ts
GROUP BY
  thread_name;
