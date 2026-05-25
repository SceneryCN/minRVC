import { memo, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Music2 } from 'lucide-react';
import { PITCH_RANGE } from '@/constants/voices';
import { formatPitch } from '@/utils/format';
import styles from './styles.module.css';

interface PitchControlProps {
  value: number;
  onChange: (semitones: number) => void;
}

function PitchControlImpl({ value, onChange }: PitchControlProps) {
  const { t } = useTranslation();

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onChange(Number.parseInt(e.target.value, 10));
    },
    [onChange],
  );

  /**
   * 0 在中点，左右各占 50%。
   * fill 从中点向 thumb 方向延伸。
   */
  const fillStyle = useMemo(() => {
    const total = PITCH_RANGE.max - PITCH_RANGE.min;
    const center = (0 - PITCH_RANGE.min) / total;
    const cur = (value - PITCH_RANGE.min) / total;
    if (cur >= center) {
      return { left: `${center * 100}%`, width: `${(cur - center) * 100}%` };
    }
    return { left: `${cur * 100}%`, width: `${(center - cur) * 100}%` };
  }, [value]);

  return (
    <div className={styles.wrapper}>
      <div className={styles.header}>
        <span className={styles.label}>
          <Music2 />
          {t('engine.pitch')}
        </span>
        <span className={styles.value}>
          {formatPitch(value)}
          <small>{t('engine.pitchUnit')}</small>
        </span>
      </div>
      <div className={styles.rangeWrap}>
        <div className={styles.rangeTrack} aria-hidden />
        <div className={styles.rangeFill} style={fillStyle} aria-hidden />
        <input
          type="range"
          className={styles.range}
          min={PITCH_RANGE.min}
          max={PITCH_RANGE.max}
          step={PITCH_RANGE.step}
          value={value}
          onChange={handleChange}
        />
      </div>
      <div className={styles.ticks}>
        <span>−24</span>
        <span>−12</span>
        <span>0</span>
        <span>+12</span>
        <span>+24</span>
      </div>
    </div>
  );
}

export const PitchControl = memo(PitchControlImpl);
