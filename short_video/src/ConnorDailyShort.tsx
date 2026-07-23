import React from 'react';
import {AbsoluteFill, Audio, Sequence, staticFile, useCurrentFrame} from 'remotion';
import {HookScene, IntroScene, OutroScene} from './components/BrandScenes';
import {DynamicCaptions} from './components/DynamicCaptions';
import {SignalOverlay} from './components/SignalOverlay';
import {StoryScene} from './components/StoryScene';
import {ConnorDailyShortProps, FPS, msToFrames} from './types';

const resolveAudioSrc = (audioPath: string | null): string | null => {
  if (!audioPath) {
    return null;
  }
  if (audioPath.startsWith('http://') || audioPath.startsWith('https://')) {
    return audioPath;
  }
  // Paths staged under short_video/public/ (e.g. renders/2026-07-22/narration.mp3)
  return staticFile(audioPath.replace(/^\/+/, ''));
};

export const ConnorDailyShort: React.FC<ConnorDailyShortProps> = (props) => {
  const frame = useCurrentFrame();
  const nowMs = (frame / FPS) * 1000;
  const audioSrc = resolveAudioSrc(props.audioPath);

  return (
    <AbsoluteFill style={{backgroundColor: '#fbfbfd'}}>
      {audioSrc ? <Audio src={audioSrc} /> : null}

      {props.segments.map((seg) => {
        const from = msToFrames(seg.startMs);
        const duration = Math.max(1, msToFrames(seg.endMs) - from);
        let body: React.ReactNode = null;
        if (seg.kind === 'hook' || seg.kind === 'intro') {
          body = (
            <IntroScene reportDate={props.reportDate} greeting={props.hook} />
          );
        } else if (seg.kind === 'story' && seg.storyIndex != null) {
          const story = props.stories[seg.storyIndex];
          if (story) {
            body = (
              <StoryScene
                story={story}
                index={seg.storyIndex}
                total={props.stories.length}
              />
            );
          }
        } else if (seg.kind === 'outro') {
          body = <OutroScene outro={props.outro} siteUrl={props.siteUrl} />;
        }
        if (!body) {
          return null;
        }
        return (
          <Sequence key={seg.id} from={from} durationInFrames={duration}>
            {body}
          </Sequence>
        );
      })}

      <DynamicCaptions captions={props.captions} localTimeMs={nowMs} />
      <SignalOverlay />
    </AbsoluteFill>
  );
};

export const ConnorDailyCover: React.FC<ConnorDailyShortProps> = (props) => {
  const lead = props.stories[0];
  return (
    <AbsoluteFill style={{backgroundColor: '#fbfbfd'}}>
      {lead ? (
        <StoryScene story={lead} index={0} total={Math.max(1, props.stories.length)} />
      ) : (
        <HookScene hook={props.hook} />
      )}
      <SignalOverlay intensity={0.02} />
    </AbsoluteFill>
  );
};
