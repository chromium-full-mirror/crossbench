// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

export interface GitCommandResult {
  status: number;
  stdout: string;
  stderr: string;
  error?: Error;
}

export type GitRunner = (args: string[], cwd?: string) => GitCommandResult;

export const REPO_ROOT: string;
export function defaultGitRunner(args: string[], cwd?: string): GitCommandResult;
export function getGitCommitHash(runGit?: GitRunner): string;
export function injectGitRevisionIntoHtml(html: string, gitHash: string): string;
export function verifyGitStatusForBuild(runGit?: GitRunner): string;
