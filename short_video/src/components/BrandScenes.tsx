import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {FONT_STACK, colors, radii, shadows} from '../theme';

export const HookScene: React.FC<{hook: string}> = ({hook}) => {
  return <IntroScene reportDate="" greeting={hook} />;
};

export const IntroScene: React.FC<{
  reportDate: string;
  greeting?: string;
}> = ({reportDate, greeting}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({frame, fps, config: {damping: 16, stiffness: 85}});
  const scale = interpolate(enter, [0, 1], [0.96, 1]);
  const opacity = interpolate(frame, [0, 8], [0, 1], {extrapolateRight: 'clamp'});
  const line =
    (greeting || '').trim() || '各位观众上午好，欢迎收看今日的Connor AI速报。';

  return (
    <AbsoluteFill
      style={{
        background: `linear-gradient(180deg, ${colors.bgSoft} 0%, ${colors.bg} 70%, #ffffff 100%)`,
        alignItems: 'center',
        justifyContent: 'center',
        padding: 72,
        opacity,
        fontFamily: FONT_STACK,
        color: colors.text,
      }}
    >
      <div
        style={{
          transform: `scale(${scale})`,
          textAlign: 'center',
          maxWidth: 920,
          background: colors.card,
          borderRadius: radii.card + 4,
          boxShadow: shadows.card,
          border: `1px solid ${colors.hairline}`,
          padding: '56px 48px',
        }}
      >
        <div
          style={{
            display: 'inline-flex',
            padding: '10px 20px',
            borderRadius: radii.pill,
            background: colors.accentSoft,
            color: colors.signal,
            fontSize: 24,
            fontWeight: 700,
            letterSpacing: '0.06em',
            marginBottom: 28,
          }}
        >
          CONNOR DAILY
        </div>
        <div
          style={{
            fontSize: 50,
            fontWeight: 700,
            lineHeight: 1.4,
            color: colors.text,
          }}
        >
          {line}
        </div>
        {reportDate ? (
          <div
            style={{
              marginTop: 28,
              fontSize: 30,
              color: colors.textSecondary,
              fontWeight: 600,
            }}
          >
            {reportDate}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

export const OutroScene: React.FC<{outro: string; siteUrl: string}> = ({
  outro,
  siteUrl,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({frame, fps, config: {damping: 16, stiffness: 85}});
  const opacity = interpolate(enter, [0, 1], [0.35, 1]);

  return (
    <AbsoluteFill
      style={{
        background: `linear-gradient(180deg, ${colors.bgSoft} 0%, ${colors.bg} 70%, #ffffff 100%)`,
        alignItems: 'center',
        justifyContent: 'center',
        padding: 72,
        fontFamily: FONT_STACK,
        color: colors.text,
        opacity,
      }}
    >
      <div
        style={{
          textAlign: 'center',
          maxWidth: 900,
          background: colors.card,
          borderRadius: radii.card + 4,
          boxShadow: shadows.card,
          border: `1px solid ${colors.hairline}`,
          padding: '52px 44px',
        }}
      >
        <div
          style={{
            fontSize: 42,
            fontWeight: 700,
            lineHeight: 1.45,
            color: colors.text,
          }}
        >
          {outro}
        </div>
        <div
          style={{
            marginTop: 36,
            display: 'inline-flex',
            padding: '14px 28px',
            borderRadius: radii.pill,
            background: colors.accentSoft,
            fontSize: 32,
            color: colors.signal,
            fontWeight: 700,
            letterSpacing: '0.02em',
          }}
        >
          {siteUrl.replace(/^https?:\/\//, '')}
        </div>
      </div>
    </AbsoluteFill>
  );
};
