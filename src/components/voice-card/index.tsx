import { memo, useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Upload } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { formatPitch } from '@/utils/format';
import styles from './styles.module.css';

interface VoiceCardProps {
  id: string;
  name: string;
  description: string;
  pitch: number;
  color: string;
  Icon: LucideIcon;
  selected: boolean;
  installed: boolean;
  onSelect: (id: string) => void;
  onImport: (id: string) => void;
}

function VoiceCardImpl({
  id,
  name,
  description,
  pitch,
  color,
  Icon,
  selected,
  installed,
  onSelect,
  onImport,
}: VoiceCardProps) {
  const { t } = useTranslation();
  const ref = useRef<HTMLElement | null>(null);
  const frameRef = useRef<number | null>(null);
  const pointerRef = useRef<{ x: number; y: number } | null>(null);

  /**
   * 鼠标位置驱动的辐射光晕，用 CSS 变量传给 ::before。
   * 用 RAF 合并高频 pointermove，避免每个鼠标事件都触发样式计算。
   */
  const handlePointerMove = useCallback((e: React.PointerEvent<HTMLElement>) => {
    if (
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    ) {
      return;
    }
    pointerRef.current = { x: e.clientX, y: e.clientY };
    if (frameRef.current !== null) return;
    frameRef.current = window.requestAnimationFrame(() => {
      frameRef.current = null;
      const point = pointerRef.current;
      const el = ref.current;
      if (!el || !point) return;
      const rect = el.getBoundingClientRect();
      const mx = ((point.x - rect.left) / rect.width) * 100;
      const my = ((point.y - rect.top) / rect.height) * 100;
      el.style.setProperty('--mx', `${mx}%`);
      el.style.setProperty('--my', `${my}%`);
    });
  }, []);

  const handlePointerLeave = useCallback(() => {
    pointerRef.current = null;
    if (frameRef.current !== null) {
      window.cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    }
    const el = ref.current;
    if (!el) return;
    el.style.removeProperty('--mx');
    el.style.removeProperty('--my');
  }, []);

  useEffect(() => {
    return () => {
      if (frameRef.current !== null) {
        window.cancelAnimationFrame(frameRef.current);
      }
    };
  }, []);

  return (
    <article
      ref={ref}
      role="button"
      tabIndex={0}
      className={styles.card}
      data-selected={selected}
      style={{ ['--card-color' as string]: color }}
      onClick={() => onSelect(id)}
      onKeyDown={(e) => {
        if (e.target !== e.currentTarget) return;
        if (e.key !== 'Enter' && e.key !== ' ') return;
        e.preventDefault();
        onSelect(id);
      }}
      onPointerMove={handlePointerMove}
      onPointerLeave={handlePointerLeave}
      aria-pressed={selected}
    >
      <span className={styles.iconWrap} aria-hidden>
        <Icon />
      </span>

      <div className={styles.body}>
        <h3 className={styles.name}>{name}</h3>
        <p className={styles.desc}>{description}</p>
      </div>

      <div className={styles.footer}>
        <span className={styles.pitchHint}>
          {formatPitch(pitch)} st
        </span>
        <span className={styles.badge} data-installed={installed}>
          <span className={styles.badgeDot} />
          {installed ? t('voice.installedShort') : t('voice.notInstalledShort')}
        </span>
      </div>

      <button
        type="button"
        className={styles.importAction}
        onClick={(e) => {
          e.stopPropagation();
          onImport(id);
        }}
      >
        <Upload />
        {installed ? t('voice.reimport') : t('voice.install')}
      </button>

      <span className={styles.checkMark} aria-hidden>
        <Check />
      </span>
    </article>
  );
}

export const VoiceCard = memo(VoiceCardImpl);
