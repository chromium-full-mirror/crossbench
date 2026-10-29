-- Copyright 2026 The Chromium Authors
-- Use of this source code is governed by a BSD-style license that can be
-- found in the LICENSE file.

INCLUDE PERFETTO MODULE chrome.histograms;

DROP VIEW IF EXISTS uma_histogram_summaries;

CREATE VIEW uma_histogram_summaries AS
WITH
  summaries AS (
    SELECT
      name AS hist_name,
      avg(value) AS "avg",
      count(*) AS "count",
      sum(value) AS "total",
      max(value) AS "max",
      percentile(value, 95) AS "p95",
      percentile(value, 90) AS "p90",
      percentile(value, 75) AS "p75",
      percentile(value, 50) AS "p50"
    FROM chrome_histograms
    GROUP BY
      name
  )
SELECT
  s.hist_name,
  s.agg_type,
  s.value,
  CASE
    WHEN s.hist_name = 'Memory.Discardable.LockingSuccess'
      THEN 'HIGHER_IS_BETTER'
    ELSE 'LOWER_IS_BETTER'
  END AS polarity
FROM (
  SELECT hist_name, 'avg' AS agg_type, "avg" AS value FROM summaries
  UNION ALL
  SELECT hist_name, 'count' AS agg_type, "count" AS value FROM summaries
  UNION ALL
  SELECT hist_name, 'total' AS agg_type, "total" AS value FROM summaries
  UNION ALL
  SELECT hist_name, 'max' AS agg_type, "max" AS value FROM summaries
  UNION ALL
  SELECT hist_name, 'p95' AS agg_type, "p95" AS value FROM summaries
  UNION ALL
  SELECT hist_name, 'p90' AS agg_type, "p90" AS value FROM summaries
  UNION ALL
  SELECT hist_name, 'p75' AS agg_type, "p75" AS value FROM summaries
  UNION ALL
  SELECT hist_name, 'p50' AS agg_type, "p50" AS value FROM summaries
) AS s;
