-- Copyright 2026 The Chromium Authors
-- Use of this source code is governed by a BSD-style license that can be
-- found in the LICENSE file.

INCLUDE PERFETTO MODULE sql_packages.multiwindow_memory_stress.iterations;

DROP VIEW IF EXISTS meminfo_events;

CREATE VIEW meminfo_events AS
SELECT
  iterations.id AS it_id,
  s.ts,
  extract_arg(s.arg_set_id, 'debug.data.detail') AS json_str
FROM slice AS s
JOIN iterations
  ON s.ts >= iterations.start AND s.ts <= iterations.end
WHERE
  s.category = 'blink.user_timing' AND s.name = 'crossbench-meminfo';

DROP VIEW IF EXISTS meminfo_total_output;

CREATE VIEW meminfo_total_output AS
SELECT
  it_id,
  json_str ->> '$.title' AS title,
  sum(CAST(proc.value ->> '$.pss_total' AS REAL)) / 1024.0 AS pss_total_mb,
  sum(CAST(proc.value ->> '$.rss_total' AS REAL)) / 1024.0 AS rss_total_mb,
  sum(CAST(proc.value ->> '$.swap_total' AS REAL)) / 1024.0 AS swap_total_mb
FROM meminfo_events, json_each(json_str -> '$.processes') AS proc
GROUP BY
  it_id,
  title;
