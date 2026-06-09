import { memo, useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { open as openDialog } from '@tauri-apps/plugin-dialog';
import { open as openShell } from '@tauri-apps/plugin-shell';
import {
  CheckCircle,
  Cpu,
  Download,
  Gauge,
  SlidersHorizontal,
  Sparkles,
  Upload,
  Waves,
} from 'lucide-react';
import { useAppStore } from '@/hooks/use-app-store';
import type { F0Method, F0ModelStatus, RealtimeConfig, RealtimeProfile, TrainingGpuInfo } from '@/types';
import { tauriApi } from '@/utils/tauri-api';
import styles from './styles.module.css';

const F0_OPTIONS: Array<{ value: RealtimeConfig['f0Method']; key: string }> = [
  { value: 'rmvpe', key: 'rmvpe' },
  { value: 'fcpe', key: 'fcpe' },
  { value: 'crepe', key: 'crepe' },
];

type PerformancePresetId = 'cudaHigh' | 'cudaNormal' | 'cpuDebug';

const PERFORMANCE_PRESETS: Record<
  PerformancePresetId,
  Partial<RealtimeConfig>
> = {
  cudaHigh: {
    f0Method: 'rmvpe',
    chunkSize: 2048,
    bufferMs: 250,
    crossfadeMs: 8,
    extraInferenceMs: 1400,
    indexRate: 0.5,
    rmsMixRate: 0.25,
  },
  cudaNormal: {
    f0Method: 'fcpe',
    chunkSize: 3072,
    bufferMs: 400,
    crossfadeMs: 10,
    extraInferenceMs: 1000,
    indexRate: 0.35,
    rmsMixRate: 0.2,
  },
  cpuDebug: {
    f0Method: 'fcpe',
    chunkSize: 6144,
    bufferMs: 900,
    crossfadeMs: 18,
    extraInferenceMs: 700,
    indexRate: 0.0,
    rmsMixRate: 0.15,
  },
};

export const RealtimeSettings = memo(function RealtimeSettings() {
  const { t } = useTranslation();
  const cfg = useAppStore((s) => s.realtimeConfig);
  const patchDsp = useAppStore((s) => s.patchDspConfig);
  const patch = useAppStore((s) => s.patchRealtimeConfig);
  const engineStatus = useAppStore((s) => s.engineStatus);
  const running = engineStatus === 'Running' || engineStatus === 'Starting';
  const [f0Status, setF0Status] = useState<F0ModelStatus | null>(null);
  const [gpuInfo, setGpuInfo] = useState<TrainingGpuInfo | null>(null);
  const profile = useAppStore((s) => s.realtimeProfile);

  const refreshF0Status = useCallback(async () => {
    try {
      setF0Status(await tauriApi.getF0ModelStatus());
    } catch {
      setF0Status(null);
    }
  }, []);

  useEffect(() => {
    void refreshF0Status();
  }, [refreshF0Status]);

  useEffect(() => {
    let cancelled = false;
    void tauriApi
      .getTrainingGpu()
      .then((info) => {
        if (!cancelled) setGpuInfo(info);
      })
      .catch(() => {
        if (!cancelled) setGpuInfo(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const recommendedPreset = pickRecommendedPreset(gpuInfo);

  const applyPreset = useCallback(
    (preset: PerformancePresetId) => {
      const next = PERFORMANCE_PRESETS[preset];
      patch(next);
    },
    [patch],
  );

  const handleImportRmvpe = useCallback(async () => {
    const picked = await openDialog({
      multiple: false,
      directory: false,
      filters: [{ name: 'RMVPE model', extensions: ['pt', 'pth'] }],
    });
    if (typeof picked !== 'string') return;
    setF0Status(await tauriApi.importF0Model('rmvpe', picked));
  }, []);

  const handleOpenRmvpeDownload = useCallback(async () => {
    const url =
      f0Status?.rmvpeDownloadUrl ??
      'https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/rmvpe.pt';
    await openShell(url);
  }, [f0Status]);

  return (
    <div className={styles.panel}>
      <div className={styles.group}>
        <div className={styles.groupHead}>
          <SlidersHorizontal />
          <div>
            <h3>{t('realtime.voiceTitle')}</h3>
            <p>{t('realtime.voiceDesc')}</p>
          </div>
        </div>
        <SettingSlider
          label={t('realtime.responseThreshold')}
          hint={t('realtime.responseThresholdHint')}
          value={cfg.responseThreshold}
          min={0.1}
          max={0.9}
          step={0.05}
          format={(v) => v.toFixed(2)}
          onChange={(responseThreshold) => {
            patch({ responseThreshold });
            patchDsp({ vadThreshold: responseThreshold });
          }}
        />
        <SettingSlider
          label={t('realtime.voiceThickness')}
          hint={t('realtime.voiceThicknessHint')}
          value={cfg.voiceThickness}
          min={-1}
          max={1}
          step={0.05}
          format={(v) =>
            v === 0
              ? '0'
              : v > 0
                ? `${t('realtime.thick')} ${v.toFixed(2)}`
                : `${t('realtime.thin')} ${Math.abs(v).toFixed(2)}`
          }
          onChange={(voiceThickness) => patch({ voiceThickness })}
        />
        <SettingSlider
          label={t('realtime.indexRate')}
          hint={t('realtime.indexRateHint')}
          value={cfg.indexRate}
          min={0}
          max={1}
          step={0.05}
          format={(v) => `${Math.round(v * 100)}%`}
          onChange={(indexRate) => patch({ indexRate })}
        />
        <SettingSlider
          label={t('realtime.rmsMixRate')}
          hint={t('realtime.rmsMixRateHint')}
          value={cfg.rmsMixRate}
          min={0}
          max={1}
          step={0.05}
          format={(v) => `${Math.round(v * 100)}%`}
          onChange={(rmsMixRate) => patch({ rmsMixRate })}
        />
        <SettingSlider
          label={t('realtime.protect')}
          hint={t('realtime.protectHint')}
          value={cfg.protect}
          min={0}
          max={0.5}
          step={0.01}
          format={(v) => v.toFixed(2)}
          onChange={(protect) => patch({ protect })}
        />
        <SettingSlider
          label={t('realtime.loudness')}
          hint={t('realtime.loudnessHint')}
          value={cfg.loudness}
          min={0}
          max={2}
          step={0.05}
          format={(v) => `${Math.round(v * 100)}%`}
          onChange={(loudness) => patch({ loudness })}
        />
      </div>

      <div className={styles.group}>
        <div className={styles.groupHead}>
          <Waves />
          <div>
            <h3>{t('realtime.pitchTitle')}</h3>
            <p>{t('realtime.pitchDesc')}</p>
          </div>
        </div>
        <label className={styles.selectField}>
          <span>{t('realtime.f0Method')}</span>
          <select
            value={cfg.f0Method}
            onChange={(e) =>
              patch({ f0Method: e.target.value as RealtimeConfig['f0Method'] })
            }
          >
            {F0_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {t(`realtime.f0.${option.key}`)}
              </option>
            ))}
          </select>
        </label>
        <div className={styles.f0ModelBox}>
          <div className={styles.f0ModelState} data-installed={f0Status?.rmvpeInstalled || undefined}>
            <CheckCircle />
            <div>
              <strong>
                {f0Status?.rmvpeInstalled
                  ? t('realtime.f0ModelInstalled')
                  : t('realtime.f0ModelMissing')}
              </strong>
              <span title={f0Status?.rmvpePath ?? undefined}>
                {f0Status?.rmvpePath ?? t('realtime.f0ModelDesc')}
              </span>
            </div>
          </div>
          <div className={styles.f0ModelActions}>
            <button type="button" onClick={() => void handleOpenRmvpeDownload()}>
              <Download />
              {t('realtime.downloadRmvpe')}
            </button>
            <button type="button" onClick={() => void handleImportRmvpe()}>
              <Upload />
              {t('realtime.importRmvpe')}
            </button>
          </div>
        </div>
        <p className={styles.inlineHint}>{t('realtime.f0GpuHint')}</p>
        <SettingSlider
          label={t('realtime.f0FilterRadius')}
          hint={t('realtime.f0FilterRadiusHint')}
          value={cfg.f0FilterRadius}
          min={0}
          max={7}
          step={1}
          format={(v) => `${Math.round(v)}`}
          onChange={(f0FilterRadius) =>
            patch({ f0FilterRadius: Math.round(f0FilterRadius) })
          }
        />
        <div className={styles.sampleRateRow}>
          <label className={styles.selectField}>
            <span>{t('realtime.sampleRateMode')}</span>
            <select
              value={cfg.sampleRateMode}
              disabled={running}
              onChange={(e) =>
                patch({
                  sampleRateMode: e.target.value as RealtimeConfig['sampleRateMode'],
                })
              }
            >
              <option value="device">{t('realtime.sampleRateDevice')}</option>
              <option value="custom">{t('realtime.sampleRateCustom')}</option>
            </select>
          </label>
          <label className={styles.selectField}>
            <span>{t('realtime.customSampleRate')}</span>
            <select
              value={cfg.customSampleRate}
              disabled={running || cfg.sampleRateMode === 'device'}
              onChange={(e) => patch({ customSampleRate: Number(e.target.value) })}
            >
              {[16000, 32000, 44100, 48000, 96000].map((sr) => (
                <option key={sr} value={sr}>
                  {sr.toLocaleString()} Hz
                </option>
              ))}
            </select>
          </label>
          <label className={styles.selectField}>
            <span>{t('realtime.resampleSr')}</span>
            <select
              value={cfg.resampleSr}
              onChange={(e) => patch({ resampleSr: Number(e.target.value) })}
            >
              <option value={0}>{t('realtime.resampleOff')}</option>
              {[16000, 32000, 40000, 44100, 48000].map((sr) => (
                <option key={sr} value={sr}>
                  {sr.toLocaleString()} Hz
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className={styles.inlineHint}>{t('realtime.resampleHint')}</p>
      </div>

      <div className={styles.group}>
        <div className={styles.groupHead}>
          <Cpu />
          <div>
            <h3>{t('realtime.performanceTitle')}</h3>
            <p>{t('realtime.performanceDesc')}</p>
          </div>
        </div>
        <div className={styles.presetRow} aria-label={t('realtime.presets')}>
          {(Object.keys(PERFORMANCE_PRESETS) as PerformancePresetId[]).map((preset) => (
            <button
              key={preset}
              type="button"
              className={styles.presetBtn}
              data-recommended={preset === recommendedPreset || undefined}
              disabled={running}
              onClick={() => applyPreset(preset)}
            >
              {preset === recommendedPreset ? <Sparkles /> : null}
              {t(`realtime.preset.${preset}`)}
            </button>
          ))}
        </div>
        <SettingSlider
          label={t('realtime.chunkSize')}
          hint={t('realtime.chunkSizeHint')}
          value={cfg.chunkSize}
          min={1024}
          max={8192}
          step={512}
          disabled={running}
          format={(v) => t('realtime.samplesValue', { value: Math.round(v) })}
          onChange={(chunkSize) => patch({ chunkSize: Math.round(chunkSize) })}
        />
        <SettingSlider
          label={t('realtime.bufferMs')}
          hint={t('realtime.bufferMsHint')}
          value={cfg.bufferMs}
          min={100}
          max={1500}
          step={50}
          disabled={running}
          format={(v) => t('realtime.msValue', { value: Math.round(v) })}
          onChange={(bufferMs) => patch({ bufferMs: Math.round(bufferMs) })}
        />
        <SettingSlider
          label={t('realtime.crossfadeMs')}
          hint={t('realtime.crossfadeMsHint')}
          value={cfg.crossfadeMs}
          min={2}
          max={80}
          step={1}
          format={(v) => t('realtime.msValue', { value: Math.round(v) })}
          onChange={(crossfadeMs) => patch({ crossfadeMs: Math.round(crossfadeMs) })}
        />
        <SettingSlider
          label={t('realtime.extraInferenceMs')}
          hint={t('realtime.extraInferenceMsHint')}
          value={cfg.extraInferenceMs}
          min={300}
          max={4000}
          step={100}
          format={(v) => t('realtime.msValue', { value: Math.round(v) })}
          onChange={(extraInferenceMs) =>
            patch({ extraInferenceMs: Math.round(extraInferenceMs) })
          }
        />
        <SettingSlider
          label={t('realtime.harvestProcesses')}
          hint={t('realtime.harvestProcessesHint')}
          value={cfg.harvestProcesses}
          min={1}
          max={8}
          step={1}
          format={(v) => `${Math.round(v)}`}
          onChange={(harvestProcesses) =>
            patch({ harvestProcesses: Math.round(harvestProcesses) })
          }
        />
      </div>

      <div className={styles.profileGroup}>
        <div className={styles.groupHead}>
          <Gauge />
          <div>
            <h3>{t('realtime.profileTitle')}</h3>
            <p>{t('realtime.profileDesc')}</p>
          </div>
        </div>
        <ProfileGrid profile={profile} />
      </div>

      <div className={styles.notice}>
        <Gauge />
        <span>{t('realtime.restartNotice')}</span>
      </div>
    </div>
  );
});

function ProfileGrid({ profile }: { profile: RealtimeProfile | null }) {
  const { t } = useTranslation();
  const items: Array<[string, number | undefined]> = [
    [t('realtime.profile.total'), profile?.totalMs],
    [t('realtime.profile.contentvec'), profile?.contentvecMs],
    [t('realtime.profile.f0'), profile?.f0Ms],
    [t('realtime.profile.generator'), profile?.generatorMs],
    [t('realtime.profile.faiss'), profile?.faissMs],
    [t('realtime.profile.resample'), profile?.inputResampleMs],
    [t('realtime.profile.rustDsp'), profile?.rustDspMs],
    [t('realtime.profile.rustSend'), profile?.rustSendMs],
    [t('realtime.profile.rustOutput'), profile?.rustOutputMs],
    [t('realtime.profile.sola'), profile?.solaMs],
    [t('realtime.profile.post'), profile?.postMs],
  ];
  const bottleneck = pickBottleneck(items);
  return (
    <div className={styles.profileGrid}>
      <div className={styles.profileMeta}>
        <span>{profile?.mode ?? '-'}</span>
        <span>{profile?.transport ?? '-'}</span>
        <span>{profile?.device ?? '-'}</span>
        <span>{formatF0(profile?.f0Method)}</span>
        <span>
          {bottleneck
            ? t('realtime.profile.bottleneck', { name: bottleneck[0] })
            : t('realtime.profile.waiting')}
        </span>
      </div>
      {items.map(([label, value]) => (
        <div key={label} className={styles.profileItem}>
          <span>{label}</span>
          <strong>{formatMs(value)}</strong>
        </div>
      ))}
    </div>
  );
}

interface SettingSliderProps {
  label: string;
  hint: string;
  value: number;
  min: number;
  max: number;
  step: number;
  disabled?: boolean;
  format: (value: number) => string;
  onChange: (value: number) => void;
}

function SettingSlider({
  label,
  hint,
  value,
  min,
  max,
  step,
  disabled,
  format,
  onChange,
}: SettingSliderProps) {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <label className={styles.sliderField} data-disabled={disabled || undefined}>
      <span className={styles.sliderText}>
        <strong>{label}</strong>
        <small>{hint}</small>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        style={{ ['--fill' as string]: `${Math.max(0, Math.min(100, pct))}%` }}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      <span className={styles.value}>{format(value)}</span>
    </label>
  );
}

function pickRecommendedPreset(info: TrainingGpuInfo | null): PerformancePresetId {
  if (!info?.available || info.backend !== 'cuda') return 'cpuDebug';
  const name = info.name.toLowerCase();
  if (
    /\b(4090|4080|5090|5080|3090|3080|6000|a6000|a5000|a100|h100)\b/.test(name)
  ) {
    return 'cudaHigh';
  }
  return 'cudaNormal';
}

function formatMs(value: number | undefined): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '-';
  return `${value.toFixed(value >= 100 ? 0 : 1)} ms`;
}

function formatF0(method: string | undefined): F0Method | '-' {
  if (method === 'rmvpe' || method === 'fcpe' || method === 'crepe') return method;
  return '-';
}

function pickBottleneck(
  items: Array<[string, number | undefined]>,
): [string, number] | null {
  const candidates = items.filter(
    ([label, value]) =>
      label !== '总耗时' &&
      label !== 'Total' &&
      typeof value === 'number' &&
      Number.isFinite(value),
  ) as Array<[string, number]>;
  if (candidates.length === 0) return null;
  return candidates.reduce((best, item) => (item[1] > best[1] ? item : best));
}
