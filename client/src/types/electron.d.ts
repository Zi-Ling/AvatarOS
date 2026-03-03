export interface ElectronAPI {
  getAppVersion: () => Promise<string>;
  platform: string;
  minimizeWindow: () => void;
  maximizeWindow: () => void;
  closeWindow: () => void;
  // Floating window APIs
  expandFloatingWindow: () => void;
  moveFloatingWindow: (deltaX: number, deltaY: number) => void;
  setIgnoreMouseEvents: (ignore: boolean, options?: { forward: boolean }) => void;
  toggleFloatingWindow: () => Promise<boolean>;
  isFloatingWindowVisible: () => Promise<boolean>;
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI;
  }
}

export {};

