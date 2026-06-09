import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { open as openDialog } from '@tauri-apps/plugin-dialog';
import {
  Activity,
  AudioWaveform,
  CircleCheck,
  Mic2,
  Mic,
  RefreshCw,
  Settings2,
  Sliders,
  SlidersHorizontal,
  Sparkles,
  Speaker,
  TriangleAlert,
  Volume2,
} from 'lucide-react';
import { AudioMeter } from '@/components/audio-meter';
import { CustomVoiceForm } from '@/components/custom-voice-form';
import { DeviceSelector } from '@/components/device-selector';
import { DspPanel } from '@/components/dsp-panel';
import { HelpPanel } from '@/components/help-panel';
import { LanguageSwitcher } from '@/components/language-switcher';
import { LiveToggle } from '@/components/live-toggle';
import { PitchControl } from '@/components/pitch-control';
import { RealtimeSettings } from '@/components/realtime-settings';
import { SeparationPanel } from '@/components/separation-panel';
import { TabBar } from '@/components/tab-bar';
import { ThemeSwitcher } from '@/components/theme-switcher';
import { TrainingPanel } from '@/components/training-panel';
import { VoiceCard } from '@/components/voice-card';
import { VOICE_PRESETS, VOICE_PRESET_MAP } from '@/constants/voices';
import { useAppStore } from '@/hooks/use-app-store';
import { useAudioDevices } from '@/hooks/use-audio-devices';
import { useDsp } from '@/hooks/use-dsp';
import { useEngine } from '@/hooks/use-engine';
import { useVoiceModels } from '@/hooks/use-voice-models';
import type { VoiceModelInfo } from '@/types';
import { tauriApi } from '@/utils/tauri-api';
import styles from './styles.module.css';

