const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  getAppVersion: () => ipcRenderer.invoke("app:get-version"),
  platform: process.platform,
  minimizeWindow: () => ipcRenderer.send("window:minimize"),
  maximizeWindow: () => ipcRenderer.send("window:maximize"),
  closeWindow: () => ipcRenderer.send("window:close"),
  // Clipboard
  readClipboardFilePaths: () => ipcRenderer.invoke("clipboard:read-file-paths"),
  clearClipboard: () => ipcRenderer.invoke("clipboard:clear"),
  // Floating window APIs
  expandFloatingWindow: () => ipcRenderer.send("floating:expand"),
  resizeFloatingExpanded: () => ipcRenderer.send("floating:resize-expanded"),
  resizeFloatingCollapsed: () => ipcRenderer.send("floating:resize-collapsed"),
  moveFloatingWindow: (deltaX, deltaY) => ipcRenderer.send("floating:move", { deltaX, deltaY }),
  setIgnoreMouseEvents: (ignore, options) => ipcRenderer.send("floating:set-ignore-mouse-events", ignore, options),
  toggleFloatingWindow: () => ipcRenderer.invoke("floating:toggle"),
  isFloatingWindowVisible: () => ipcRenderer.invoke("floating:is-visible"),
});
