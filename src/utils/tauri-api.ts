import { invoke } from '@tauri-apps/api/core';
import type {
  AudioDeviceInfo,
  AudioMeter,
  DspConfig,
  DspStatus,
  EngineStatusPayload,
  SeparationStatus,
  StartEnginePayload,
  VoiceModelInfo,
} from '@/types';

export const tauriApi = {
  listInputDevices: () => invoke<AudioDeviceInfo[]>('list_input_devices'),
  listOutputDevices: () => invoke<AudioDeviceInfo[]>('list_output_devices'),
  detectVirtualCable: () => invoke<AudioDeviceInfo | null>('detect_virtual_cable'),
  getAudioMeter: () => invoke<AudioMeter>('get_audio_meter'),

  startEngine: (payload: StartEnginePayload) =>
    invoke<void>('start_engine', { payload }),
  stopEngine: () => invoke<void>('stop_engine'),
  getEngineStatus: () => invoke<EngineStatusPayload>('get_engine_status'),
  setVoice: (voiceId: string) => invoke<void>('set_voice', { voiceId }),
  setPitchShift: (semitones: number) =>
    invoke<void>('set_pitch_shift', { semitones }),

  listVoiceModels: () => invoke<VoiceModelInfo[]>('list_voice_models'),
  importVoiceModel: (payload: {
    voice_id: string;
    pth_path: string;
    index_path: string | null;
  }) => invoke<VoiceModelInfo>('import_voice_model', { payload }),
  downloadPresetModel: (voiceId: string) =>
    invoke<VoiceModelInfo>('download_preset_model', { payload: { voice_id: voiceId } }),

  // ---------- DSP（降噪 + VAD） ----------
  getDspConfig: () => invoke<DspConfig>('get_dsp_config'),
  setDspConfig: (config: DspConfig) => invoke<void>('set_dsp_config', { config }),
  getDspStatus: () => invoke<DspStatus>('get_dsp_status'),

  // ---------- 离线人声分离（Demucs） ----------
  startSeparation: (payload: {
    input_path: string;
    model?: string;
    two_stems?: boolean;
  }) =>
    invoke<{ session_id: string }>('start_separation', { payload }),
  getSeparationStatus: (sessionId: string) =>
    invoke<SeparationStatus>('get_separation_status', { sessionId }),
  cancelSeparation: (sessionId: string) =>
    invoke<void>('cancel_separation', { sessionId }),
} as const;
