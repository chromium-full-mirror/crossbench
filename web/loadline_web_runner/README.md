# LoadLine Web Runner

The **LoadLine Web Runner** is a client-side web application that runs
[Crossbench](https://chromium.googlesource.com/crossbench/) and the
[LoadLine benchmark](https://chromium.googlesource.com/crossbench/+/refs/heads/main/config/benchmark/loadline2/)
entirely within modern web browsers (e.g. Google Chrome) without requiring a
native Python installation, desktop ADB server, or local command-line tooling
on the host machine.

---

## Supported Devices

- Only **arm64** devices are supported.
- Emulators are not supported because they don't work via WebUSB.

---

## High-Level Architecture

The web runner orchestrates benchmark runs on connected Android devices through
several browser-native technologies:

1. **WebUSB ADB Transport (`src/webadb_bridge.ts`, `src/webadb_crypto.ts`)**:
   Communicates directly with Android devices over WebUSB via `@yume-chan/adb`.
   Handles RSA key generation and persistence (via Web Crypto and IndexedDB),
   packet framing, shell command execution, file sync (push/pull), and process
   streaming.

2. **Pyodide WebAssembly Runtime (`src/pyodide_worker.ts`,
   `src/pyodide_runner.ts`)**:
   Runs the full Crossbench Python test framework inside a dedicated Web Worker
   using [Pyodide](https://pyodide.org/). Crossbench source files and benchmark
   definitions are mounted into Emscripten's virtual filesystem (MEMFS).

3. **Synchronous RPC Bridge (`src/sync_rpc_bridge.ts`)**:
   Allows synchronous Python platform methods running inside the Web Worker to
   make blocking calls to asynchronous main-thread browser APIs
   (WebUSB, CDP, DOM) using `SharedArrayBuffer` and `Atomics.wait` /
   `Atomics.notify`.

4. **Chrome DevTools Protocol Client (`src/cdp_client.ts`,
   `src/devtools_discovery.ts`)**:
   Discovers Chrome abstract Unix domain sockets on Android
   (`localabstract:chrome_devtools_remote`), negotiates DevTools WebSocket
   endpoints, and drives navigation, DOM inspection, and tracing over CDP.

5. **In-Browser Perfetto Trace Processor (`src/trace_processor_wasm.ts`)**:
   Processes recorded Perfetto traces directly in the browser using the official
   `trace_processor.wasm` engine and executes SQL metric queries client-side.

6. **Google Cloud Storage & Auth (`src/gis_auth.ts`, `src/gcs_cache.ts`)**:
   Uses Google Identity Services (GIS) OAuth 2.0 to authenticate and download
   WPR replay archives from Cloud Storage, caching them locally in IndexedDB.

---

## Development & Testing

### Prerequisites
- **Node.js** (v20+ recommended) and **npm**
- Full Crossbench checkout with dependencies (including `vpython3`)

### Installation
```bash
# Navigate to the web runner directory
cd web/loadline_web_runner

# Install npm dependencies
npm install
```

### Local Development Server
```bash
npm run dev
```
Starts the Vite development server at `http://localhost:5173`.

> **Note on Cross-Origin Isolation:** The web runner requires
> `SharedArrayBuffer` for synchronous RPC. The development server
> (`vite.config.ts`) and production hosting (`firebase.json`) configure the
> necessary `Cross-Origin-Opener-Policy` (`same-origin`) and
> `Cross-Origin-Embedder-Policy` (`require-corp`) headers.

### Running Unit Tests
```bash
npm test
```
Runs the Vitest unit test suite covering ADB framing, crypto stores, socket
streams, and worker protocols.

### Type Checking
```bash
npx tsc --noEmit
```

---

## Production Build & Deployment

The application is deployed as a static Single Page Application (SPA) to
**Firebase Hosting**.

> **Build Safety Check:** `npm run build` verifies that the repository is on
> the `main` branch, has no uncommitted changes to tracked files, and that
> `HEAD` is submitted upstream in `origin/main` before building.

### One-Command Build & Deploy
```bash
npm run build && npx firebase deploy --only hosting
```

---

### Step-by-Step Deployment Setup

If setting up deployment from scratch or on a new workstation:

1. **Authenticate with Google / Firebase**:
   ```bash
   npx firebase login
   ```

2. **Verify Firebase Project Configuration**:
   The active Firebase project is defined in `.firebaserc`:
   ```json
   {
     "projects": {
       "default": "loadline-web-runner"
     }
   }
   ```
   To switch or select a different project:
   ```bash
   npx firebase use <project-id>
   ```

3. **Permissions & Access Control (IAM)**:
   To deploy to Firebase Hosting, your Google account must be granted access to
   the `loadline-web-runner` Google Cloud project. Access can be requested via
   [GCP IAM Console](https://console.cloud.google.com/iam-admin/iam?project=loadline-web-runner).

   The required IAM role is `roles/firebase.developAdmin`. The following
   broader roles are also enough: `roles/firebase.admin`, `roles/editor`,
   `roles/owner`.

4. **OAuth 2.0 Client ID Configuration**:
   Ensure your Google Cloud OAuth 2.0 Client ID (configured in Google Cloud
   Console under **APIs & Services > Credentials**) includes the hosting domain
   in its **Authorized JavaScript origins** and **Authorized redirect URIs**:
   - `http://localhost:5173` (local dev server)
   - `http://localhost:4173` (local preview server)
   - `https://loadline-web-runner.web.app`

5. **Build and Deploy**:
   ```bash
   # Build production assets into dist/
   npm run build

   # Deploy static assets to Firebase Hosting
   npx firebase deploy --only hosting
   ```

### Hosting Configuration Details (`firebase.json`)
- **Public Directory**: `dist`
- **SPA Rewrites**: All routes rewrite to `/index.html`, with explicit routes
  for `/auth.html` (OAuth callback), `/privacy.html`, and domain verification
  files.
- **Security Headers**:
  - `Cross-Origin-Opener-Policy: same-origin`
  - `Cross-Origin-Embedder-Policy: require-corp`
  - `/auth.html` is configured with
    `Cross-Origin-Opener-Policy: same-origin-allow-popups` to allow GIS
    authentication popups to communicate with the opener window.
