import { useCallback, useEffect, useRef } from 'react';
import { tauriApi } from '@/utils/tauri-api';
import { useAppStore } from './use-app-store';

interface UseEngineResult {
  start: () => Promise<void>;
  stop: () => Promise<void>;
}

const METER_INTERVAL_MS = 80;
const STATUS_INTERVAL_MS = 500;

export function useEngine(): UseEngineResult {
  const selectedInput = useAppStore((s) => s.selectedInput);
  const selectedOutput = useAppStore((s) => s.selectedOutput);
  const selectedVoice = useAppStore((s) => s.selectedVoice);
  const pitchShift = useAppStore((s) => s.pitchShift);
  const setEngineStatus = useAppStore((s) => s.setEngineStatus);
  const setMeters = useAppStore((s) => s.setMeters);
  const setError = useAppStore((s) => s.setError);

  const meterTimerRef = useRef<number | null>(null);
  const statusTimerRef = useRef<number | null>(null);

  const start = useCallback(async () => {
    if (!selectedVoice) {
      setError('请先选择一个音色');
      return;
    }
    if (!selectedInput) {
      setError('请先选择麦克风');
      return;
    }
    if (!selectedOutput) {
      setError('请先选择输出设备');
      return;
    }
    try {
      setError(null);
      setEngineStatus('Starting');
      await tauriApi.startEngine({
        input_device: selectedInput,
        output_device: selectedOutput,
        voice_id: selectedVoice,
        pitch_shift: pitchShift,
      });
      setEngineStatus('Running');
    } catch (e) {
      setEngineStatus('Error');
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [selectedInput, selectedOutput, selectedVoice, pitchShift, setEngineStatus, setError]);

  const stop = useCallback(async () => {
    try {
      setEngineStatus('Stopping');
      await tauriApi.stopEngine();
      setEngineStatus('Stopped');
    } catch (e) {
      setEngineStatus('Error');
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [setEngineStatus, setError]);

  // 轮询电平 + 状态
  useEffect(() => {
    meterTimerRef.current = window.setInterval(async () => {
      try {
        const m = await tauriApi.getAudioMeter();
        setMeters(m.input_level, m.output_level);
      } catch {
        // 静默忽略
      }
    }, METER_INTERVAL_MS);

    statusTimerRef.current = window.setInterval(async () => {
      try {
        const s = await tauriApi.getEngineStatus();
        setEngineStatus(s.status);
      } catch {
        // 静默忽略
      }
    }, STATUS_INTERVAL_MS);

    return () => {
      if (meterTimerRef.current !== null) window.clearInterval(meterTimerRef.current);
      if (statusTimerRef.current !== null) window.clearInterval(statusTimerRef.current);
    };
  }, [setMeters, setEngineStatus]);

  return { start, stop };
}
