import { useCallback, useEffect } from 'react';
import { tauriApi } from '@/utils/tauri-api';
import { useAppStore } from './use-app-store';

interface UseVoiceModelsResult {
  refresh: () => Promise<void>;
}

export function useVoiceModels(): UseVoiceModelsResult {
  const setVoices = useAppStore((s) => s.setVoices);
  const setError = useAppStore((s) => s.setError);

  const refresh = useCallback(async () => {
    try {
      const list = await tauriApi.listVoiceModels();
      setVoices(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [setVoices, setError]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { refresh };
}
