# Browser Startup Benchmark

This benchmark measures browser startup paint latencies (`Startup.BrowserWindow.FirstPaint`, `Startup.FirstWebContents.NonEmptyPaint3`, and `InitialWebUI.Startup.ReloadButton.FirstContentfulPaint`) across startup stories (`newtab_startup`, `blank_startup`, and `google_startup`). It compares a **baseline** configuration against one with the **InitialWebUI** feature enabled.

## Running the Benchmark

This configuration uses the `browser-startup` subcommand, which automatically loads `config/benchmark/browser_startup/probe.hjson` and `config/benchmark/browser_startup/story.hjson`. To run the benchmark locally and compare the variants using Poetry, first install the required dependencies:

```bash
poetry install
```

Then run the benchmark (passing `--separate` so each startup story launches a fresh browser instance):

```bash
poetry run cb browser-startup \
  --browser-config config/benchmark/browser_startup/browser.config.hjson \
  --separate \
  --env-validation=warn \
  --repeat=30
```

> [!NOTE]
> If you are in a Chromium development environment with `depot_tools` (`vpython3`), you can run `./cb.py browser-startup ...` directly without `poetry install`.

## Interpreting Results

After the run finishes, Crossbench outputs a path to the results directory (e.g., `results/latest/`).
Within the `trace_processor/` sub-directory, look for the following CSV (or `.json`) files containing per-run metrics:

- `browser_window_first_paint.csv` (`Startup.BrowserWindow.FirstPaint`): Contains `browser_window_first_paint_ms` for each run and story.
- `first_web_contents_non_empty_paint.csv` (`Startup.FirstWebContents.NonEmptyPaint3`): Contains `first_web_contents_non_empty_paint_ms` for each run and story.
- `reload_button_fcp.csv` (`InitialWebUI.Startup.ReloadButton.FirstContentfulPaint`): Contains `reload_button_fcp_ms` for each run and story (emitted only when `InitialWebUI` + `WebUIReloadButton` are enabled).
