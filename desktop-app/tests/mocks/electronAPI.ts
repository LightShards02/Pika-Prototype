import { vi } from 'vitest';
import type { ElectronAPI } from '../../src/types';

export function mockElectronAPI(): ElectronAPI {
  return {
    readFile: vi.fn().mockResolvedValue(''),
    writeFile: vi.fn().mockResolvedValue(true),
    listDirectory: vi.fn().mockResolvedValue([]),
    openFileDialog: vi.fn().mockResolvedValue(null),
    openDirDialog: vi.fn().mockResolvedValue(null),
    saveFileDialog: vi.fn().mockResolvedValue(null),
    getPikaRoot: vi.fn().mockResolvedValue('/mock/pika'),
    startRefine: vi.fn().mockResolvedValue(undefined),
    cancelPika: vi.fn().mockResolvedValue(undefined),
    readGateOutput: vi.fn().mockResolvedValue({ stage: 'agents', items: [] }),
    writeResolution: vi.fn().mockResolvedValue(undefined),
    applyResolutions: vi.fn().mockResolvedValue(undefined),
    resumeRefine: vi.fn().mockResolvedValue(undefined),
    onPikaStderr: vi.fn().mockReturnValue(() => {}),
    onPikaExit: vi.fn().mockReturnValue(() => {}),
  };
}
