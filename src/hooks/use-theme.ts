import { useCallback, useSyncExternalStore } from 'react';

export type ThemeMode = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';

const STORAGE_KEY = 'rvc.theme';
const SWITCHING_FLAG = 'data-theme-switching';

const mediaQuery = (): MediaQueryList | null => {
  if (typeof window === 'undefined') return null;
  return window.matchMedia('(prefers-color-scheme: dark)');
};

const readStoredMode = (): ThemeMode => {
  if (typeof window === 'undefined') return 'system';
  const v = window.localStorage.getItem(STORAGE_KEY);
  return v === 'light' || v === 'dark' || v === 'system' ? v : 'system';
};

const resolveTheme = (mode: ThemeMode): ResolvedTheme => {
  if (mode === 'system') {
    const mq = mediaQuery();
    return mq?.matches ? 'dark' : 'light';
  }
  return mode;
};

/**
 * 把 resolved 写到 <html data-theme="...">。切换瞬间冻结所有过渡，
 * 避免大批量 CSS 变量同时变化时产生跳变。
 */
const applyTheme = (resolved: ResolvedTheme): void => {
  const root = document.documentElement;
  root.setAttribute(SWITCHING_FLAG, '');
  root.setAttribute('data-theme', resolved);
  // 下一帧解除冻结
  window.requestAnimationFrame(() => {
    window.requestAnimationFrame(() => {
      root.removeAttribute(SWITCHING_FLAG);
    });
  });
};

interface ThemeSnapshot {
  mode: ThemeMode;
  resolved: ResolvedTheme;
}

const listeners = new Set<() => void>();
let snapshot: ThemeSnapshot = (() => {
  if (typeof window === 'undefined') {
    return { mode: 'system', resolved: 'dark' };
  }
  const mode = readStoredMode();
  return { mode, resolved: resolveTheme(mode) };
})();

const emit = (next: ThemeSnapshot): void => {
  if (next.mode === snapshot.mode && next.resolved === snapshot.resolved) return;
  snapshot = next;
  listeners.forEach((l) => l());
};

const subscribe = (cb: () => void): (() => void) => {
  listeners.add(cb);
  return () => listeners.delete(cb);
};

const getSnapshot = (): ThemeSnapshot => snapshot;

let initialized = false;
const ensureInitialized = (): void => {
  if (initialized || typeof window === 'undefined') return;
  initialized = true;

  applyTheme(snapshot.resolved);

  const mq = mediaQuery();
  mq?.addEventListener('change', (e) => {
    if (snapshot.mode !== 'system') return;
    const resolved: ResolvedTheme = e.matches ? 'dark' : 'light';
    applyTheme(resolved);
    emit({ mode: 'system', resolved });
  });
};

export interface UseThemeResult {
  mode: ThemeMode;
  resolved: ResolvedTheme;
  setMode: (mode: ThemeMode) => void;
  cycle: () => void;
}

/**
 * 主题状态：light / dark / system，配合 prefers-color-scheme。
 * 用 useSyncExternalStore 让多个组件共享同一个状态，且无需 Context。
 */
export function useTheme(): UseThemeResult {
  ensureInitialized();
  const { mode, resolved } = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  const setMode = useCallback((next: ThemeMode) => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(STORAGE_KEY, next);
    const resolvedNext = resolveTheme(next);
    applyTheme(resolvedNext);
    emit({ mode: next, resolved: resolvedNext });
  }, []);

  const cycle = useCallback(() => {
    const order: ThemeMode[] = ['light', 'dark', 'system'];
    const idx = order.indexOf(snapshot.mode);
    const next = order[(idx + 1) % order.length] ?? 'system';
    setMode(next);
  }, [setMode]);

  return { mode, resolved, setMode, cycle };
}

/**
 * 在 React 挂载前同步设置一次 data-theme，避免首屏闪烁。
 * 在 main.tsx 顶部调用一次即可。
 */
export function bootstrapTheme(): void {
  if (typeof window === 'undefined') return;
  const mode = readStoredMode();
  const resolved = resolveTheme(mode);
  document.documentElement.setAttribute('data-theme', resolved);
}
