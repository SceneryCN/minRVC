import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import { zhCN } from './zh-cn';
import { en } from './en';

const LANGUAGE_KEY = 'rvc.language';

function getInitialLanguage() {
  if (typeof window === 'undefined') return 'zh-CN';
  const stored = window.localStorage.getItem(LANGUAGE_KEY);
  if (stored === 'zh-CN' || stored === 'en') return stored;
  return window.navigator.language.toLowerCase().startsWith('zh') ? 'zh-CN' : 'en';
}

void i18n.use(initReactI18next).init({
  resources: {
    'zh-CN': { translation: zhCN },
    en: { translation: en },
  },
  lng: getInitialLanguage(),
  fallbackLng: 'zh-CN',
  interpolation: { escapeValue: false },
});

i18n.on('languageChanged', (lng) => {
  if (typeof window === 'undefined') return;
  if (lng === 'zh-CN' || lng === 'en') {
    window.localStorage.setItem(LANGUAGE_KEY, lng);
  }
});

export default i18n;
