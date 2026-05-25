import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { LoaderCircle, Play, Square } from 'lucide-react';
import type { EngineStatus } from '@/types';
import styles from './styles.module.css';

interface LiveToggleProps {
  status: EngineStatus;
  onStart: () => void;
  onStop: () => void;
  disabled?: boolean;
}

function LiveToggleImpl({ status, onStart, onStop, disabled }: LiveToggleProps) {
  const { t } = useTranslation();
  const running = status === 'Running';
  const transitioning = status === 'Starting' || status === 'Stopping';

  const label = (() => {
    switch (status) {
      case 'Starting':
        return t('engine.starting');
      case 'Stopping':
        return t('engine.stopping');
      case 'Running':
        return t('engine.stop');
      default:
        return t('engine.start');
    }
  })();

  const Icon = transitioning ? LoaderCircle : running ? Square : Play;

  return (
    <button
      type="button"
      className={styles.button}
      data-running={running}
      data-transitioning={transitioning}
      disabled={disabled || transitioning}
      onClick={running ? onStop : onStart}
    >
      <span
        className={`${styles.icon}${transitioning ? ` ${styles.iconSpin}` : ''}`}
      >
        <Icon />
      </span>
      <span className={styles.label}>{label}</span>
    </button>
  );
}

export const LiveToggle = memo(LiveToggleImpl);
