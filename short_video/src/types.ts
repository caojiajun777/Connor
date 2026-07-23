export type StoryProps = {
  role: 'lead' | 'support';
  title: string;
  narration: string;
  keyPoint: string;
  slideBody: string;
  commentary: string;
  source: string;
  uncertainty: 'confirmed' | 'unconfirmed';
  image: string | null;
  eventId: string;
};

export type TimedSegmentProps = {
  id: string;
  kind: 'hook' | 'intro' | 'story' | 'outro';
  text: string;
  storyIndex: number | null;
  startMs: number;
  endMs: number;
  pauseAfterMs: number;
};

export type CaptionCueProps = {
  index: number;
  startMs: number;
  endMs: number;
  text: string;
};

export type ConnorDailyShortProps = {
  reportDate: string;
  hook: string;
  outro: string;
  stories: StoryProps[];
  segments: TimedSegmentProps[];
  captions: CaptionCueProps[];
  durationMs: number;
  audioPath: string | null;
  siteUrl: string;
};

export const FPS = 30;
export const WIDTH = 1080;
export const HEIGHT = 1920;

export const defaultProps: ConnorDailyShortProps = {
  reportDate: '2026-07-22',
  hook: '各位观众上午好，欢迎收看今日的Connor AI速报。',
  outro: '完整日报与原始信源，可以前往 aiconnor.cn 查看。',
  stories: [
    {
      role: 'lead',
      title: 'OpenAI 更新 Agent 工具',
      narration: 'OpenAI 正在进一步提高 Agent 处理长任务的能力。',
      keyPoint: 'Coding Agent 可处理更复杂的项目',
      slideBody:
        'OpenAI 进一步提高 Agent 处理长任务的能力。官方称 Coding Agent 可覆盖更复杂的项目流程，并强化多步工具调用的稳定性，适合团队把长链路研发任务交给自动化代理。',
      commentary: '',
      source: '@OpenAI',
      uncertainty: 'confirmed',
      image: null,
      eventId: 'evt_1',
    },
  ],
  segments: [
    {
      id: 'intro',
      kind: 'intro',
      text: '各位观众上午好，欢迎收看今日的Connor AI速报。',
      storyIndex: null,
      startMs: 0,
      endMs: 4000,
      pauseAfterMs: 0,
    },
    {
      id: 'story_0',
      kind: 'story',
      text: 'OpenAI 正在进一步提高 Agent 处理长任务的能力。',
      storyIndex: 0,
      startMs: 4000,
      endMs: 12000,
      pauseAfterMs: 0,
    },
    {
      id: 'outro',
      kind: 'outro',
      text: '完整日报与原始信源，可以前往 aiconnor.cn 查看。',
      storyIndex: null,
      startMs: 12000,
      endMs: 16000,
      pauseAfterMs: 0,
    },
  ],
  captions: [
    {
      index: 1,
      startMs: 0,
      endMs: 4000,
      text: '各位观众上午好，欢迎收看今日的Connor AI速报。',
    },
  ],
  durationMs: 16000,
  audioPath: null,
  siteUrl: 'aiconnor.cn',
};

export const msToFrames = (ms: number, fps = FPS): number =>
  Math.max(1, Math.round((ms / 1000) * fps));
