-- Copyright 2026 The Chromium Authors
-- Use of this source code is governed by a BSD-style license that can be
-- found in the LICENSE file.

INCLUDE PERFETTO MODULE sql_packages.multiwindow_memory_stress.iterations;

-- User timing marks named '<name>~<tab_index>' with their iteration.
DROP VIEW IF EXISTS tab_marks;

CREATE VIEW tab_marks AS
SELECT
  iterations.id AS it_id,
  substr(s.name, 1, instr(s.name, '~') - 1) AS name,
  CAST(substr(s.name, instr(s.name, '~') + 1) AS INTEGER) AS tab_index,
  s.ts
FROM slice AS s
JOIN iterations
  ON s.ts >= iterations.start AND s.ts <= iterations.end
WHERE
  s.category = 'blink.user_timing'
  AND (
    s.name GLOB 'page-load~*'
    OR s.name GLOB 'page-loaded~*'
    OR s.name GLOB 'allocation-start~*'
    OR s.name GLOB 'allocation-done~*'
  );

DROP VIEW IF EXISTS tab_timing_by_tab_index;

CREATE VIEW tab_timing_by_tab_index AS
SELECT
  it_id,
  tab_index,
  (
    max(iif(name = 'page-loaded', ts, NULL))
    - max(iif(name = 'page-load', ts, NULL))
  ) / 1e6 AS page_load_duration_ms,
  (
    max(iif(name = 'allocation-done', ts, NULL))
    - max(iif(name = 'allocation-start', ts, NULL))
  ) / 1e6 AS allocation_duration_ms
FROM tab_marks
GROUP BY
  it_id,
  tab_index
ORDER BY
  it_id,
  tab_index;
