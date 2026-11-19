/**
 * Phase 4, workstream 9a: test runs never start a backend of their own.
 *
 * Vitest loads vite.config.ts. Its auto-start plugin used to launch backend/main.py on port 8000 during
 * every Vitest run; without DATABASE_URL that backend opened the development database
 * backend/shoppulse.db. Under Vitest (and with SHOPPULSE_TEST_MODE=1) the plugin must not be loaded.
 */
import { describe, it, expect } from 'vitest';
import config from '../../vite.config';

describe('test isolation: no auto-started backend', () => {
  it('the backend auto-start plugin is not loaded under Vitest', () => {
    const names = (config.plugins ?? []).flat().map((p) => (p && typeof p === 'object' && 'name' in p ? p.name : null));
    expect(process.env.VITEST).toBeTruthy();
    expect(names).not.toContain('auto-start-backend');
    expect(names).toContain('vite:react-babel');
  });

  it('the /api proxy keeps the development default unless a test target is given', () => {
    const target = (config.server?.proxy as Record<string, { target: string }>)['/api'].target;
    expect(target).toBe(process.env.SHOPPULSE_API_TARGET || 'http://127.0.0.1:8000');
  });
});
