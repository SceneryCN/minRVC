import { useCallback, useEffect } from 'react';
import { tauriApi } from '@/utils/tauri-api';
import { useAppStore } from './use-app-store';

interface UseAudioDevicesResult {
  refresh: () => Promise<void>;
}

export function useAudioDevices(): UseAudioDevicesResult {
  const setDevices = useAppStore((s) => s.setDevices);
  const setVirtualCable = useAppStore((s) => s.setVirtualCable);
  const selectedInput = useAppStore((s) => s.selectedInput);
  const selectedOutput = useAppStore((s) => s.selectedOutput);
  const setSelectedInput = useAppStore((s) => s.setSelectedInput);
  const setSelectedOutput = useAppStore((s) => s.setSelectedOutput);
  const setError = useAppStore((s) => s.setError);

  const refresh = useCallback(async () => {
    try {
      const [inputs, outputs, vc] = await Promise.all([
        tauriApi.listInputDevices(),
        tauriApi.listOutputDevices(),
        tauriApi.detectVirtualCable(),
      ]);
      setDevices(inputs, outputs);
      setVirtualCable(vc);

      if (!selectedInput) {
        const def = inputs.find((d) => d.is_default) ?? inputs[0];
        if (def) setSelectedInput(def.name);
      }
      if (!selectedOutput && vc) {
        setSelectedOutput(vc.name);
      } else if (!selectedOutput) {
        const def = outputs.find((d) => d.is_default) ?? outputs[0];
        if (def) setSelectedOutput(def.name);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [selectedInput, selectedOutput, setDevices, setVirtualCable, setSelectedInput, setSelectedOutput, setError]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { refresh };
}
