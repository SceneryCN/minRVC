import { create } from 'zustand';
import type {
  AppTabId,
  AudioDeviceInfo,
  DspConfig,
  DspStatus,
  EngineStatus,
  SeparationStatus,
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

  separationJob: SeparationStatus | null;
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
  setSeparationJob: (job: SeparationStatus | null) => void;
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

  separationJob: null,

  setActiveTab: (tab) => set({ activeTab: tab }),
  setDevices: (input, output) => set({ inputDevices: input, outputDevices: output }),
  setSelectedInput: (name) => set({ selectedInput: name }),
  setSelectedOutput: (name) => set({ selectedOutput: name }),
  setVirtualCable: (dev) => set({ virtualCable: dev }),
  setVoices: (voices) => set({ voices }),
  setSelectedVoice: (voice) => set({ selectedVoice: voice }),
  setPitchShift: (semitones) => set({ pitchShift: semitones }),
  setEngineStatus: (s) => set({ engineStatus: s }),
  setMeters: (input, output) => set({ inputLevel: input, outputLevel: output }),
  setError: (message) => set({ errorMessage: message }),
  setDspConfig: (cfg) => set({ dspConfig: cfg }),
  patchDspConfig: (patch) =>
    set((s) => ({ dspConfig: { ...s.dspConfig, ...patch } })),
  setDspStatus: (status) => set({ dspStatus: status }),
  setSeparationJob: (job) => set({ separationJob: job }),
}));
