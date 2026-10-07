// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {spawnSync} from 'node:child_process';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

export const REPO_ROOT = resolve(__dirname, '../../..');

export function defaultGitRunner(args, cwd = REPO_ROOT) {
  const result = spawnSync('git', args, {
    cwd,
    encoding: 'utf-8',
  });
  return {
    status: result.status ?? 1,
    stdout: (result.stdout || '').trim(),
    stderr: (result.stderr || '').trim(),
    error: result.error,
  };
}

export function getGitCommitHash(runGit = defaultGitRunner) {
  const res = runGit(['rev-parse', 'HEAD']);
  if (res.error || res.status !== 0 || !res.stdout) {
    return '';
  }
  return res.stdout;
}

export function injectGitRevisionIntoHtml(html, gitHash) {
  const trimmed = (gitHash || '').trim();
  if (!trimmed) {
    return html;
  }
  const shortHash = trimmed.slice(0, 8);
  return html.replace(
      /<a id="crossbench-revision-link"[^>]*>.*?<\/a>/,
      `<a id="crossbench-revision-link" ` +
          `href="https://chromium.googlesource.com/crossbench/+/${trimmed}" ` +
          `title="${trimmed}" target="_blank" rel="noopener noreferrer">${
              shortHash}</a>`,
  );
}

export function verifyGitStatusForBuild(runGit = defaultGitRunner) {
  const branchRes = runGit(['rev-parse', '--abbrev-ref', 'HEAD']);
  if (branchRes.error || branchRes.status !== 0) {
    throw new Error(
        `Failed to determine current git branch: ${
            branchRes.error?.message || branchRes.stderr || 'unknown error'}`,
    );
  }
  const branch = branchRes.stdout;
  if (branch !== 'main') {
    throw new Error(
        `Production builds must be created from the 'main' branch ` +
            `(current branch: '${branch}').`,
    );
  }

  const statusRes = runGit([
    'status',
    '--porcelain',
    '--untracked-files=no',
  ]);
  if (statusRes.error || statusRes.status !== 0) {
    throw new Error(
        `Failed to check git working tree status: ${
            statusRes.error?.message || statusRes.stderr || 'unknown error'}`,
    );
  }
  if (statusRes.stdout.length > 0) {
    throw new Error(
        `Production builds require a clean working tree. ` +
            `Uncommitted changes found:\n${statusRes.stdout}`,
    );
  }

  const headRes = runGit(['rev-parse', 'HEAD']);
  if (headRes.error || headRes.status !== 0 || !headRes.stdout) {
    throw new Error(
        `Failed to resolve HEAD commit hash: ${
            headRes.error?.message || headRes.stderr || 'unknown error'}`,
    );
  }
  const currentHash = headRes.stdout;

  const ancestorRes = runGit([
    'merge-base',
    '--is-ancestor',
    'HEAD',
    'origin/main',
  ]);
  if (ancestorRes.error || ancestorRes.status !== 0) {
    throw new Error(
        `Current commit (${currentHash.slice(0, 8)}) is not submitted ` +
            `upstream in 'origin/main'.`,
    );
  }

  return currentHash;
}

if (process.argv[1] && resolve(process.argv[1]) === __filename) {
  try {
    const hash = verifyGitStatusForBuild();
    console.log(
        `Git status verified for build ` +
            `(branch: main, commit: ${hash.slice(0, 8)}).`,
    );
  } catch (err) {
    console.error(`ERROR: ${err?.message || err}`);
    process.exit(1);
  }
}
