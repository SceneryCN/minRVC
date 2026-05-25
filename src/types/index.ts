export type VoiceId = 'yujie' | 'loli' | 'shaonian' | 'naiqing' | 'qingshu';

export interface AudioDeviceInfo {
  name: string;
  is_default: boolean;
  is_virtual_cable: boolean;
  sample_rate: number;
  channels: number;
}

export interface VoiceModelInfo {
  id: string;
  display_name: string;
  description: string;
  category: string;
  gender: 'female' | 'male' | 'unknown';
  sample_rate: number;
  pth_path: string | null;
  index_path: string | null;
  installed: boolean;
  recommended_pitch: number;
  source_url: string | null;
}

export type EngineStatus = 'Stopped' | 'Starting' | 'Running' | 'Stopping' | 'Error';

export interface EngineStatusPayload {
  status: EngineStatus;
  current_voice: string | null;
  pitch_shift: number;
}

export interface AudioMeter {
  input_level: number;
  output_level: number;
}

export interface StartEnginePayload {
  input_device: string | null;
  output_device: string | null;
  voice_id: string;
  pitch_shift?: number;
}

/**
 * 实时 DSP（降噪 + VAD）配置。
 * 与 Rust 端 `audio::dsp::DspConfig` 对齐（serde rename_all camelCase）。
 */
export interface DspConfig {
  denoiseEnabled: boolean;
  denoiseStrength: number;
  vadEnabled: boolean;
  vadThreshold: number;
  vadMinSpeechMs: number;
  vadMinSilenceMs: number;
}

export interface DspStatus {
  speaking: boolean;
  vadProbability: number;
  denoiseActive: boolean;
  vadAvailable: boolean;
}

export type SeparationState =
  | 'pending'
  | 'running'
  | 'done'
  | 'failed'
  | 'cancelled';

export interface SeparationStatus {
  sessionId: string;
  state: SeparationState;
  progress: number;
  message: string | null;
  vocalsPath: string | null;
  otherPath: string | null;
  error: string | null;
}

export type AppTabId = 'voice' | 'lab';
