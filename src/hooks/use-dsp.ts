import { useCallback, useEffect } from 'react';
import { useAppStore } from '@/hooks/use-app-store';
import type { DspConfig } from '@/types';
import { tauriApi } from '@/utils/tauri-api';

const STATUS_POLL_MS = 200;
const CONFIG_DEBOUNCE_MS = 120;

/**
 * 管理 DSP 配置（降噪 + VAD）：
 * - 启动时拉取一次后端配置作为初始值
 * - 修改时本地立刻乐观更新，并防抖推送到后端
 * - 引擎运行时按 200ms 轮询 dsp 状态（说话灯 / VAD 概率）
 */
export function useDsp(): {
  setConfig: (patch: Partial<DspConfig>) => void;
} {
  const dspConfig = useAppStore((s) => s.dspConfig);
  const setDspConfig = useAppStore((s) => s.setDspConfig);
  const patchDspConfig = useAppStore((s) => s.patchDspConfig);
  const setDspStatus = useAppStore((s) => s.setDspStatus);
  const engineStatus = useAppStore((s) => s.engineStatus);

  // 首次拉取
  useEffect(() => {
    let alive = true;
    void tauriApi
      .getDspConfig()
      .then((cfg) => {
        if (alive) setDspConfig(cfg);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [setDspConfig]);

  // 防抖推送
  useEffect(() => {
    const t = window.setTimeout(() => {
      void tauriApi.setDspConfig(dspConfig).catch(() => undefined);
    }, CONFIG_DEBOUNCE_MS);
    return () => window.clearTimeout(t);
  }, [dspConfig]);

  // 状态轮询
  useEffect(() => {
    if (engineStatus !== 'Running') return;
    let alive = true;
    const tick = async (): Promise<void> => {
      if (!alive) return;
      try {
        const s = await tauriApi.getDspStatus();
        if (alive) setDspStatus(s);
      } catch {
        /* ignore */
      }
    };
    void tick();
    const id = window.setInterval(tick, STATUS_POLL_MS);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [engineStatus, setDspStatus]);

  const setConfig = useCallback(
    (patch: Partial<DspConfig>) => {
      patchDspConfig(patch);
    },
    [patchDspConfig],
  );

  return { setConfig };
}
