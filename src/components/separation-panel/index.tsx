import { memo, useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  CircleCheck,
  Download,
  FileAudio,
  FlaskConical,
  Loader2,
  Music,
  TriangleAlert,
  Upload,
  X,
} from 'lucide-react';
import { open as openDialog } from '@tauri-apps/plugin-dialog';
import { open as openShell } from '@tauri-apps/plugin-shell';
import { useSeparation } from '@/hooks/use-separation';
import styles from './styles.module.css';

const MODELS: Array<{ id: string; labelKey: string }> = [
  { id: 'htdemucs', labelKey: 'separation.modelHtdemucs' },
  { id: 'htdemucs_ft', labelKey: 'separation.modelHtdemucsFt' },
  { id: 'mdx_extra', labelKey: 'separation.modelMdxExtra' },
];

/**
 * 离线人声分离面板：
 * - 选择本地音频文件 → 选择模型 → 启动分离
 * - 进度条、状态文字、错误提示
 * - 完成后展示 vocals.wav / accompaniment.wav 路径并支持「打开文件夹」
 */
export const SeparationPanel = memo(function SeparationPanel() {
  const { t } = useTranslation();
  const { job, start, cancel } = useSeparation();
  const [inputPath, setInputPath] = useState<string | null>(null);
  const [model, setModel] = useState<string>('htdemucs');
  const [twoStems, setTwoStems] = useState<boolean>(true);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const isRunning = job?.state === 'pending' || job?.state === 'running';
  const isDone = job?.state === 'done';
  const isFailed = job?.state === 'failed';
  const isCancelled = job?.state === 'cancelled';

  const handlePickFile = useCallback(async () => {
    setError(null);
    try {
      const picked = await openDialog({
        multiple: false,
        directory: false,
        filters: [
          {
            name: 'Audio',
            extensions: ['wav', 'mp3', 'flac', 'm4a', 'aac', 'ogg', 'opus'],
          },
        ],
      });
      if (typeof picked === 'string') {
        setInputPath(picked);
      }
    } catch (e) {
      setError(String(e));
    }
  }, []);

  const handleStart = useCallback(async () => {
    if (!inputPath) return;
    setSubmitting(true);
    setError(null);
    try {
      await start(inputPath, { model, twoStems });
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  }, [inputPath, model, twoStems, start]);

  const handleCancel = useCallback(async () => {
    await cancel();
  }, [cancel]);

  const handleOpenFolder = useCallback(
    async (path: string | null) => {
      if (!path) return;
      try {
        const dir = path.replace(/\/[^/]+$/, '') || path;
        await openShell(dir);
      } catch (e) {
        setError(String(e));
      }
    },
    [],
  );

  const progressPct = Math.round((job?.progress ?? 0) * 100);

  return (
    <div className={styles.panel}>
      <div className={styles.intro}>
        <FlaskConical />
        <div>
          <h3 className={styles.introTitle}>{t('separation.title')}</h3>
          <p className={styles.introDesc}>{t('separation.desc')}</p>
        </div>
      </div>

      {/* Step 1: 选文件 */}
      <div className={styles.dropZone} data-active={!!inputPath || undefined}>
        <button type="button" className={styles.dropBtn} onClick={handlePickFile}>
          {inputPath ? (
            <>
              <FileAudio />
              <span className={styles.fileName} title={inputPath}>
                {inputPath.split('/').pop() || inputPath}
              </span>
              <span className={styles.replace}>{t('separation.replace')}</span>
            </>
          ) : (
            <>
              <Upload />
              <span>{t('separation.pickFile')}</span>
            </>
          )}
        </button>
      </div>

      {/* Step 2: 模型 + 选项 */}
      <div className={styles.optionRow}>
        <label className={styles.optionLabel}>
          <span>{t('separation.model')}</span>
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className={styles.select}
            disabled={isRunning}
          >
            {MODELS.map((m) => (
              <option key={m.id} value={m.id}>
                {t(m.labelKey)}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.optionLabel}>
          <span>{t('separation.outputs')}</span>
          <div className={styles.segment}>
            <button
              type="button"
              data-active={twoStems || undefined}
              onClick={() => setTwoStems(true)}
              disabled={isRunning}
            >
              {t('separation.twoStems')}
            </button>
            <button
              type="button"
              data-active={!twoStems || undefined}
              onClick={() => setTwoStems(false)}
              disabled={isRunning}
            >
              {t('separation.fourStems')}
            </button>
          </div>
        </label>
      </div>

      {/* Step 3: action */}
      <div className={styles.actions}>
        {!isRunning ? (
          <button
            type="button"
            className={styles.primaryBtn}
            onClick={handleStart}
            disabled={!inputPath || submitting}
          >
            <Music />
            {t('separation.start')}
          </button>
        ) : (
          <button
            type="button"
            className={styles.cancelBtn}
            onClick={handleCancel}
          >
            <X />
            {t('separation.cancel')}
          </button>
        )}
      </div>

      {/* Progress */}
      {job && (
        <div
          className={styles.progressBox}
          data-state={job.state}
        >
          <div className={styles.progressHead}>
            <span className={styles.progressIcon} aria-hidden>
              {isDone ? (
                <CircleCheck />
              ) : isFailed || isCancelled ? (
                <TriangleAlert />
              ) : (
                <Loader2 className={styles.spin} />
              )}
            </span>
            <span className={styles.progressText}>
              {t(`separation.state.${job.state}`)}
              {job.message ? ` · ${job.message}` : ''}
            </span>
            <span className={styles.progressPct}>{progressPct}%</span>
          </div>
          <div className={styles.progressBar}>
            <span
              className={styles.progressFill}
              style={{ transform: `scaleX(${(job.progress ?? 0).toFixed(3)})` }}
            />
          </div>

          {isDone && (
            <div className={styles.results}>
              {job.vocalsPath && (
                <ResultRow
                  label={t('separation.vocals')}
                  path={job.vocalsPath}
                  onOpen={() => handleOpenFolder(job.vocalsPath)}
                />
              )}
              {job.otherPath && (
                <ResultRow
                  label={t('separation.accompaniment')}
                  path={job.otherPath}
                  onOpen={() => handleOpenFolder(job.otherPath)}
                />
              )}
            </div>
          )}

          {(isFailed || error) && (
            <p className={styles.error}>{job.error ?? error}</p>
          )}
        </div>
      )}
    </div>
  );
});

interface ResultRowProps {
  label: string;
  path: string;
  onOpen: () => void;
}

function ResultRow({ label, path, onOpen }: ResultRowProps) {
  return (
    <div className={styles.resultRow}>
      <span className={styles.resultLabel}>{label}</span>
      <code className={styles.resultPath} title={path}>
        {path}
      </code>
      <button type="button" className={styles.resultBtn} onClick={onOpen}>
        <Download />
      </button>
    </div>
  );
}
