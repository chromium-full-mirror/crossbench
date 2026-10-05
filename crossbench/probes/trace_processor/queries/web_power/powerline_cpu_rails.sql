-- Copyright 2026 The Chromium Authors
-- Use of this source code is governed by a BSD-style license that can be
-- found in the LICENSE file.

-- For Google Pixel devices, this query query estimates the power consumed
-- during a PowerLine run using go/pixel-odpm-rails. It includes all rails
-- associated with the SoC compute logic (CPU, GPU, memory etc), but excludes
-- radios, displays etc.
INCLUDE PERFETTO MODULE ext.web_power_rails;

SELECT
  SUM(energy_delta) as total_energy,
  power_rail_name
FROM android_power_rails_counters
WHERE ts >= COALESCE(
        (SELECT start_ts FROM ext_web_power_measured_interval),
        (SELECT MIN(ts) FROM android_power_rails_counters))
  AND ts <= COALESCE(
        (SELECT end_ts FROM ext_web_power_measured_interval),
        (SELECT MAX(ts) FROM android_power_rails_counters))
  AND power_rail_name LIKE '%CPU%'
  AND power_rail_name NOT LIKE '%CPU%_M%'
GROUP BY power_rail_name
ORDER BY total_energy DESC;
