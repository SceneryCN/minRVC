import { useCallback, useEffect, useRef, useState } from 'react';
import { useAppStore } from '@/hooks/use-app-store';
import type { StartTrainingPayload, TrainingGpuInfo, TrainingStatus } from '@/types';
import { tauriApi } from '@/utils/tauri-api';

const POLL_MS = 1200;

export function useTraining(): {
  job: TrainingStatus | null;
  gpuInfo: TrainingGpuInfo | null;
  gpuLoading: boolean;
  refreshGpu: () => Promise<void>;
  start: (payload: StartTrainingPayload) => Promise<void>;
  cancel: () => Promise<void>;
} {
  const job = useAppStore((s) => s.trainingJob);
  const setJob = useAppStore((s) => s.setTrainingJob);
  const pollRef = useRef<number | null>(null);
  const [gpuInfo, setGpuInfo] = useState<TrainingGpuInfo | null>(null);
  const [gpuLoading, setGpuLoading] = useState(false);

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
          const status = await tauriApi.getTrainingStatus(sessionId);
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

  const refreshGpu = useCallback(async (): Promise<void> => {
    setGpuLoading(true);
    try {
      setGpuInfo(await tauriApi.getTrainingGpu());
    } finally {
      setGpuLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshGpu().catch(() => undefined);
  }, [refreshGpu]);

  const start = useCallback(
    async (payload: StartTrainingPayload): Promise<void> => {
      if (job && (job.state === 'pending' || job.state === 'running')) {
        try {
          await tauriApi.cancelTraining(job.sessionId);
        } catch {
          /* ignore */
        }
      }
      const { session_id } = await tauriApi.startTraining(payload);
      const initial: TrainingStatus = {
        sessionId: session_id,
        state: 'pending',
        progress: 0,
        message: 'queued',
        error: null,
        pthPath: null,
        indexPath: null,
        logPath: null,
      };
      setJob(initial);
      startPoll(session_id);
    },
    [job, setJob, startPoll],
  );

  const cancel = useCallback(async (): Promise<void> => {
    if (!job) return;
    try {
      await tauriApi.cancelTraining(job.sessionId);
    } catch {
      /* ignore */
    }
  }, [job]);

  return { job, gpuInfo, gpuLoading, refreshGpu, start, cancel };
}
