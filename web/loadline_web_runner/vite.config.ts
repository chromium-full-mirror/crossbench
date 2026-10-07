// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {resolve} from 'path';
import {defineConfig, type Plugin, searchForWorkspaceRoot} from 'vite';

import {getGitCommitHash, injectGitRevisionIntoHtml, verifyGitStatusForBuild} from './scripts/check_git_status.mjs';

const POPUP_ALLOWED_PREFIXES = [
  '/auth',
  '/privacy',
  '/google03706b24b8377fa4.html',
];

function coopCoepPlugin(): Plugin {
  const handler = (req: any, res: any, next: any) => {
    const url = req.url || '';
    if (POPUP_ALLOWED_PREFIXES.some((prefix) => url.startsWith(prefix))) {
      res.setHeader('Cross-Origin-Opener-Policy', 'same-origin-allow-popups');
      next();
      return;
    }
    res.setHeader('Cross-Origin-Opener-Policy', 'same-origin');
    res.setHeader('Cross-Origin-Embedder-Policy', 'require-corp');
    next();
  };

  return {
    name: 'coop-coep-plugin',
    configureServer(server) {
      server.middlewares.use(handler);
    },
    configurePreviewServer(server) {
      server.middlewares.use(handler);
    },
  };
}

function gitRevisionPlugin(gitHash: string, isBuild: boolean): Plugin {
  return {
    name: 'git-revision-plugin',
    buildStart() {
      if (isBuild) {
        verifyGitStatusForBuild();
      }
    },
    transformIndexHtml(html) {
      return injectGitRevisionIntoHtml(html, gitHash);
    },
  };
}

export default defineConfig(({command, mode}) => {
  const gitHash = getGitCommitHash();
  const isBuild = command === 'build' && mode !== 'test';

  return {
    plugins: [
      coopCoepPlugin(),
      gitRevisionPlugin(gitHash, isBuild),
    ],
    worker: {
      format: 'es',
    },
    optimizeDeps: {
      exclude: ['pyodide'],
    },
    server: {
      fs: {
        allow: [searchForWorkspaceRoot(process.cwd())],
        deny: ['.env', '.env.*', '**/.git/**'],
      },
      proxy: {
        '/gcs-proxy': {
          target: 'https://storage.googleapis.com',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/gcs-proxy/, ''),
        },
      },
    },
    build: {
      target: 'es2022',
      rollupOptions: {
        input: {
          main: resolve(__dirname, 'index.html'),
          auth: resolve(__dirname, 'auth.html'),
          privacy: resolve(__dirname, 'privacy.html'),
        },
      },
    },
    test: {
      globals: true,
      environment: 'happy-dom',
      setupFiles: ['./tests/setup.ts'],
      include: ['tests/**/*.test.ts'],
      pool: 'forks',
    },
  };
});
