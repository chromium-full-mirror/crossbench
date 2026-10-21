# Web Power Benchmark

The "Web Power" benchmark measures the power consumption of Web workloads.

Currently supported scenarios:

- **Idle:** Static, fully-loaded page (or as close to it as possible, since
  pages can load arbitrary new content at any time).
- **Scroll:** Actively scrolling up and down (with pauses for workload realism).
- **Page-Load:** The initial page-loading phase.
- **Media-Playback:** The steady-state of playing back video and audio.

The canonical sites used for power measurements are **Al Jazeera** (`ajnews`),
**CNN** (`cnn`), and **MSN** (`msn`). For the `media-playback` scenario, the
canonical site is **YouTube**.

We support other sites (like `yahoo`), but they aren't canonical - usually
because their metrics are too noisy, or they aren't representative of the
broader Web.

A story consists of a combination of a scenario and a site (for example,
`idle-cnn` or `scroll-msn`). The site may be implied if only one is supported
(e.g., media playback currently only uses YouTube).

Power measurement is supported through various means. These include:

- **ODPM (On-Device Power Meter):** Hardware sensors built into many modern
  devices (like Pixel phones) that report precise power consumption for various
  system rails (e.g., CPU, GPU, Display).
- **External Dedicated Hardware:** Hardware like Kibble, paired with matching
  software like Bits, can be used for high-fidelity, external power profiling.

## Setup

### Getting the Code

