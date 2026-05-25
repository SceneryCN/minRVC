import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { Mic, Sparkles, Wand2 } from 'lucide-react';
import { useAppStore } from '@/hooks/use-app-store';
import { useDsp } from '@/hooks/use-dsp';
import styles from './styles.module.css';

/**
 * DSP 高级面板：
 * - 降噪开关 + 强度滑条
 * - VAD 开关 + 阈值滑条
 * - 实时说话指示灯（VAD 概率可视化）
 *
 * 性能：
 * - 使用 zustand 选择器细粒度订阅
 * - 概率值用 transform: scaleX 渲染（GPU 合成）
 */
export const DspPanel = memo(function DspPanel() {
  const { t } = useTranslation();
  const { setConfig } = useDsp();

  const cfg = useAppStore((s) => s.dspConfig);
  const status = useAppStore((s) => s.dspStatus);

  return (
    <div className={styles.panel}>
      <div className={styles.row}>
        <div className={styles.rowHead}>
          <Wand2 className={styles.rowIcon} />
          <div>
            <h3 className={styles.rowTitle}>{t('dsp.denoiseTitle')}</h3>
            <p className={styles.rowDesc}>{t('dsp.denoiseDesc')}</p>
          </div>
          <Toggle
            checked={cfg.denoiseEnabled}
            onChange={(v) => setConfig({ denoiseEnabled: v })}
          />
        </div>
        <div className={styles.controlRow} data-disabled={!cfg.denoiseEnabled || undefined}>
          <span className={styles.label}>{t('dsp.denoiseStrength')}</span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={cfg.denoiseStrength}
            onChange={(e) =>
              setConfig({ denoiseStrength: Number.parseFloat(e.target.value) })
            }
            className={styles.slider}
            disabled={!cfg.denoiseEnabled}
          />
          <span className={styles.value}>
            {Math.round(cfg.denoiseStrength * 100)}%
          </span>
        </div>
      </div>

      <div className={styles.row}>
        <div className={styles.rowHead}>
          <Mic className={styles.rowIcon} />
          <div>
            <h3 className={styles.rowTitle}>{t('dsp.vadTitle')}</h3>
            <p className={styles.rowDesc}>{t('dsp.vadDesc')}</p>
          </div>
          <Toggle
            checked={cfg.vadEnabled}
            onChange={(v) => setConfig({ vadEnabled: v })}
          />
        </div>
        <div className={styles.controlRow} data-disabled={!cfg.vadEnabled || undefined}>
          <span className={styles.label}>{t('dsp.vadThreshold')}</span>
          <input
            type="range"
            min={0.1}
            max={0.9}
            step={0.05}
            value={cfg.vadThreshold}
            onChange={(e) =>
              setConfig({ vadThreshold: Number.parseFloat(e.target.value) })
            }
            className={styles.slider}
            disabled={!cfg.vadEnabled}
          />
          <span className={styles.value}>{cfg.vadThreshold.toFixed(2)}</span>
        </div>
        <div className={styles.controlRow} data-disabled={!cfg.vadEnabled || undefined}>
          <span className={styles.label}>{t('dsp.minSpeech')}</span>
          <input
            type="range"
            min={50}
            max={1000}
            step={50}
            value={cfg.vadMinSpeechMs}
            onChange={(e) =>
              setConfig({ vadMinSpeechMs: Number.parseInt(e.target.value, 10) })
            }
            className={styles.slider}
            disabled={!cfg.vadEnabled}
          />
          <span className={styles.value}>{cfg.vadMinSpeechMs} ms</span>
        </div>
        <div className={styles.controlRow} data-disabled={!cfg.vadEnabled || undefined}>
          <span className={styles.label}>{t('dsp.minSilence')}</span>
          <input
            type="range"
            min={50}
            max={1000}
            step={50}
            value={cfg.vadMinSilenceMs}
            onChange={(e) =>
              setConfig({ vadMinSilenceMs: Number.parseInt(e.target.value, 10) })
            }
            className={styles.slider}
            disabled={!cfg.vadEnabled}
          />
          <span className={styles.value}>{cfg.vadMinSilenceMs} ms</span>
        </div>

        <div className={styles.statusRow} aria-live="polite">
          <span
            className={styles.lamp}
            data-on={status.speaking || undefined}
            aria-hidden
          />
          <span className={styles.statusText}>
            {status.speaking ? t('dsp.speaking') : t('dsp.silence')}
          </span>
          <div className={styles.probBar}>
            <span
              className={styles.probFill}
              style={{ transform: `scaleX(${Math.max(0, Math.min(1, status.vadProbability))})` }}
            />
          </div>
          <span className={styles.value}>
            {Math.round(status.vadProbability * 100)}%
          </span>
        </div>
      </div>

      <div className={styles.hint}>
        <Sparkles />
        <span>{t('dsp.hint')}</span>
      </div>
    </div>
  );
});

interface ToggleProps {
  checked: boolean;
  onChange: (v: boolean) => void;
}

function Toggle({ checked, onChange }: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      className={styles.toggle}
      data-on={checked || undefined}
      onClick={() => onChange(!checked)}
    >
      <span className={styles.toggleThumb} />
    </button>
  );
}
