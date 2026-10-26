-- Copyright 2026 The Chromium Authors
-- Use of this source code is governed by a BSD-style license that can be
-- found in the LICENSE file.

-- the sql formatter will attempt to re-type the id column to STRING which
-- is not correct. STRING will automatically convert numeric values to a
-- numeric type but id needs to always remain as text.
-- sqlformat file off

-- The test may have been run multiple times in the same trace.
-- Grab the start and end ts for each iteration.
DROP VIEW IF EXISTS iterations;

CREATE VIEW iterations AS
SELECT
  CAST(id AS TEXT) AS id,
  "start",
  "end"
FROM (
  SELECT
    row_number() OVER (ORDER BY ts) - 1 AS id,
    ts AS "start"
  FROM slice
  WHERE
    category = 'blink.user_timing' AND name = 'crossbench-iteration-start'
)
JOIN (
  SELECT
    row_number() OVER (ORDER BY ts) - 1 AS id,
    ts AS "end"
  FROM slice
  WHERE
    category = 'blink.user_timing' AND name = 'crossbench-iteration-end'
)
  USING (id)
ORDER BY
  id;
