import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import type {CaptionCueProps} from '../types';
import {FPS} from '../types';
import {FONT_STACK, colors, radii, shadows} from '../theme';

export const DynamicCaptions: React.FC<{
  captions: CaptionCueProps[];
  localTimeMs: number;
}> = ({captions, localTimeMs}) => {
  const frame = useCurrentFrame();
  const active = captions.find(
    (c) => localTimeMs >= c.startMs && localTimeMs < c.endMs,
  );
  if (!active) {
    return null;
  }

  const startFrame = Math.round((active.startMs / 1000) * FPS);
  const local = Math.max(0, frame - startFrame);
  const opacity = interpolate(local, [0, 5], [0.35, 1], {
    extrapolateRight: 'clamp',
  });
  const y = interpolate(local, [0, 5], [8, 0], {extrapolateRight: 'clamp'});

  return (
    <AbsoluteFill
      style={{
        justifyContent: 'flex-end',
        alignItems: 'center',
        paddingBottom: 188,
        paddingLeft: 48,
        paddingRight: 48,
      }}
    >
      <div
        style={{
          opacity,
          transform: `translateY(${y}px)`,
          maxWidth: 960,
          textAlign: 'center',
          color: colors.captionText,
          fontSize: 40,
          lineHeight: 1.4,
          fontWeight: 650,
          letterSpacing: '0.01em',
          whiteSpace: 'pre-line',
          padding: '14px 28px',
          borderRadius: radii.caption,
          background: colors.captionBg,
          boxShadow: shadows.caption,
          fontFamily: FONT_STACK,
        }}
      >
        {active.text}
      </div>
    </AbsoluteFill>
  );
};
