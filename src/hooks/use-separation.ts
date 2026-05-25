import { useCallback, useEffect, useRef } from 'react';
import { useAppStore } from '@/hooks/use-app-store';
import type { SeparationStatus } from '@/types';
import { tauriApi } from '@/utils/tauri-api';

const POLL_MS = 800;

/**
 * 离线人声分离任务管理。
 * - start(inputPath) 启动一个新任务（如已有任务在跑则先取消）
 * - cancel() 取消当前任务
 * - 任务运行中按 800ms 轮询后端状态
 */
export function useSeparation(): {
  job: SeparationStatus | null;
  start: (inputPath: string, opts?: { model?: string; twoStems?: boolean }) => Promise<void>;
  cancel: () => Promise<void>;
} {
  const job = useAppStore((s) => s.separationJob);
  const setJob = useAppStore((s) => s.setSeparationJob);
  const pollRef = useRef<number | null>(null);

  const stopPoll = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPoll = useCallback(
    (sessionId: string) => {
      stopPoll();
      pollRef.current = window.setInterval(async () => {
        try {
          const status = await tauriApi.getSeparationStatus(sessionId);
          setJob(status);
          if (
            status.state === 'done' ||
            status.state === 'failed' ||
            status.state === 'cancelled'
          ) {
            stopPoll();
          }
        } catch {
          stopPoll();
        }
      }, POLL_MS);
    },
    [setJob, stopPoll],
  );

  useEffect(() => stopPoll, [stopPoll]);

  const start = useCallback(
    async (
      inputPath: string,
      opts?: { model?: string; twoStems?: boolean },
    ): Promise<void> => {
      // 如果有运行中任务，先取消
      if (job && (job.state === 'pending' || job.state === 'running')) {
        try {
          await tauriApi.cancelSeparation(job.sessionId);
        } catch {
          /* ignore */
        }
      }
      const { session_id } = await tauriApi.startSeparation({
        input_path: inputPath,
        model: opts?.model,
        two_stems: opts?.twoStems ?? true,
      });
      const initial: SeparationStatus = {
        sessionId: session_id,
        state: 'pending',
        progress: 0,
        message: 'queued',
        vocalsPath: null,
        otherPath: null,
        error: null,
      };
      setJob(initial);
      startPoll(session_id);
    },
    [job, setJob, startPoll],
  );

  const cancel = useCallback(async (): Promise<void> => {
    if (!job) return;
    try {
      await tauriApi.cancelSeparation(job.sessionId);
    } catch {
      /* ignore */
    }
  }, [job]);

  return { job, start, cancel };
}
