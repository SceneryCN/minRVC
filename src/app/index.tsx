import { useCallback, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Activity,
  AudioWaveform,
  CircleCheck,
  Mic,
  RefreshCw,
  Settings2,
  Sliders,
  Sparkles,
  Speaker,
  TriangleAlert,
  Volume2,
} from 'lucide-react';
import { AudioMeter } from '@/components/audio-meter';
import { DeviceSelector } from '@/components/device-selector';
import { DspPanel } from '@/components/dsp-panel';
import { LiveToggle } from '@/components/live-toggle';
import { PitchControl } from '@/components/pitch-control';
import { SeparationPanel } from '@/components/separation-panel';
import { TabBar } from '@/components/tab-bar';
import { ThemeSwitcher } from '@/components/theme-switcher';
import { VoiceCard } from '@/components/voice-card';
import { VOICE_PRESETS } from '@/constants/voices';
import { useAppStore } from '@/hooks/use-app-store';
import { useAudioDevices } from '@/hooks/use-audio-devices';
import { useDsp } from '@/hooks/use-dsp';
import { useEngine } from '@/hooks/use-engine';
import { useVoiceModels } from '@/hooks/use-voice-models';
import type { VoiceId } from '@/types';
import { tauriApi } from '@/utils/tauri-api';
import styles from './styles.module.css';

export function App() {
  const { t } = useTranslation();
  const { refresh: refreshDevices } = useAudioDevices();
  const { refresh: refreshVoices } = useVoiceModels();
  const { start, stop } = useEngine();
  useDsp(); // 全局副作用：拉取/推送 DSP 配置 + 状态轮询

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

  const engineStatus = useAppStore((s) => s.engineStatus);
  const inputLevel = useAppStore((s) => s.inputLevel);
  const outputLevel = useAppStore((s) => s.outputLevel);
  const errorMessage = useAppStore((s) => s.errorMessage);

  const installedMap = useMemo(() => {
    const m = new Map<string, boolean>();
    for (const v of voices) m.set(v.id, v.installed);
    return m;
  }, [voices]);

  const handleSelectVoice = useCallback(
    (id: VoiceId) => {
      setSelectedVoice(id);
      const preset = VOICE_PRESETS.find((v) => v.id === id);
      if (preset) setPitchShift(preset.defaultPitch);
    },
    [setSelectedVoice, setPitchShift],
  );

  useEffect(() => {
    if (engineStatus !== 'Running') return;
    void tauriApi.setPitchShift(pitchShift).catch(() => {});
  }, [pitchShift, engineStatus]);

  useEffect(() => {
    if (engineStatus !== 'Running' || !selectedVoice) return;
    void tauriApi.setVoice(selectedVoice).catch(() => {});
  }, [selectedVoice, engineStatus]);

  const showVirtualCableHint =
    !!selectedVoice && !virtualCable && inputDevices.length > 0;

  const showMissingModel =
    !!selectedVoice && !(installedMap.get(selectedVoice) ?? false);

  return (
    <div className={styles.shell}>
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
                {VOICE_PRESETS.map((preset) => (
                  <VoiceCard
                    key={preset.id}
                    preset={preset}
                    selected={selectedVoice === preset.id}
                    installed={installedMap.get(preset.id) ?? false}
                    onSelect={handleSelectVoice}
                  />
                ))}
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
                  level={inputLevel}
                  Icon={Mic}
                />
                <AudioMeter
                  label={t('engine.outputLevel')}
                  level={outputLevel}
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
          </>
        ) : (
          <section className={styles.section}>
            <SeparationPanel />
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
          onClick={() => void refreshVoices()}
        >
          <RefreshCw />
          {t('app.refreshModels')}
        </button>
      </footer>
    </div>
  );
}
