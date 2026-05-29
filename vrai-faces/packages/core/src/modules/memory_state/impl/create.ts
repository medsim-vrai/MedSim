import type { MemoryStateModule, SnapshotHooks } from '@contracts/memory_state';
import type { BootDeps, SessionState } from '@contracts/shared';

const DB_NAME = 'vrai-faces';
const STORE   = 'session-state';
const DB_VERSION = 1;

function key(scenarioId: string, characterId: string): string {
  return `${scenarioId}::${characterId}`;
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      req.result.createObjectStore(STORE);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function idbGet<T>(k: string): Promise<T | null> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readonly');
    const req = tx.objectStore(STORE).get(k);
    req.onsuccess = () => resolve((req.result as T) ?? null);
    req.onerror = () => reject(req.error);
  });
}

async function idbPut<T>(k: string, v: T): Promise<void> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite');
    tx.objectStore(STORE).put(v, k);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function idbDelete(k: string): Promise<void> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite');
    tx.objectStore(STORE).delete(k);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

export function createImpl(): MemoryStateModule {
  let _deps: BootDeps | null = null;
  const hooks = new Map<string, SnapshotHooks>();

  return {
    async boot(deps) { _deps = deps; },
    dispose() { hooks.clear(); _deps = null; },

    async save(state) {
      await idbPut(key(state.scenarioId, state.characterId), state);
    },

    async load(scenarioId, characterId) {
      return idbGet<SessionState>(key(scenarioId, characterId));
    },

    async clear(scenarioId, characterId) {
      await idbDelete(key(scenarioId, characterId));
    },

    register(moduleId, h) { hooks.set(moduleId, h); },

    async pauseAll(): Promise<SessionState> {
      const modules: Record<string, unknown> = {};
      for (const [id, h] of hooks) {
        await h.pause();
        modules[id] = h.snapshot();
      }
      const scenarioId  = _deps?.scenarioId  ?? 'unknown';
      const characterId = _deps?.characterId ?? 'unknown';
      const state: SessionState = {
        v: 1,
        scenarioId,
        characterId,
        opacityLevel: 1,                         // shell will overwrite before save
        modules,
        savedAt: Date.now(),
      };
      await idbPut(key(scenarioId, characterId), state);
      return state;
    },

    async resumeAll(scenarioId, characterId) {
      const state = await idbGet<SessionState>(key(scenarioId, characterId));
      if (!state) return;
      for (const [id, h] of hooks) {
        const snap = state.modules[id];
        if (snap !== undefined) await h.restore(snap);
        await h.resume();
      }
    },
  };
}
