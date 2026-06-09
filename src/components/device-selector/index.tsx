import { memo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, RefreshCw, type LucideIcon } from 'lucide-react';
import type { AudioDeviceInfo } from '@/types';
import { formatSampleRate } from '@/utils/format';
import styles from './styles.module.css';

interface DeviceSelectorProps {
  label: string;
  Icon: LucideIcon;
  placeholder: string;
  devices: AudioDeviceInfo[];
  value: string | null;
  onChange: (name: string) => void;
  onRefresh: () => void;
}

function DeviceSelectorImpl({
  label,
  Icon,
  placeholder,
  devices,
  value,
  onChange,
  onRefresh,
}: DeviceSelectorProps) {
  const { t } = useTranslation();

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      onChange(e.target.value);
    },
    [onChange],
  );

  return (
    <div className={styles.wrapper}>
      <div className={styles.header}>
        <span className={styles.label}>
          <Icon />
          {label}
        </span>
        <button type="button" className={styles.refreshBtn} onClick={onRefresh}>
          <RefreshCw />
          {t('device.refresh')}
        </button>
      </div>
      <div className={styles.selectWrap}>
        <select className={styles.select} value={value ?? ''} onChange={handleChange}>
          <option value="" disabled>
            {placeholder}
          </option>
          {devices.map((d) => (
            <option key={d.name} value={d.name}>
              {d.is_virtual_cable ? '◉ ' : ''}
              {d.name}
              {d.sample_rate > 0 ? ` · ${formatSampleRate(d.sample_rate)}` : ''}
              {d.is_default ? ` · ${t('device.default')}` : ''}
            </option>
          ))}
        </select>
        <span className={styles.chevron} aria-hidden>
          <ChevronDown />
        </span>
      </div>
    </div>
  );
}

export const DeviceSelector = memo(DeviceSelectorImpl);