export function App() {
  const { t } = useTranslation();
  const { refresh: refreshDevices } = useAudioDevices();
  const { refresh: refreshVoices } = useVoiceModels();
  const { start, stop } = useEngine();
  const refreshDoneTimerRef = useRef<number | null>(null);
  const realtimeConfigTimerRef = useRef<number | null>(null);
  const [modelRefreshState, setModelRefreshState] = useState<
    'idle' | 'loading' | 'done'
  >('idle');

  const activeTab = useAppStore((s) => s.activeTab);
  const setActiveTab = useAppStore((s) => s.setActiveTab);

  const inputDevices = useAppStore((s) => s.inputDevices);
  const outputDevices = useAppStore((s) => s.outputDevices);
  const selectedInput = useAppStore((s) => s.selectedInput);
  const selectedOutput = useAppStore((s) => s.selectedOutput);
  const setSelectedInput = useAppStore((s) => s.setSelectedInput);
  const setSelectedOutput = useAppStore((s) => s.setSelectedOutput);
  const virtualCable = useAppStore((s) => s.virtualCable);

  const voices = useAppStore((s) => s.voices);
  const selectedVoice = useAppStore((s) => s.selectedVoice);
  const setSelectedVoice = useAppStore((s) => s.setSelectedVoice);
  const pitchShift = useAppStore((s) => s.pitchShift);
  const setPitchShift = useAppStore((s) => s.setPitchShift);
  const realtimeConfig = useAppStore((s) => s.realtimeConfig);

  const engineStatus = useAppStore((s) => s.engineStatus);
  const errorMessage = useAppStore((s) => s.errorMessage);

  const installedMap = useMemo(() => {
    const m = new Map<string, boolean>();
    for (const v of voices) m.set(v.id, v.installed);
    return m;
  }, [voices]);

  const displayVoices = useMemo<VoiceModelInfo[]>(() => {
    if (voices.length > 0) return voices;
    return VOICE_PRESETS.map((preset) => ({
      id: preset.id,
      display_name: t(`${preset.i18nKey}.name`),
      description: t(`${preset.i18nKey}.desc`),
      category: preset.gender,
      gender: preset.gender,
      sample_rate: 40_000,
      pth_path: null,
      index_path: null,
      installed: false,
      recommended_pitch: preset.defaultPitch,
      source_url: null,
    }));
  }, [t, voices]);

  const handleSelectVoice = useCallback(
    (id: string) => {
      setSelectedVoice(id);
      const voice = displayVoices.find((v) => v.id === id);
      if (voice) setPitchShift(voice.recommended_pitch);
    },
    [setSelectedVoice, setPitchShift, displayVoices],
  );

  const handleImportVoice = useCallback(
    async (voiceId: string) => {
      try {
        const pickedPth = await openDialog({
          multiple: false,
          directory: false,
          filters: [{ name: 'RVC model', extensions: ['pth'] }],
        });
        if (typeof pickedPth !== 'string') return;
        const pickedIndex = await openDialog({
          multiple: false,
          directory: false,
          title: t('voice.pickIndexOptional'),
          filters: [{ name: 'RVC index', extensions: ['index'] }],
        });
        await tauriApi.importVoiceModel({
          voice_id: voiceId,
          pth_path: pickedPth,
          index_path: typeof pickedIndex === 'string' ? pickedIndex : null,
        });
        await refreshVoices();
      } catch (e) {
        useAppStore.getState().setError(e instanceof Error ? e.message : String(e));
      }
    },
    [refreshVoices, t],
  );

  const handleCustomImported = useCallback(
    async (voiceId: string) => {
      await refreshVoices();
      setSelectedVoice(voiceId);
    },
    [refreshVoices, setSelectedVoice],
  );

  const handleRefreshVoices = useCallback(async () => {
    if (modelRefreshState === 'loading') return;
    if (refreshDoneTimerRef.current !== null) {
      window.clearTimeout(refreshDoneTimerRef.current);
      refreshDoneTimerRef.current = null;
    }
    setModelRefreshState('loading');
    try {
      await refreshVoices();
      setModelRefreshState('done');
      refreshDoneTimerRef.current = window.setTimeout(() => {
        setModelRefreshState('idle');
        refreshDoneTimerRef.current = null;
      }, 1800);
    } catch (e) {
      setModelRefreshState('idle');
      useAppStore.getState().setError(e instanceof Error ? e.message : String(e));
    }
  }, [modelRefreshState, refreshVoices]);

  useEffect(() => {
    return () => {
      if (refreshDoneTimerRef.current !== null) {
        window.clearTimeout(refreshDoneTimerRef.current);
      }
      if (realtimeConfigTimerRef.current !== null) {
        window.clearTimeout(realtimeConfigTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (engineStatus !== 'Running') return;
    void tauriApi.setPitchShift(pitchShift).catch(() => {});
  }, [pitchShift, engineStatus]);

  useEffect(() => {
    if (engineStatus !== 'Running' || !selectedVoice) return;
    void tauriApi.setVoice(selectedVoice).catch(() => {});
  }, [selectedVoice, engineStatus]);

  useEffect(() => {
    if (engineStatus !== 'Running') return;
    if (realtimeConfigTimerRef.current !== null) {
      window.clearTimeout(realtimeConfigTimerRef.current);
    }
    realtimeConfigTimerRef.current = window.setTimeout(() => {
      void tauriApi.setRealtimeConfig(realtimeConfig).catch(() => {});
      realtimeConfigTimerRef.current = null;
    }, 140);
    return () => {
      if (realtimeConfigTimerRef.current !== null) {
        window.clearTimeout(realtimeConfigTimerRef.current);
        realtimeConfigTimerRef.current = null;
      }
    };
  }, [realtimeConfig, engineStatus]);

  const showVirtualCableHint =
    !!selectedVoice && !virtualCable && inputDevices.length > 0;

  const showMissingModel =
    !!selectedVoice && !(installedMap.get(selectedVoice) ?? false);

  return (
    <div className={styles.shell}>
      <DspRuntime />
      <div className={styles.splash} aria-hidden>
        <div className={styles.splashMark}>
          <AudioWaveform />
        </div>
        <div className={styles.splashTitle}>Fuck RVC</div>
      </div>
      <header className={styles.header}>
        <div className={styles.brand}>
          <span className={styles.brandIcon} aria-hidden>
            <AudioWaveform />
          </span>
          <div className={styles.brandText}>
            <h1 className={styles.brandTitle}>{t('app.title')}</h1>
            <span className={styles.brandSubtitle}>{t('app.subtitle')}</span>
          </div>
        </div>
        <div className={styles.headerCenter}>
          <TabBar active={activeTab} onChange={setActiveTab} />
        </div>
        <div className={styles.headerRight}>
          <span className={styles.statusPill} data-status={engineStatus}>
            <span className={styles.statusDot} />
            {t(`status.${engineStatus}`)}
          </span>
          <LanguageSwitcher />
          <ThemeSwitcher />
        </div>
      </header>

      <main className={styles.body}>
        {activeTab === 'voice' ? (
          <>
            <section className={styles.section}>
              <div className={styles.sectionHeader}>
                <h2 className={styles.sectionTitle}>
                  <Sparkles />
                  {t('app.sectionVoice')}
                </h2>
              </div>
              <div className={styles.voiceGrid}>
                {displayVoices.map((voice) => {
                  const preset = VOICE_PRESET_MAP.get(voice.id);
                  return (
                  <VoiceCard
                    key={voice.id}
                    id={voice.id}
                    name={getVoiceName(voice, preset?.i18nKey, t)}
                    description={getVoiceDescription(voice, preset?.i18nKey, t)}
                    pitch={voice.recommended_pitch}
                    color={preset?.colorVar ?? 'var(--color-info)'}
                    Icon={preset?.Icon ?? Mic2}
                    selected={selectedVoice === voice.id}
                    installed={installedMap.get(voice.id) ?? false}
                    onSelect={handleSelectVoice}
                    onImport={handleImportVoice}
                  />
                  );
                })}
              </div>
              <div className={styles.customVoiceWrap}>
                <CustomVoiceForm onImported={handleCustomImported} />
              </div>
              {showMissingModel && (
                <p className={styles.alert}>
                  <TriangleAlert />
                  {t('voice.needModel')}
                </p>
              )}
            </section>

            <section className={styles.section}>
              <div className={styles.sectionHeader}>
                <h2 className={styles.sectionTitle}>
                  <Settings2 />
                  {t('app.sectionDevice')}
                </h2>
              </div>
              <div className={styles.devicesRow}>
                <DeviceSelector
                  label={t('device.inputLabel')}
                  Icon={Mic}
                  placeholder={t('device.selectInput')}
                  devices={inputDevices}
                  value={selectedInput}
                  onChange={setSelectedInput}
                  onRefresh={() => void refreshDevices()}
                />
                <DeviceSelector
                  label={t('device.outputLabel')}
                  Icon={Speaker}
                  placeholder={t('device.selectOutput')}
                  devices={outputDevices}
                  value={selectedOutput}
                  onChange={setSelectedOutput}
                  onRefresh={() => void refreshDevices()}
                />
              </div>
              {virtualCable ? (
                <p className={styles.alert} data-kind="success">
                  <CircleCheck />
                  {t('device.virtualCableFound', { name: virtualCable.name })}
                </p>
              ) : showVirtualCableHint ? (
                <p className={styles.alert}>
                  <TriangleAlert />
                  {t('device.virtualCableNotFound')}
                </p>
              ) : null}
            </section>

            <section className={styles.section}>
              <div className={styles.sectionHeader}>
                <h2 className={styles.sectionTitle}>
                  <Activity />
                  {t('app.sectionControl')}
                </h2>
              </div>
              <div className={styles.controlBar}>
                <LiveToggle status={engineStatus} onStart={start} onStop={stop} />
                <PitchControl value={pitchShift} onChange={setPitchShift} />
              </div>
              <div className={styles.metersRow}>
                <AudioMeter
                  label={t('engine.inputLevel')}
                  channel="input"
                  Icon={Mic}
                />
                <AudioMeter
                  label={t('engine.outputLevel')}
                  channel="output"
                  Icon={Volume2}
                />
              </div>
              {errorMessage && (
                <p className={styles.alert} data-kind="error">
                  <TriangleAlert />
                  {t('error.generic', { message: errorMessage })}
                </p>
              )}
            </section>

            <section className={styles.section}>
              <div className={styles.sectionHeader}>
                <h2 className={styles.sectionTitle}>
                  <Sliders />
                  {t('dsp.sectionTitle')}
                </h2>
              </div>
              <DspPanel />
            </section>

            <section className={styles.section}>
              <div className={styles.sectionHeader}>
                <h2 className={styles.sectionTitle}>
                  <SlidersHorizontal />
                  {t('realtime.sectionTitle')}
                </h2>
              </div>
              <RealtimeSettings />
            </section>
          </>
        ) : activeTab === 'lab' ? (
          <section className={styles.section}>
            <SeparationPanel />
          </section>
        ) : activeTab === 'train' ? (
          <section className={styles.section}>
            <TrainingPanel />
          </section>
        ) : (
          <section className={styles.section}>
            <HelpPanel />
          </section>
        )}
      </main>

      <footer className={styles.footer}>
        <div className={styles.guide}>
          {[1, 2, 3, 4].map((n) => (
            <span key={n} className={styles.guideStep}>
              <span className={styles.guideStepNum}>{n}</span>
              {t(`guide.step${n}`)}
            </span>
          ))}
        </div>
        <button
          type="button"
          className={styles.refreshBtn}
          data-state={modelRefreshState}
          disabled={modelRefreshState === 'loading'}
          aria-live="polite"
          onClick={() => void handleRefreshVoices()}
        >
          {modelRefreshState === 'done' ? <CircleCheck /> : <RefreshCw />}
          {t(
            modelRefreshState === 'loading'
              ? 'app.refreshingModels'
              : modelRefreshState === 'done'
                ? 'app.modelsRefreshed'
                : 'app.refreshModels',
          )}
        </button>
      </footer>
    </div>
  );
}

const DspRuntime = memo(function DspRuntime() {
  useDsp(); // 全局副作用：拉取/推送 DSP 配置 + 状态轮询
  return null;
});

function getVoiceName(
  voice: VoiceModelInfo,
  i18nKey: string | undefined,
  t: ReturnType<typeof useTranslation>['t'],
) {
  return i18nKey ? t(`${i18nKey}.name`) : voice.display_name;
}

function getVoiceDescription(
  voice: VoiceModelInfo,
  i18nKey: string | undefined,
  t: ReturnType<typeof useTranslation>['t'],
) {
  return i18nKey ? t(`${i18nKey}.desc`) : voice.description;
}
