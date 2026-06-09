export type VoiceId = string;

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

export interface ImportVoiceModelPayload {
  voice_id: string;
  pth_path: string;
  index_path: string | null;
  display_name?: string;
  description?: string;
  category?: string;
  gender?: 'female' | 'male' | 'unknown';
  sample_rate?: number;
  recommended_pitch?: number;
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
  realtime_config?: RealtimeConfig;
}

export type F0Method = 'rmvpe' | 'fcpe' | 'crepe';
export type SampleRateMode = 'device' | 'custom';

export interface RealtimeConfig {
  responseThreshold: number;
  voiceThickness: number;
  indexRate: number;
  rmsMixRate: number;
  protect: number;
  loudness: number;
  f0Method: F0Method;
  f0FilterRadius: number;
  resampleSr: number;
  sampleRateMode: SampleRateMode;
  customSampleRate: number;
  chunkSize: number;
  harvestProcesses: number;
  crossfadeMs: number;
  extraInferenceMs: number;
  bufferMs: number;
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

export type TrainingState =
  | 'pending'
  | 'running'
  | 'done'
  | 'failed'
  | 'cancelled';

export interface TrainingStatus {
  sessionId: string;
  state: TrainingState;
  progress: number;
  message: string | null;
  error: string | null;
  pthPath: string | null;
  indexPath: string | null;
  logPath: string | null;
}

export interface TrainingGpuInfo {
  available: boolean;
  backend: 'cuda' | 'mps' | 'cpu' | string;
  name: string;
}

export interface StartTrainingPayload {
  dataset_dir: string;
  voice_name: string;
  training_package_dir?: string | null;
  epochs?: number;
  batch_size?: number;
  sample_rate?: number;
  f0_method?: F0Method;
  save_every_epoch?: number;
  model_version?: 'v1' | 'v2';
  gpu_ids?: string | null;
  cache_gpu?: boolean;
  save_latest_only?: boolean;
  save_every_weights?: boolean;
  pretrained_g?: string | null;
  pretrained_d?: string | null;
  use_gpu?: boolean;
}

export interface F0ModelStatus {
  rmvpeInstalled: boolean;
  rmvpePath: string | null;
  rmvpeDownloadUrl: string;
}

export type AppTabId = 'voice' | 'lab' | 'train' | 'help';
