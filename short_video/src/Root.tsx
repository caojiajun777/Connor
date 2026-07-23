import React from 'react';
import {Composition, getInputProps} from 'remotion';
import {ConnorDailyCover, ConnorDailyShort} from './ConnorDailyShort';
import {
  ConnorDailyShortProps,
  FPS,
  HEIGHT,
  WIDTH,
  defaultProps,
  msToFrames,
} from './types';

const calcDuration = (props: ConnorDailyShortProps) =>
  Math.max(FPS, msToFrames(props.durationMs || defaultProps.durationMs));

export const RemotionRoot: React.FC = () => {
  const input = getInputProps() as Partial<ConnorDailyShortProps>;
  const merged: ConnorDailyShortProps = {
    ...defaultProps,
    ...input,
    stories: input.stories ?? defaultProps.stories,
    segments: input.segments ?? defaultProps.segments,
    captions: input.captions ?? defaultProps.captions,
  };

  return (
    <>
      <Composition
        id="ConnorDailyShort"
        component={ConnorDailyShort}
        durationInFrames={calcDuration(merged)}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={defaultProps}
        calculateMetadata={({props}) => ({
          durationInFrames: calcDuration(props as ConnorDailyShortProps),
        })}
      />
      <Composition
        id="ConnorDailyCover"
        component={ConnorDailyCover}
        durationInFrames={FPS}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={defaultProps}
      />
    </>
  );
};
