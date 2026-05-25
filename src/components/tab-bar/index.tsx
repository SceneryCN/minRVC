import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { AudioWaveform, FlaskConical } from 'lucide-react';
import type { AppTabId } from '@/types';
import styles from './styles.module.css';

interface TabItem {
  id: AppTabId;
  Icon: typeof AudioWaveform;
  i18nKey: string;
}

const TABS: TabItem[] = [
  { id: 'voice', Icon: AudioWaveform, i18nKey: 'tabs.voice' },
  { id: 'lab', Icon: FlaskConical, i18nKey: 'tabs.lab' },
];

interface TabBarProps {
  active: AppTabId;
  onChange: (id: AppTabId) => void;
}

export const TabBar = memo(function TabBar({ active, onChange }: TabBarProps) {
  const { t } = useTranslation();
  return (
    <nav className={styles.bar} aria-label={t('tabs.aria') ?? 'Sections'}>
      <div
        className={styles.indicator}
        style={{ transform: `translateX(${TABS.findIndex((it) => it.id === active) * 100}%)` }}
        aria-hidden
      />
      {TABS.map(({ id, Icon, i18nKey }) => (
        <button
          key={id}
          type="button"
          className={styles.tab}
          data-active={id === active || undefined}
          onClick={() => onChange(id)}
        >
          <Icon />
          <span>{t(i18nKey)}</span>
        </button>
      ))}
    </nav>
  );
});
