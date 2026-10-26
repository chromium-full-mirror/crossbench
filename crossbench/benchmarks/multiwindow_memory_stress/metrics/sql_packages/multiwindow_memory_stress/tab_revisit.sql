-- Copyright 2026 The Chromium Authors
-- Use of this source code is governed by a BSD-style license that can be
-- found in the LICENSE file.

INCLUDE PERFETTO MODULE sql_packages.multiwindow_memory_stress.iterations;

-- User timing marks named 'tab-revisit-<start|done>~cycle~<tab_index>' with
-- their iteration. The revisits right after opening a tab ('~open~') are not
-- measured.
DROP VIEW IF EXISTS tab_revisit_marks;

CREATE VIEW tab_revisit_marks AS
SELECT
  iterations.id AS it_id,
  substr(s.name, 1, instr(s.name, '~') - 1) AS name,
  CAST(substr(s.name, length(rtrim(s.name, '0123456789')) + 1) AS INTEGER)
    AS tab_index,
  s.ts
FROM slice AS s
JOIN iterations
  ON s.ts >= iterations.start AND s.ts <= iterations.end
WHERE
  s.category = 'blink.user_timing'
  AND (
    s.name GLOB 'tab-revisit-start~cycle~*'
    OR s.name GLOB 'tab-revisit-done~cycle~*'
  );

DROP VIEW IF EXISTS tab_revisit_by_tab_index;

CREATE VIEW tab_revisit_by_tab_index AS
SELECT
  it_id,
  tab_index,
  (
    max(iif(name = 'tab-revisit-done', ts, NULL))
    - max(iif(name = 'tab-revisit-start', ts, NULL))
  ) / 1e6 AS tab_revisit_duration_ms
FROM tab_revisit_marks
GROUP BY
  it_id,
  tab_index
ORDER BY
  it_id,
  tab_index;
