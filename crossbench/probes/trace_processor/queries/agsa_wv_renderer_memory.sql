INCLUDE PERFETTO MODULE linux.memory.high_watermark;
INCLUDE PERFETTO MODULE linux.memory.process;

-- Find the timestamp of when the SRP in AGSA has finished loading
WITH srp_finish_event AS (
  SELECT ts
  FROM slice
  WHERE name = 'GOOGLEAPP_SEARCH_TEXT_SEARCH_FINISH'
  ORDER BY ts ASC
  LIMIT 1
),
-- Retrieve the latest memory metrics for the WebView renderer process
-- just before the SRP finish event occurs.
latest_memory AS (
  SELECT
    m.upid,
    m.anon_rss AS rss_anon_renderer_bytes,
    m.file_rss AS rss_file_renderer_bytes,
    m.shmem_rss AS rss_shmem_renderer_bytes,
    m.swap AS swap_renderer_bytes,
    m.anon_rss_and_swap AS rss_anon_plus_swap_renderer_bytes
  FROM memory_rss_and_swap_per_process m
  JOIN srp_finish_event s
  WHERE m.ts < s.ts
    AND m.process_name LIKE '%webview%sandboxed%'
  ORDER BY m.ts DESC
  LIMIT 1
),
latest_hwm AS (
  SELECT
    h.rss_high_watermark AS rss_hwm_renderer_bytes
  FROM memory_rss_high_watermark_per_process h
  JOIN srp_finish_event s
  JOIN latest_memory m ON h.upid = m.upid
  WHERE h.ts < s.ts
  ORDER BY h.ts DESC
  LIMIT 1
)
SELECT
  rss_anon_renderer_bytes,
  rss_file_renderer_bytes,
  rss_shmem_renderer_bytes,
  swap_renderer_bytes,
  rss_anon_plus_swap_renderer_bytes,
  rss_hwm_renderer_bytes
FROM latest_memory, latest_hwm;
