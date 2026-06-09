import { memo, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Monitor, Moon, Sun } from 'lucide-react';
import { useTheme, type ThemeMode } from '@/hooks/use-theme';
import styles from './styles.module.css';

interface OptionDef {
  key: ThemeMode;
  labelKey: string;
  Icon: typeof Sun;
}

const OPTIONS: ReadonlyArray<OptionDef> = [
  { key: 'light', labelKey: 'theme.light', Icon: Sun },
  { key: 'dark', labelKey: 'theme.dark', Icon: Moon },
  { key: 'system', labelKey: 'theme.system', Icon: Monitor },
];

function ThemeSwitcherImpl() {
  const { t } = useTranslation();
  const { mode, setMode } = useTheme();

  const indicatorStyle = useMemo(() => {
    const idx = OPTIONS.findIndex((o) => o.key === mode);
    return { transform: `translateX(${idx * 32}px)` };
  }, [mode]);

  return (
    <div className={styles.group} role="radiogroup" aria-label={t('theme.aria')}>
      <div className={styles.indicator} style={indicatorStyle} aria-hidden />
      {OPTIONS.map(({ key, labelKey, Icon }) => {
        const label = t(labelKey);
        return (
        <button
          key={key}
          type="button"
          role="radio"
          aria-checked={mode === key}
          aria-label={label}
          title={label}
          className={styles.option}
          data-active={mode === key}
          onClick={() => setMode(key)}
        >
          <Icon strokeWidth={2} />
        </button>
        );
      })}
    </div>
  );
}

export const ThemeSwitcher = memo(ThemeSwitcherImpl);
