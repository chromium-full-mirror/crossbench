-- Copyright 2026 The Chromium Authors
-- Use of this source code is governed by a BSD-style license that can be
-- found in the LICENSE file.

INCLUDE PERFETTO MODULE android.power_rails;

DROP VIEW IF EXISTS ext_web_power_measured_interval;
CREATE VIEW ext_web_power_measured_interval AS
SELECT
  (SELECT ts FROM slice WHERE name = 'crossbench-web-power-start' LIMIT 1) AS start_ts,
  (SELECT ts FROM slice WHERE name = 'crossbench-web-power-stop' LIMIT 1) AS end_ts;

DROP VIEW IF EXISTS ext_web_power_per_rail;
CREATE VIEW ext_web_power_per_rail AS
SELECT
  power_rail_name,
  (MAX(value) - MIN(value)) / (MAX(ts) - MIN(ts)) * 1e6 AS avg_power_mw
FROM android_power_rails_counters
WHERE ts >= COALESCE(
        (SELECT start_ts FROM ext_web_power_measured_interval),
        (SELECT MIN(ts) FROM android_power_rails_counters))
  AND ts <= COALESCE(
        (SELECT end_ts FROM ext_web_power_measured_interval),
        (SELECT MAX(ts) FROM android_power_rails_counters))
GROUP BY 1;
