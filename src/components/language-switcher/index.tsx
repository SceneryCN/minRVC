import { memo, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import styles from './styles.module.css';

const LANGS = [
  { key: 'zh-CN', labelKey: 'language.zh' },
  { key: 'en', labelKey: 'language.en' },
] as const;

function LanguageSwitcherImpl() {
  const { i18n, t } = useTranslation();
  const active = i18n.resolvedLanguage === 'en' ? 'en' : 'zh-CN';

  const indicatorStyle = useMemo(() => {
    const idx = LANGS.findIndex((it) => it.key === active);
    return { transform: `translateX(${idx * 46}px)` };
  }, [active]);

  return (
    <div className={styles.group} role="radiogroup" aria-label={t('language.aria')}>
      <div className={styles.options}>
        <div className={styles.indicator} style={indicatorStyle} aria-hidden />
        {LANGS.map(({ key, labelKey }) => (
          <button
            key={key}
            type="button"
            role="radio"
            aria-checked={active === key}
            className={styles.option}
            data-active={active === key || undefined}
            onClick={() => void i18n.changeLanguage(key)}
          >
            {t(labelKey)}
          </button>
        ))}
      </div>
    </div>
  );
}

export const LanguageSwitcher = memo(LanguageSwitcherImpl);
