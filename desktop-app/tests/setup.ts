import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach, vi } from 'vitest';
import { mockElectronAPI } from './mocks/electronAPI';
import { resetStore } from './mocks/storeHelpers';

beforeEach(() => {
  window.electronAPI = mockElectronAPI();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  resetStore();
});
