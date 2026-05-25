import { Coffee, Crown, Flame, Mountain, Sparkles, type LucideIcon } from 'lucide-react';
import type { VoiceId } from '@/types';

export interface VoicePreset {
  id: VoiceId;
  i18nKey: string;
  Icon: LucideIcon;
  /** CSS 变量名，引用 styles/variables.css 中的 --voice-* */
  colorVar: string;
  defaultPitch: number;
  gender: 'female' | 'male';
}

export const VOICE_PRESETS: ReadonlyArray<VoicePreset> = [
  {
    id: 'yujie',
    i18nKey: 'voice.yujie',
    Icon: Crown,
    colorVar: 'var(--voice-yujie)',
    defaultPitch: 0,
    gender: 'female',
  },
  {
    id: 'loli',
    i18nKey: 'voice.loli',
    Icon: Sparkles,
    colorVar: 'var(--voice-loli)',
    defaultPitch: 12,
    gender: 'female',
  },
  {
    id: 'shaonian',
    i18nKey: 'voice.shaonian',
    Icon: Flame,
    colorVar: 'var(--voice-shaonian)',
    defaultPitch: 6,
    gender: 'male',
  },
  {
    id: 'naiqing',
    i18nKey: 'voice.naiqing',
    Icon: Coffee,
    colorVar: 'var(--voice-naiqing)',
    defaultPitch: 2,
    gender: 'female',
  },
  {
    id: 'qingshu',
    i18nKey: 'voice.qingshu',
    Icon: Mountain,
    colorVar: 'var(--voice-qingshu)',
    defaultPitch: 0,
    gender: 'male',
  },
] as const;

export const PITCH_RANGE = { min: -24, max: 24, step: 1 } as const;
