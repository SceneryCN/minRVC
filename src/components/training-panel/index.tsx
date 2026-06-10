import { memo, useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  CircleCheck,
  Cpu,
  Download,
  ExternalLink,
  FolderOpen,
  Loader2,
  RefreshCw,
  ScrollText,
  TriangleAlert,
  X,
  Zap,
} from 'lucide-react';
import { open as openDialog } from '@tauri-apps/plugin-dialog';
import { open as openShell } from '@tauri-apps/plugin-shell';
import { useAppStore } from '@/hooks/use-app-store';
import { useTraining } from '@/hooks/use-training';
import type { F0Method, PretrainedWeightInfo } from '@/types';
import { tauriApi } from '@/utils/tauri-api';
import styles from './styles.module.css';

const SAMPLE_RATES = [32000, 40000, 48000] as const;
const F0_METHODS: F0Method[] = ['rmvpe', 'fcpe', 'crepe'];
const RVC_WEBUI_URL =
  'https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI';
const RVC_WEBUI_RELEASES_URL =
  'https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/releases';

export const TrainingPanel = memo(function TrainingPanel() {
  const { t } = useTranslation();
  const { job, gpuInfo, gpuLoading, refreshGpu, start, cancel } = useTraining();
  const setVoices = useAppStore((s) => s.setVoices);
  const setSelectedVoice = useAppStore((s) => s.setSelectedVoice);
  const [datasetDir, setDatasetDir] = useState<string | null>(null);
  const [trainingPackageDir, setTrainingPackageDir] = useState<string | null>(null);
  const [voiceName, setVoiceName] = useState('');
  const [epochs, setEpochs] = useState(200);
  const [batchSize, setBatchSize] = useState(4);
  const [sampleRate, setSampleRate] = useState(40000);
  const [f0Method, setF0Method] = useState<F0Method>('rmvpe');
  const [saveEveryEpoch, setSaveEveryEpoch] = useState(10);
  const [modelVersion, setModelVersion] = useState<'v1' | 'v2'>('v2');
  const [gpuIds, setGpuIds] = useState('0');
  const [cacheGpu, setCacheGpu] = useState(false);
  const [saveLatestOnly, setSaveLatestOnly] = useState(true);
  const [saveEveryWeights, setSaveEveryWeights] = useState(false);
  const [pretrainedG, setPretrainedG] = useState<string | null>(null);
  const [pretrainedD, setPretrainedD] = useState<string | null>(null);
  const [useGpu, setUseGpu] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [importingOutput, setImportingOutput] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pretrainedCatalog, setPretrainedCatalog] = useState<PretrainedWeightInfo[]>([]);

  const isRunning = job?.state === 'pending' || job?.state === 'running';
  const isDone = job?.state === 'done';
  const isFailed = job?.state === 'failed';
  const isCancelled = job?.state === 'cancelled';
  const canStart = !!datasetDir && voiceName.trim().length > 0 && !submitting;
  const gpuAvailable = gpuInfo?.available ?? false;
  const gpuStatusLabel = gpuLoading
    ? t('training.gpuChecking')
    : gpuInfo
      ? gpuInfo.available
        ? t(`training.gpuBackend.${gpuInfo.backend}`, {
            defaultValue: gpuInfo.backend.toUpperCase(),
          })
        : t('training.gpuUnavailable')
      : t('training.gpuUnknown');
  const gpuStatusDetail = gpuLoading
    ? null
    : gpuInfo?.available
      ? gpuInfo.name
      : gpuInfo
        ? t('training.gpuCpuMode')
        : null;

  useEffect(() => {
    if (gpuInfo && !gpuInfo.available) setUseGpu(false);
  }, [gpuInfo]);

  useEffect(() => {
    let cancelled = false;
    void tauriApi
      .getBaseModelStatus()
      .then((status) => {
        if (!cancelled) setPretrainedCatalog(status.pretrainedWeights);
      })
      .catch(() => {
        if (!cancelled) setPretrainedCatalog([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const recommendedG = pickPretrained(pretrainedCatalog, 'G', modelVersion, sampleRate);
  const recommendedD = pickPretrained(pretrainedCatalog, 'D', modelVersion, sampleRate);
  const gMismatch = pretrainedG
    ? !pretrainedG.split(/[\\/]/).pop()?.includes(recommendedG?.fileName ?? '')
    : false;
  const dMismatch = pretrainedD
    ? !pretrainedD.split(/[\\/]/).pop()?.includes(recommendedD?.fileName ?? '')
    : false;

  const handlePickDataset = useCallback(async () => {
    setError(null);
    try {
      const picked = await openDialog({
        multiple: false,
        directory: true,
      });
      if (typeof picked === 'string') setDatasetDir(picked);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  const handlePickTrainingPackage = useCallback(async () => {
    setError(null);
    try {
      const picked = await openDialog({
        multiple: false,
        directory: true,
        title: t('training.pickPackageTitle'),
      });
      if (typeof picked === 'string') setTrainingPackageDir(picked);
    } catch (e) {
      setError(String(e));
    }
  }, [t]);

  const handlePickPretrained = useCallback(
    async (kind: 'g' | 'd') => {
      setError(null);
      try {
        const picked = await openDialog({
          multiple: false,
          directory: false,
          title: t(kind === 'g' ? 'training.pickPretrainedGTitle' : 'training.pickPretrainedDTitle'),
          filters: [{ name: 'RVC pretrained model', extensions: ['pth'] }],
        });
        if (typeof picked !== 'string') return;
        if (kind === 'g') setPretrainedG(picked);
        else setPretrainedD(picked);
      } catch (e) {
        setError(String(e));
      }
    },
    [t],
  );

  const handleOpenDownload = useCallback(async (url: string) => {
    try {
      await openShell(url);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  const handleImportTrainingOutput = useCallback(async () => {
    if (!job?.pthPath) return;
    setImportingOutput(true);
    setError(null);
    try {
      const imported = await tauriApi.importTrainingOutput({
        pth_path: job.pthPath,
        index_path: job.indexPath,
        voice_name: voiceName.trim() || 'trained_voice',
        sample_rate: sampleRate,
        model_version: modelVersion,
      });
      setVoices(await tauriApi.listVoiceModels());
      setSelectedVoice(imported.id);
    } catch (e) {
      setError(String(e));
    } finally {
      setImportingOutput(false);
    }
  }, [job, modelVersion, sampleRate, setSelectedVoice, setVoices, voiceName]);

  const handleStart = useCallback(async () => {
    if (!datasetDir || !voiceName.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await start({
        dataset_dir: datasetDir,
        voice_name: voiceName.trim(),
        training_package_dir: trainingPackageDir,
        epochs,
        batch_size: batchSize,
        sample_rate: sampleRate,
        f0_method: f0Method,
        save_every_epoch: saveEveryEpoch,
        model_version: modelVersion,
        gpu_ids: gpuIds.trim() || null,
        cache_gpu: cacheGpu,
        save_latest_only: saveLatestOnly,
        save_every_weights: saveEveryWeights,
        pretrained_g: pretrainedG,
        pretrained_d: pretrainedD,
        use_gpu: useGpu,
      });
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  }, [
    datasetDir,
    trainingPackageDir,
    voiceName,
    epochs,
    batchSize,
    sampleRate,
    f0Method,
    saveEveryEpoch,
    modelVersion,
    gpuIds,
    cacheGpu,
    saveLatestOnly,
    saveEveryWeights,
    pretrainedG,
    pretrainedD,
    useGpu,
    start,
  ]);

  const handleOpen = useCallback(async (path: string | null) => {
    if (!path) return;
    try {
      await openShell(path.replace(/\/[^/]+$/, '') || path);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  const progressPct = Math.round((job?.progress ?? 0) * 100);

  return (
    <div className={styles.panel}>
      <div className={styles.intro}>
        <Zap />
        <div>
          <h3 className={styles.introTitle}>{t('training.title')}</h3>
          <p className={styles.introDesc}>{t('training.desc')}</p>
        </div>
      </div>

      <div className={styles.notice}>
        <Cpu />
        <span>{t('training.gpuNotice')}</span>
      </div>

      <div className={styles.packageBox}>
        <div className={styles.packageCopy}>
          <strong>{t('training.packageTitle')}</strong>
          <span>{t('training.packageDesc')}</span>
        </div>
        <div className={styles.packageActions}>
          <button
            type="button"
            className={styles.secondaryBtn}
            onClick={() => void handleOpenDownload(RVC_WEBUI_URL)}
          >
            <ExternalLink />
            {t('training.openRepo')}
          </button>
          <button
            type="button"
            className={styles.secondaryBtn}
            onClick={() => void handleOpenDownload(RVC_WEBUI_RELEASES_URL)}
          >
            <ExternalLink />
            {t('training.openReleases')}
          </button>
          <button
            type="button"
            className={styles.pathBtn}
            onClick={handlePickTrainingPackage}
          >
            <FolderOpen />
            <span title={trainingPackageDir ?? undefined}>
              {trainingPackageDir
                ? trainingPackageDir.split('/').pop()
                : t('training.pickPackage')}
            </span>
          </button>
        </div>
      </div>

      <div className={styles.grid}>
        <label className={styles.field}>
          <span>{t('training.dataset')}</span>
          <button type="button" className={styles.pathBtn} onClick={handlePickDataset}>
            <FolderOpen />
            <span title={datasetDir ?? undefined}>
              {datasetDir ? datasetDir.split('/').pop() : t('training.pickDataset')}
            </span>
          </button>
        </label>

        <label className={styles.field}>
          <span>{t('training.voiceName')}</span>
          <input
            className={styles.input}
            value={voiceName}
            onChange={(e) => setVoiceName(e.target.value)}
            placeholder={t('training.voiceNamePlaceholder')}
            disabled={isRunning}
          />
        </label>

        <label className={styles.field}>
          <span>{t('training.modelVersion')}</span>
          <select
            className={styles.input}
            value={modelVersion}
            onChange={(e) => setModelVersion(e.target.value as 'v1' | 'v2')}
            disabled={isRunning}
          >
            <option value="v2">{t('training.version.v2')}</option>
            <option value="v1">{t('training.version.v1')}</option>
          </select>
        </label>

        <label className={styles.field}>
          <span>{t('training.epochs')}</span>
          <input
            className={styles.input}
            type="number"
            min={1}
            max={1000}
            value={epochs}
            onChange={(e) => setEpochs(Number(e.target.value))}
            disabled={isRunning}
          />
        </label>

        <label className={styles.field}>
          <span>{t('training.batchSize')}</span>
          <input
            className={styles.input}
            type="number"
            min={1}
            max={64}
            value={batchSize}
            onChange={(e) => setBatchSize(Number(e.target.value))}
            disabled={isRunning}
          />
        </label>

        <label className={styles.field}>
          <span>{t('training.sampleRate')}</span>
          <select
            className={styles.input}
            value={sampleRate}
            onChange={(e) => setSampleRate(Number(e.target.value))}
            disabled={isRunning}
          >
            {SAMPLE_RATES.map((sr) => (
              <option key={sr} value={sr}>
                {sr.toLocaleString()} Hz
              </option>
            ))}
          </select>
        </label>

        <label className={styles.field}>
          <span>{t('training.f0Method')}</span>
          <select
            className={styles.input}
            value={f0Method}
            onChange={(e) => setF0Method(e.target.value as F0Method)}
            disabled={isRunning}
          >
            {F0_METHODS.map((method) => (
              <option key={method} value={method}>
                {t(`training.f0.${method}`)}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.field}>
          <span>{t('training.saveEveryEpoch')}</span>
          <input
            className={styles.input}
            type="number"
            min={1}
            max={100}
            value={saveEveryEpoch}
            onChange={(e) => setSaveEveryEpoch(Number(e.target.value))}
            disabled={isRunning}
          />
        </label>

        <label className={styles.toggleField}>
          <span>{t('training.useGpu')}</span>
          <div className={styles.gpuBox} data-available={gpuAvailable || undefined}>
            <label className={styles.gpuToggle}>
              <input
                type="checkbox"
                checked={useGpu && gpuAvailable}
                onChange={(e) => setUseGpu(e.target.checked)}
                disabled={isRunning || !gpuAvailable}
              />
              <span>{gpuStatusLabel}</span>
            </label>
            {gpuStatusDetail ? <small title={gpuStatusDetail}>{gpuStatusDetail}</small> : null}
            <button
              type="button"
              className={styles.gpuRefresh}
              onClick={() => void refreshGpu().catch((e) => setError(String(e)))}
              disabled={gpuLoading}
              aria-label={t('training.refreshGpu')}
            >
              <RefreshCw className={gpuLoading ? styles.spin : undefined} />
            </button>
          </div>
        </label>
      </div>

      <div className={styles.sectionBlock}>
        <div className={styles.sectionHead}>
          <h4>{t('training.advancedTitle')}</h4>
          <p>{t('training.advancedDesc')}</p>
        </div>
        <div className={styles.grid}>
          <label className={styles.field}>
            <span>{t('training.gpuIds')}</span>
            <input
              className={styles.input}
              value={gpuIds}
              onChange={(e) => setGpuIds(e.target.value)}
              placeholder="0"
              disabled={isRunning || !useGpu || !gpuAvailable}
            />
          </label>

          <label className={styles.field}>
            <span>{t('training.pretrainedG')}</span>
            <button
              type="button"
              className={styles.pathBtn}
              onClick={() => void handlePickPretrained('g')}
              disabled={isRunning}
            >
              <FolderOpen />
              <span title={pretrainedG ?? undefined}>
                {pretrainedG ? pretrainedG.split('/').pop() : t('training.pickPretrainedG')}
              </span>
            </button>
            {recommendedG && (
              <WeightHint
                item={recommendedG}
                mismatch={gMismatch}
                mismatchText={t('training.pretrainedMismatch')}
                recommendedText={t('training.recommendedWeight', {
                  file: recommendedG.fileName,
                })}
                downloadText={t('training.downloadRecommended')}
                onOpen={handleOpenDownload}
              />
            )}
          </label>

          <label className={styles.field}>
            <span>{t('training.pretrainedD')}</span>
            <button
              type="button"
              className={styles.pathBtn}
              onClick={() => void handlePickPretrained('d')}
              disabled={isRunning}
            >
              <FolderOpen />
              <span title={pretrainedD ?? undefined}>
                {pretrainedD ? pretrainedD.split('/').pop() : t('training.pickPretrainedD')}
              </span>
            </button>
            {recommendedD && (
              <WeightHint
                item={recommendedD}
                mismatch={dMismatch}
                mismatchText={t('training.pretrainedMismatch')}
                recommendedText={t('training.recommendedWeight', {
                  file: recommendedD.fileName,
                })}
                downloadText={t('training.downloadRecommended')}
                onOpen={handleOpenDownload}
              />
            )}
          </label>

          <label className={styles.checkField}>
            <input
              type="checkbox"
              checked={cacheGpu}
              onChange={(e) => setCacheGpu(e.target.checked)}
              disabled={isRunning || !useGpu || !gpuAvailable}
            />
            <span>
              <strong>{t('training.cacheGpu')}</strong>
              <small>{t('training.cacheGpuHint')}</small>
            </span>
          </label>

          <label className={styles.checkField}>
            <input
              type="checkbox"
              checked={saveLatestOnly}
              onChange={(e) => setSaveLatestOnly(e.target.checked)}
              disabled={isRunning}
            />
            <span>
              <strong>{t('training.saveLatestOnly')}</strong>
              <small>{t('training.saveLatestOnlyHint')}</small>
            </span>
          </label>

          <label className={styles.checkField}>
            <input
              type="checkbox"
              checked={saveEveryWeights}
              onChange={(e) => setSaveEveryWeights(e.target.checked)}
              disabled={isRunning}
            />
            <span>
              <strong>{t('training.saveEveryWeights')}</strong>
              <small>{t('training.saveEveryWeightsHint')}</small>
            </span>
          </label>
        </div>
      </div>

      <p className={styles.hint}>{t('training.envHint')}</p>

      <div className={styles.actions}>
        {!isRunning ? (
          <button
            type="button"
            className={styles.primaryBtn}
            disabled={!canStart}
            onClick={handleStart}
          >
            <Zap />
            {t('training.start')}
          </button>
        ) : (
          <button type="button" className={styles.cancelBtn} onClick={() => void cancel()}>
            <X />
            {t('training.cancel')}
          </button>
        )}
      </div>

      {job && (
        <div className={styles.progressBox} data-state={job.state}>
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
              {t(`training.state.${job.state}`)}
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

          {(job.pthPath || job.indexPath || job.logPath) && (
            <div className={styles.results}>
              {job.pthPath && (
                <ResultRow label={t('training.pth')} path={job.pthPath} onOpen={handleOpen} />
              )}
              {job.indexPath && (
                <ResultRow
                  label={t('training.index')}
                  path={job.indexPath}
                  onOpen={handleOpen}
                />
              )}
              {job.logPath && (
                <ResultRow label={t('training.log')} path={job.logPath} onOpen={handleOpen} />
              )}
            </div>
          )}

          {isDone && job.pthPath && (
            <div className={styles.importOutputBox}>
              <div>
                <strong>{t('training.importOutputTitle')}</strong>
                <span>{t('training.importOutputDesc')}</span>
              </div>
              <button
                type="button"
                className={styles.primaryBtn}
                onClick={() => void handleImportTrainingOutput()}
                disabled={importingOutput}
              >
                {importingOutput ? <Loader2 className={styles.spin} /> : <CircleCheck />}
                {t('training.importOutput')}
              </button>
            </div>
          )}

          {(isFailed || error) && <p className={styles.error}>{job.error ?? error}</p>}
        </div>
      )}
    </div>
  );
});

function pickPretrained(
  catalog: PretrainedWeightInfo[],
  kind: 'G' | 'D',
  version: 'v1' | 'v2',
  sampleRate: number,
) {
  return catalog.find(
    (item) =>
      item.kind.toUpperCase() === kind &&
      item.version === version &&
      item.sampleRate === sampleRate,
  );
}

function WeightHint({
  item,
  recommendedText,
  mismatch,
  mismatchText,
  downloadText,
  onOpen,
}: {
  item: PretrainedWeightInfo;
  recommendedText: string;
  mismatch: boolean;
  mismatchText: string;
  downloadText: string;
  onOpen: (url: string) => Promise<void>;
}) {
  return (
    <div className={styles.weightHint} data-mismatch={mismatch || undefined}>
      <span>{mismatch ? mismatchText : recommendedText}</span>
      <button type="button" onClick={() => void onOpen(item.url)}>
        <Download />
        {downloadText}
      </button>
    </div>
  );
}

function ResultRow({
  label,
  path,
  onOpen,
}: {
  label: string;
  path: string;
  onOpen: (path: string) => void;
}) {
  return (
    <div className={styles.resultRow}>
      <span className={styles.resultLabel}>{label}</span>
      <code className={styles.resultPath} title={path}>
        {path}
      </code>
      <button type="button" className={styles.resultBtn} onClick={() => onOpen(path)}>
        <ScrollText />
      </button>
    </div>
  );
}
