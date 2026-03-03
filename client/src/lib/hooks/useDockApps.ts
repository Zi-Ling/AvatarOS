"use client";

import { useState, useEffect } from 'react';
import { AppId } from '@/lib/apps';

const STORAGE_KEY = 'ia-dock-pinned-apps';
const DEFAULT_PINNED: AppId[] = ['chat']; // Only Chat is pinned by default. Home is hardcoded.

export function useDockApps() {
  const [pinnedAppIds, setPinnedAppIds] = useState<AppId[]>(DEFAULT_PINNED);
  const [isLoaded, setIsLoaded] = useState(false);

  // Load from localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      try {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed)) {
          setPinnedAppIds(parsed);
        }
      } catch (e) {
        console.error("Failed to parse pinned apps", e);
      }
    }
    setIsLoaded(true);
  }, []);

  // Listen for storage events to sync across tabs/components
  useEffect(() => {
    const handleStorageChange = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY && e.newValue) {
        setPinnedAppIds(JSON.parse(e.newValue));
      }
    };
    
    // Custom event for same-window sync
    const handleCustomSync = () => {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
          const newIds = JSON.parse(stored);
          setPinnedAppIds(prev => {
              // Deep compare to avoid infinite loop
              if (JSON.stringify(prev) === JSON.stringify(newIds)) return prev;
              return newIds;
          });
      }
    };

    window.addEventListener('storage', handleStorageChange);
    window.addEventListener('dock-sync', handleCustomSync);
    
    return () => {
      window.removeEventListener('storage', handleStorageChange);
      window.removeEventListener('dock-sync', handleCustomSync);
    };
  }, []);

  // Save to localStorage whenever state changes
  useEffect(() => {
    if (isLoaded) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(pinnedAppIds));
      // Dispatch custom event to notify other components
      window.dispatchEvent(new Event('dock-sync'));
    }
  }, [pinnedAppIds, isLoaded]);

  const pinApp = (appId: AppId) => {
    setPinnedAppIds(prev => {
      if (prev.includes(appId)) return prev;
      return [...prev, appId];
    });
  };

  const unpinApp = (appId: AppId) => {
    setPinnedAppIds(prev => prev.filter(id => id !== appId));
  };

  const isPinned = (appId: AppId) => pinnedAppIds.includes(appId);

  const togglePin = (appId: AppId) => {
    if (isPinned(appId)) {
      unpinApp(appId);
    } else {
      pinApp(appId);
    }
  };

  const reorderApps = (fromIndex: number, toIndex: number) => {
    setPinnedAppIds(prev => {
      const newOrder = [...prev];
      const [movedItem] = newOrder.splice(fromIndex, 1);
      newOrder.splice(toIndex, 0, movedItem);
      return newOrder;
    });
  };

  return {
    pinnedAppIds,
    pinApp,
    unpinApp,
    isPinned,
    togglePin,
    reorderApps,
    isLoaded
  };
}