The "Web Power" benchmark is part of the open-source
[Crossbench](http://chromium.googlesource.com/) project. Instructions are
available [here](https://chromium.googlesource.com/crossbench). We strongly
recommend following the guidance on using
[depot_tools](https://chromium.googlesource.com/chromium/tools/depot_tools/+/HEAD/README.md).

If you're a Googler, after checking out Crossbench, open your `.gclient` file.
It should contain a section named `"crossbench"`. Add the following
entry in its `"custom_vars"` section:

```python
      "checkout_crossbench_internal": True,
```

Thereafter, the file should look roughly as follows:

```python
solutions = [
  {
    "name": "crossbench",
    "url": "https://chromium.googlesource.com/crossbench.git",
    "deps_file": "DEPS",
    "custom_deps": {},
    "custom_vars": {
      "checkout_crossbench_internal": True,
    },
  },
]
```

After setting this for the first time, run `gclient sync` once to fetch
the `crossbench-internal` submodule.

### Obtaining Access to WPR Recordings

To ensure consistent results, we use WPR (Web Page Replay) archives stored in
the `chrome-partner-loadline` cloud bucket. Request access to this
bucket [here](https://docs.google.com/forms/d/e/1FAIpQLSdCb1LYPlDEKuOd1lP21yZ9YDEvjq-9W0a5X9k7QxM_YjskzA/viewform).

After obtaining access, run this once:

```bash
gcloud auth application-default login --disable-quota-project
```

If you run into issues, refer to the
[relevant section](https://chromium.googlesource.com/crossbench/+/refs/heads/main/config/benchmark/loadline2/#cloud-bucket-access) of the LoadLine 2 guide. (Both benchmarks use the same
cloud bucket.)

## Running the Benchmark

### Canonical Configuration Runs

A canonical run currently consists of 10 stories, 5 repetitions of each, and a
set cool-down period in between. Run it with:

```bash
./cb.py web-power --browser=adb:chrome
```

For official score-collecting runs, do NOT deviate from the defaults.
For example, tweaking the interval between runs might affect the thermal
state of the device, change the frequency of thermal throttling, and therefore
impact the scores.

### Running on iOS (Scroll Scenario)

The scroll scenario (`web-power-scroll`) can also be run on iOS:

```bash
./cb.py web-power-scroll --browser=ios:safari
```

Or target a specific device using its UDID:

```bash
./cb.py web-power-scroll --browser=<UDID>:safari
```

**Prerequisite:** Touch scrolling on iOS requires
[WebDriverAgent](https://github.com/appium/WebDriverAgent) (WDA) to simulate
physical touch gestures. Crossbench will automatically launch
`WebDriverAgentRunner` if its `.xctestrun` bundle has been built in Xcode or
with `xcodebuild` (deposited in `~/Library/Developer/Xcode/DerivedData/`), or if
the `CROSSBENCH_WDA_XCTESTRUN` environment variable points to it.
Alternatively, launch `WebDriverAgentRunner` on the device beforehand so it
listens on port 8100.


### Results

Like any Crossbench benchmark, a results directory is produced at the end of
the run.

The main metric of the Web Power benchmark is power consumption. As mentioned
earlier, there are two ways to collect this data: ODPM or dedicated hardware.

By default, a Perfetto probe will be used to collect ODPM metrics.
Users with access to Bits may use that instead by specifying
`--bits-path=path/to/bits/binary`.

Because Perfetto trace collection impacts performance and power, the collection
methods are mutually exclusive by default. If you know what you are doing and
want _both_ metrics simultaneously, pass both `--bits-path` and
`--probe=perfetto:config/benchmark/web_power/perfetto_basic.txtpb`.

#### ODPM

When using ODPM, Crossbench pulls Perfetto traces with power rail data. After
the run, it auto-processes them and outputs:

- **Logs and traces:** Saved in the aforementioned results directory. These
  include a raw Perfetto trace for each iteration (under
  `runs/*/perfetto.trace.pb.gz`) that you can open in
  [Perfetto UI](https://ui.perfetto.dev).
- **Console Summary:** High-level results printed straight to `stdout`.

As power rails are hardware-specific, we need custom Trace Processor SQL queries
to analyse the data. Crossbench determines the device model and runs the
matching SQL query.

**Watch out:** power rail queries expose hardware details. Do not push queries
for unreleased hardware to the open-source repo. Keep them gated in a private
repo like `crossbench-internal` (see [Getting the Code](#getting-the-code)).

#### Kibble/Bits

Dedicated power-measuring hardware and matching software can be used.
Crossbench currently supports one such HW/SW pair - Kibble/Bits. It is used
by specifying `--bits-path=<PATH_TO_BITS_BINARY>`. (Different users will have
installed Bits to different paths.)

Bits captures high-fidelity power data throughout the run and writes data to a
sub-directory of the dedicated Bits output directory. This is controlled using
`--bits-out=<SUB_DIRECTORY_NAME>`. (Note that the name of the sub-directory is
expected, not the full path.) If the flag is omitted, the sub-directory name
defaults to the current timestamp in the format `YYYYMMDD_HHMMSS`.

Additional supported Bits configuration includes:

- `--bits-device`: The device identifier passed to the Bits tool. (This is
  typically NOT the ADB serial number of the device.)
- `--bits-duration`: How long Bits records. Unused by default; instead,
  an unbounded recording is used, then terminated when the benchmark completes.
- `--bits-port`: The Bits service port. This can normally be omitted.

To view the Bits power data alongside a Perfetto trace from the device, run
both probes (`--bits-path` plus `--probe=perfetto:...`, see above) and
afterwards:

```bash
./cb.py bits-merge path/to/results/dir path/to/output/dir
```

For each run, this writes an archive into the output directory (which must
be empty or not exist yet), combining the Bits trace with the device's trace
on a common timeline. Archives are named `<browser>_<story>_<repetition>.zip`,
e.g. `android.5B221FDDV0000K.1_0_web-power-idle-cnn_0.zip`. Open an archive
in [Perfetto UI](https://ui.perfetto.dev).

#### Uploading Results

To share results with colleagues, you can upload them to a GCS bucket (Google
Cloud Storage). You can either:
- Elect to upload the results automatically after the benchmark finishes.
  This is done by specifying `--upload-results` when running Crossbench.
  Googlers should use `--upload-results=gs://web-power-crossbench-export/`,
  and other users can use their own GCS bucket if they so wish.
- Manually trigger an upload of previously collected results. This is done
  using `./cb.py upload-results path/to/results/dir path/to/gcs_bucket`.

If you upload results often, you may save yourself some typing by setting the
`CROSSBENCH_RESULT_UPLOAD_TARGET` environment variable to the target URL to
which you normally upload. Uploads will then default to that target when an
explicit value is omitted.

For example, as a Googler, you could add this to your `.bashrc` file:
```bash
CROSSBENCH_RESULT_UPLOAD_TARGET="gs://web-power-crossbench-export/"
```
If you do so, you can then specify `--upload-results` without an explicit URL,
or run `./cb.py upload-results results/latest`.

## Versioning

### Reading the Version

The version of Crossbench itself can be read using the `--version` flag:

```bash
./cb.py --version
```

The version of the benchmark can be read using the `--benchmark-version` flag.
Naturally, the benchmark itself must be specified (in this case, `web-power`):

```bash
./cb.py web-power --benchmark-version
```

You will typically only care about the latter (the Web Power version).

### Interpreting the Version String

The Web Power version follows the format `A.B.C`, where:

- **A** is expected to be incremented roughly every year, with `1` being the
  first entry launched in 2026. Different values of `A` are associated with such
  different workloads and scores that they might be considered distinct
  benchmarks.
- **B** is the major version within a given year. It will be incremented when
  significant changes are made that can affect the score.
- **C** is the minor version within a given `A.B` version. It is typically
  incremented following minor changes that have no significant impact on the
  scores themselves, but which might affect the ease with which the benchmarks
  are executed or scores are collected.
