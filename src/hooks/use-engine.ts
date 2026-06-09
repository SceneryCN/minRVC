import { useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { tauriApi } from '@/utils/tauri-api';
import { useAppStore } from './use-app-store';

interface UseEngineResult {
  start: () => Promise<void>;
  stop: () => Promise<void>;
}

const METER_INTERVAL_MS = 100;
const STATUS_INTERVAL_MS = 500;

export function useEngine(): UseEngineResult {
  const { t } = useTranslation();
  const selectedInput = useAppStore((s) => s.selectedInput);
  const selectedOutput = useAppStore((s) => s.selectedOutput);
  const selectedVoice = useAppStore((s) => s.selectedVoice);
  const pitchShift = useAppStore((s) => s.pitchShift);
  const realtimeConfig = useAppStore((s) => s.realtimeConfig);
  const setEngineStatus = useAppStore((s) => s.setEngineStatus);
  const setMeters = useAppStore((s) => s.setMeters);
  const setError = useAppStore((s) => s.setError);
  const setRealtimeProfile = useAppStore((s) => s.setRealtimeProfile);
  const engineStatus = useAppStore((s) => s.engineStatus);

  const meterTimerRef = useRef<number | null>(null);
  const statusTimerRef = useRef<number | null>(null);

  const start = useCallback(async () => {
    if (!selectedVoice) {
      setError(t('engine.selectVoiceFirst'));
      return;
    }
    if (!selectedInput) {
      setError(t('engine.selectInputFirst'));
      return;
    }
    if (!selectedOutput) {
      setError(t('engine.selectOutputFirst'));
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
        realtime_config: realtimeConfig,
      });
      setEngineStatus('Running');
    } catch (e) {
      setEngineStatus('Error');
      setRealtimeProfile(null);
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [
    selectedInput,
    selectedOutput,
    selectedVoice,
    pitchShift,
    realtimeConfig,
    setEngineStatus,
    setError,
    t,
  ]);

  const stop = useCallback(async () => {
    try {
      setEngineStatus('Stopping');
      await tauriApi.stopEngine();
      setEngineStatus('Stopped');
      setRealtimeProfile(null);
    } catch (e) {
      setEngineStatus('Error');
      setRealtimeProfile(null);
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [setEngineStatus, setError, setRealtimeProfile]);

  // 轮询引擎状态
  useEffect(() => {
    statusTimerRef.current = window.setInterval(async () => {
      try {
        const s = await tauriApi.getEngineStatus();
        setEngineStatus(s.status);
        setRealtimeProfile(s.profile);
      } catch {
        // 静默忽略
      }
    }, STATUS_INTERVAL_MS);

    return () => {
      if (statusTimerRef.current !== null) window.clearInterval(statusTimerRef.current);
    };
  }, [setEngineStatus, setRealtimeProfile]);

  // 电平只在运行时轮询，避免空闲时持续刷新 React 状态。
  useEffect(() => {
    if (engineStatus !== 'Running') {
      setMeters(0, 0);
      setRealtimeProfile(null);
      return;
    }
    meterTimerRef.current = window.setInterval(async () => {
      try {
        const m = await tauriApi.getAudioMeter();
        setMeters(m.input_level, m.output_level);
      } catch {
        // 静默忽略
      }
    }, METER_INTERVAL_MS);

    return () => {
      if (meterTimerRef.current !== null) {
        window.clearInterval(meterTimerRef.current);
        meterTimerRef.current = null;
      }
    };
  }, [engineStatus, setMeters, setRealtimeProfile]);

  return { start, stop };
}
