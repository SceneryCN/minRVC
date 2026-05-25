import { memo, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Check } from 'lucide-react';
import type { VoicePreset } from '@/constants/voices';
import { formatPitch } from '@/utils/format';
import styles from './styles.module.css';

interface VoiceCardProps {
  preset: VoicePreset;
  selected: boolean;
  installed: boolean;
  onSelect: (id: VoicePreset['id']) => void;
}

function VoiceCardImpl({ preset, selected, installed, onSelect }: VoiceCardProps) {
  const { t } = useTranslation();
  const ref = useRef<HTMLButtonElement | null>(null);

  /**
   * 鼠标位置驱动的辐射光晕，用 CSS 变量传给 ::before。
   * 仅在 hover 时更新，没有进入 React 渲染循环，性能可忽略。
   */
  const handlePointerMove = useCallback((e: React.PointerEvent<HTMLButtonElement>) => {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const mx = ((e.clientX - rect.left) / rect.width) * 100;
    const my = ((e.clientY - rect.top) / rect.height) * 100;
    el.style.setProperty('--mx', `${mx}%`);
    el.style.setProperty('--my', `${my}%`);
  }, []);

  const Icon = preset.Icon;

  return (
    <button
      ref={ref}
      type="button"
      className={styles.card}
      data-selected={selected}
      style={{ ['--card-color' as string]: preset.colorVar }}
      onClick={() => onSelect(preset.id)}
      onPointerMove={handlePointerMove}
      aria-pressed={selected}
    >
      <span className={styles.iconWrap} aria-hidden>
        <Icon />
      </span>

      <div className={styles.body}>
        <h3 className={styles.name}>{t(`${preset.i18nKey}.name`)}</h3>
        <p className={styles.desc}>{t(`${preset.i18nKey}.desc`)}</p>
      </div>

      <div className={styles.footer}>
        <span className={styles.pitchHint}>
          {formatPitch(preset.defaultPitch)} st
        </span>
        <span className={styles.badge} data-installed={installed}>
          <span className={styles.badgeDot} />
          {installed ? t('voice.installedShort') : t('voice.notInstalledShort')}
        </span>
      </div>

      <span className={styles.checkMark} aria-hidden>
        <Check />
      </span>
    </button>
  );
}

export const VoiceCard = memo(VoiceCardImpl);
