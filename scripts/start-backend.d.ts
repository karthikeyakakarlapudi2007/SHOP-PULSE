import type { ChildProcess } from 'node:child_process';

export interface StartBackendOptions {
  silent?: boolean;
}

export function getPythonPath(): string;
export function startBackend(options?: StartBackendOptions): ChildProcess;

