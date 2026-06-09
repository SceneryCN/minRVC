import { memo, useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FilePlus2, FolderSearch, Loader2, Plus } from 'lucide-react';
import { open as openDialog } from '@tauri-apps/plugin-dialog';
import { PITCH_RANGE } from '@/constants/voices';
import { tauriApi } from '@/utils/tauri-api';
import styles from './styles.module.css';

interface CustomVoiceFormProps {
  onImported: (voiceId: string) => Promise<void> | void;
}

function toVoiceId(name: string) {
  const normalized = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fa5]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return `custom-${normalized || Date.now()}`;
}

export const CustomVoiceForm = memo(function CustomVoiceForm({
  onImported,
}: CustomVoiceFormProps) {
  const { t } = useTranslation();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [pitch, setPitch] = useState(0);
  const [pthPath, setPthPath] = useState<string | null>(null);
  const [indexPath, setIndexPath] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = useMemo(
    () => name.trim().length > 0 && !!pthPath && !submitting,
    [name, pthPath, submitting],
  );

  const pickPth = useCallback(async () => {
    setError(null);
    const picked = await openDialog({
      multiple: false,
      directory: false,
      filters: [{ name: 'RVC model', extensions: ['pth'] }],
    });
    if (typeof picked === 'string') setPthPath(picked);
  }, []);

  const pickIndex = useCallback(async () => {
    setError(null);
    const picked = await openDialog({
      multiple: false,
      directory: false,
      filters: [{ name: 'RVC index', extensions: ['index'] }],
    });
    if (typeof picked === 'string') setIndexPath(picked);
  }, []);

  const handleSubmit = useCallback(async () => {
    if (!pthPath || !name.trim()) return;
    setSubmitting(true);
    setError(null);
    const voiceId = toVoiceId(name);
    try {
      await tauriApi.importVoiceModel({
        voice_id: voiceId,
        pth_path: pthPath,
        index_path: indexPath,
        display_name: name.trim(),
        description: description.trim() || t('customVoice.defaultDesc'),
        category: 'custom',
        gender: 'unknown',
        recommended_pitch: pitch,
      });
      await onImported(voiceId);
      setName('');
      setDescription('');
      setPitch(0);
      setPthPath(null);
      setIndexPath(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }, [description, indexPath, name, onImported, pitch, pthPath, t]);

  return (
    <div className={styles.panel}>
      <div className={styles.titleRow}>
        <FilePlus2 />
        <div>
          <h3>{t('customVoice.title')}</h3>
          <p>{t('customVoice.desc')}</p>
        </div>
      </div>

      <div className={styles.formGrid}>
        <label className={styles.field}>
          <span>{t('customVoice.name')}</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('customVoice.namePlaceholder')}
          />
        </label>
        <label className={styles.field}>
          <span>{t('customVoice.pitch')}</span>
          <input
            type="number"
            min={PITCH_RANGE.min}
            max={PITCH_RANGE.max}
            step={PITCH_RANGE.step}
            value={pitch}
            onChange={(e) => setPitch(Number(e.target.value))}
          />
        </label>
        <label className={styles.field}>
          <span>{t('customVoice.description')}</span>
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={t('customVoice.descriptionPlaceholder')}
          />
        </label>
      </div>

      <div className={styles.fileRow}>
        <button type="button" className={styles.fileBtn} onClick={pickPth}>
          <FolderSearch />
          <span>{pthPath ? pthPath.split('/').pop() : t('customVoice.pickPth')}</span>
        </button>
        <button type="button" className={styles.fileBtn} onClick={pickIndex}>
          <FolderSearch />
          <span>
            {indexPath ? indexPath.split('/').pop() : t('customVoice.pickIndex')}
          </span>
        </button>
        <button
          type="button"
          className={styles.submitBtn}
          disabled={!canSubmit}
          onClick={handleSubmit}
        >
          {submitting ? <Loader2 className={styles.spin} /> : <Plus />}
          {t('customVoice.add')}
        </button>
      </div>

      {error && <p className={styles.error}>{error}</p>}
    </div>
  );
});
