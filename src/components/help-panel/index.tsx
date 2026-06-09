import { memo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { open as openShell } from '@tauri-apps/plugin-shell';
import {
  BookOpen,
  Cable,
  CircleAlert,
  Download,
  GraduationCap,
  ExternalLink,
  MicVocal,
  Route,
  Sparkles,
} from 'lucide-react';
import styles from './styles.module.css';

const STEPS = [
  { icon: Cable, key: 'virtualCable' },
  { icon: MicVocal, key: 'devices' },
  { icon: Sparkles, key: 'voice' },
  { icon: Route, key: 'routing' },
] as const;

const MODEL_LINKS = [
  {
    key: 'hubert',
    url: 'https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/hubert_base.pt',
  },
  {
    key: 'rmvpe',
    url: 'https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/rmvpe.pt',
  },
  {
    key: 'rvcWebui',
    url: 'https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI',
  },
  {
    key: 'rvcReleases',
    url: 'https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/releases',
  },
  {
    key: 'uvrModels',
    url: 'https://github.com/nomadkaraoke/python-audio-separator',
  },
] as const;

export const HelpPanel = memo(function HelpPanel() {
  const { t } = useTranslation();
  const handleOpen = useCallback(async (url: string) => {
    await openShell(url);
  }, []);

  return (
    <div className={styles.panel}>
      <section className={styles.hero}>
        <div className={styles.heroIcon} aria-hidden>
          <BookOpen />
        </div>
        <div className={styles.heroText}>
          <h2>{t('help.title')}</h2>
          <p>{t('help.desc')}</p>
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionTitle}>
          <GraduationCap />
          <h3>{t('help.quickStartTitle')}</h3>
        </div>
        <div className={styles.stepGrid}>
          {STEPS.map(({ icon: Icon, key }, index) => (
            <article key={key} className={styles.stepCard}>
              <span className={styles.stepIndex}>{index + 1}</span>
              <Icon />
              <div>
                <h4>{t(`help.steps.${key}.title`)}</h4>
                <p>{t(`help.steps.${key}.desc`)}</p>
              </div>
            </article>
          ))}
        </div>
      </section>

      <div className={styles.columns}>
        <section className={styles.section}>
          <div className={styles.sectionTitle}>
            <Download />
            <h3>{t('help.modelGuideTitle')}</h3>
          </div>
          <div className={styles.modelList}>
            <div className={styles.downloadGrid}>
              {MODEL_LINKS.map((item) => (
                <article key={item.key} className={styles.downloadItem}>
                  <div>
                    <strong>{t(`help.downloads.${item.key}.title`)}</strong>
                    <p>{t(`help.downloads.${item.key}.desc`)}</p>
                    <small>{t(`help.downloads.${item.key}.where`)}</small>
                  </div>
                  <button type="button" onClick={() => void handleOpen(item.url)}>
                    <ExternalLink />
                    {t('help.openLink')}
                  </button>
                </article>
              ))}
            </div>
            <div className={styles.modelItem}>
              <strong>{t('help.voiceModelsTitle')}</strong>
              <p>{t('help.voiceModelsDesc')}</p>
            </div>
            <div className={styles.modelItem}>
              <strong>{t('help.importModelsTitle')}</strong>
              <p>{t('help.importModelsDesc')}</p>
            </div>
            <div className={styles.notice}>
              <CircleAlert />
              <span>{t('help.licenseNotice')}</span>
            </div>
          </div>
        </section>

        <section className={styles.section}>
          <div className={styles.sectionTitle}>
            <Cable />
            <h3>{t('help.routingTitle')}</h3>
          </div>
          <div className={styles.modelList}>
            <div className={styles.modelItem}>
              <strong>{t('help.routingDirectTitle')}</strong>
              <p>{t('help.routingDirectDesc')}</p>
            </div>
            <div className={styles.modelItem}>
              <strong>{t('help.routingVirtualTitle')}</strong>
              <p>{t('help.routingVirtualDesc')}</p>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
});
