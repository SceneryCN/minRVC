import { memo, useMemo } from 'react';
import { Monitor, Moon, Sun } from 'lucide-react';
import { useTheme, type ThemeMode } from '@/hooks/use-theme';
import styles from './styles.module.css';

interface OptionDef {
  key: ThemeMode;
  label: string;
  Icon: typeof Sun;
}

const OPTIONS: ReadonlyArray<OptionDef> = [
  { key: 'light', label: '浅色', Icon: Sun },
  { key: 'dark', label: '暗色', Icon: Moon },
  { key: 'system', label: '跟随系统', Icon: Monitor },
];

function ThemeSwitcherImpl() {
  const { mode, setMode } = useTheme();

  const indicatorStyle = useMemo(() => {
    const idx = OPTIONS.findIndex((o) => o.key === mode);
    return { transform: `translateX(${idx * 32}px)` };
  }, [mode]);

  return (
    <div className={styles.group} role="radiogroup" aria-label="主题">
      <div className={styles.indicator} style={indicatorStyle} aria-hidden />
      {OPTIONS.map(({ key, label, Icon }) => (
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
      ))}
    </div>
  );
}

export const ThemeSwitcher = memo(ThemeSwitcherImpl);
