export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export function formatSampleRate(sr: number): string {
  if (sr <= 0) return '—';
  return `${(sr / 1000).toFixed(1)} kHz`;
}

export function formatPitch(semitones: number): string {
  if (semitones === 0) return '0';
  return semitones > 0 ? `+${semitones}` : `${semitones}`;
}

export function levelToPercent(level: number): number {
  return clamp(Math.round(level * 100), 0, 100);
}
