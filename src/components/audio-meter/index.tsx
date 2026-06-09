import { memo } from 'react';
import { type LucideIcon } from 'lucide-react';
import { useAppStore } from '@/hooks/use-app-store';
import { clamp, levelToPercent } from '@/utils/format';
import styles from './styles.module.css';

interface AudioMeterProps {
  label: string;
  channel: 'input' | 'output';
  Icon?: LucideIcon;
}

const PEAK_TICKS = 12;

function AudioMeterImpl({ label, channel, Icon }: AudioMeterProps) {
  const level = useAppStore((s) =>
    channel === 'input' ? s.inputLevel : s.outputLevel,
  );
  const percent = levelToPercent(level);
  const scale = clamp(level, 0, 1);

  return (
    <div className={styles.wrapper}>
      <div className={styles.header}>
        <span className={styles.label}>
          {Icon ? <Icon /> : null}
          {label}
        </span>
        <span className={styles.value}>{percent.toString().padStart(2, '0')}%</span>
      </div>
      <div className={styles.bar}>
        <div className={styles.fill} style={{ transform: `scaleX(${scale})` }} />
        <div className={styles.peakDots} aria-hidden>
          {Array.from({ length: PEAK_TICKS }, (_, i) => (
            <span key={i} />
          ))}
        </div>
      </div>
    </div>
  );
}

export const AudioMeter = memo(AudioMeterImpl);
