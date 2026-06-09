import { create } from 'zustand';
import type {
  AppTabId,
  AudioDeviceInfo,
  DspConfig,
  DspStatus,
  EngineStatus,
  RealtimeConfig,
  SeparationStatus,
  TrainingStatus,
  VoiceId,
  VoiceModelInfo,
} from '@/types';

const DEFAULT_DSP_CONFIG: DspConfig = {
  denoiseEnabled: true,
  denoiseStrength: 1.0,
  vadEnabled: true,
  vadThreshold: 0.5,
  vadMinSpeechMs: 250,
  vadMinSilenceMs: 250,
};

const DEFAULT_DSP_STATUS: DspStatus = {
  speaking: false,
  vadProbability: 0,
  denoiseActive: false,
  vadAvailable: false,
};

export const DEFAULT_REALTIME_CONFIG: RealtimeConfig = {
  responseThreshold: 0.5,
  voiceThickness: 0,
  indexRate: 0.5,
  rmsMixRate: 0.25,
  protect: 0.33,
  loudness: 1,
  f0Method: 'rmvpe',
  f0FilterRadius: 3,
  resampleSr: 0,
  sampleRateMode: 'device',
  customSampleRate: 48000,
  chunkSize: 4096,
  harvestProcesses: 2,
  crossfadeMs: 10,
  extraInferenceMs: 2500,
  bufferMs: 500,
};

interface AppStoreState {
  activeTab: AppTabId;

  inputDevices: AudioDeviceInfo[];
  outputDevices: AudioDeviceInfo[];
  selectedInput: string | null;
  selectedOutput: string | null;
  virtualCable: AudioDeviceInfo | null;

  voices: VoiceModelInfo[];
  selectedVoice: VoiceId | null;
  pitchShift: number;

  engineStatus: EngineStatus;
  inputLevel: number;
  outputLevel: number;
  errorMessage: string | null;

  dspConfig: DspConfig;
  dspStatus: DspStatus;
  realtimeConfig: RealtimeConfig;

  separationJob: SeparationStatus | null;
  trainingJob: TrainingStatus | null;
}

interface AppStoreActions {
  setActiveTab: (tab: AppTabId) => void;
  setDevices: (input: AudioDeviceInfo[], output: AudioDeviceInfo[]) => void;
  setSelectedInput: (name: string | null) => void;
  setSelectedOutput: (name: string | null) => void;
  setVirtualCable: (dev: AudioDeviceInfo | null) => void;
  setVoices: (voices: VoiceModelInfo[]) => void;
  setSelectedVoice: (voice: VoiceId | null) => void;
  setPitchShift: (semitones: number) => void;
  setEngineStatus: (s: EngineStatus) => void;
  setMeters: (input: number, output: number) => void;
  setError: (message: string | null) => void;
  setDspConfig: (cfg: DspConfig) => void;
  patchDspConfig: (patch: Partial<DspConfig>) => void;
  setDspStatus: (status: DspStatus) => void;
  setRealtimeConfig: (cfg: RealtimeConfig) => void;
  patchRealtimeConfig: (patch: Partial<RealtimeConfig>) => void;
  setSeparationJob: (job: SeparationStatus | null) => void;
  setTrainingJob: (job: TrainingStatus | null) => void;
}

export const useAppStore = create<AppStoreState & AppStoreActions>((set) => ({
  activeTab: 'voice',

  inputDevices: [],
  outputDevices: [],
  selectedInput: null,
  selectedOutput: null,
  virtualCable: null,

  voices: [],
  selectedVoice: null,
  pitchShift: 0,

  engineStatus: 'Stopped',
  inputLevel: 0,
  outputLevel: 0,
  errorMessage: null,

  dspConfig: DEFAULT_DSP_CONFIG,
  dspStatus: DEFAULT_DSP_STATUS,
  realtimeConfig: DEFAULT_REALTIME_CONFIG,

  separationJob: null,
  trainingJob: null,

  setActiveTab: (tab) => set({ activeTab: tab }),
  setDevices: (input, output) => set({ inputDevices: input, outputDevices: output }),
  setSelectedInput: (name) => set({ selectedInput: name }),
  setSelectedOutput: (name) => set({ selectedOutput: name }),
  setVirtualCable: (dev) => set({ virtualCable: dev }),
  setVoices: (voices) => set({ voices }),
  setSelectedVoice: (voice) => set({ selectedVoice: voice }),
  setPitchShift: (semitones) => set({ pitchShift: semitones }),
  setEngineStatus: (s) => set({ engineStatus: s }),
  setMeters: (input, output) =>
    set((s) => {
      if (
        Math.abs(s.inputLevel - input) < 0.004 &&
        Math.abs(s.outputLevel - output) < 0.004
      ) {
        return s;
      }
      return { inputLevel: input, outputLevel: output };
    }),
  setError: (message) => set({ errorMessage: message }),
  setDspConfig: (cfg) => set({ dspConfig: cfg }),
  patchDspConfig: (patch) =>
    set((s) => ({ dspConfig: { ...s.dspConfig, ...patch } })),
  setDspStatus: (status) =>
    set((s) => {
      if (
        s.dspStatus.speaking === status.speaking &&
        s.dspStatus.denoiseActive === status.denoiseActive &&
        s.dspStatus.vadAvailable === status.vadAvailable &&
        Math.abs(s.dspStatus.vadProbability - status.vadProbability) < 0.004
      ) {
        return s;
      }
      return { dspStatus: status };
    }),
  setRealtimeConfig: (cfg) => set({ realtimeConfig: cfg }),
  patchRealtimeConfig: (patch) =>
    set((s) => ({ realtimeConfig: { ...s.realtimeConfig, ...patch } })),
  setSeparationJob: (job) => set({ separationJob: job }),
  setTrainingJob: (job) => set({ trainingJob: job }),
}));
