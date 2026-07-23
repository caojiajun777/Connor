import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import type {StoryProps} from '../types';
import {FONT_STACK, colors, radii, shadows} from '../theme';

const pad = (n: number, width = 2) => String(n).padStart(width, '0');

/** Split slide body into short bullet lines. */
const bodyBullets = (text: string, max = 6): string[] => {
  const cleaned = text.replace(/\s+/g, ' ').trim();
  if (!cleaned) {
    return [];
  }
  const sentences = cleaned
    .split(/(?<=[。！？；;])/)
    .map((s) => s.trim().replace(/^[•·\-\s]+/, ''))
    .filter(Boolean);
  if (sentences.length <= 1) {
    const parts = cleaned
      .split(/[，,]/)
      .map((s) => s.trim())
      .filter((s) => s.length >= 8);
    if (parts.length >= 2) {
      return parts.slice(0, max);
    }
    return [cleaned];
  }
  return sentences.slice(0, max);
};

/** Soft inline chips for Latin product / tech tokens (Connor pill style). */
const renderRichLine = (line: string): React.ReactNode => {
  const parts = line.split(/([A-Za-z][A-Za-z0-9.\-+/]{1,})/g);
  return parts.map((part, i) => {
    if (/^[A-Za-z][A-Za-z0-9.\-+/]{1,}$/.test(part) && part.length >= 2) {
      return (
        <span
          key={`${part}-${i}`}
          style={{
            display: 'inline',
            background: colors.pillBg,
            borderRadius: radii.chip,
            padding: '3px 10px',
            margin: '0 3px',
            color: colors.inkSoft,
            fontWeight: 600,
            fontSize: '0.94em',
          }}
        >
          {part}
        </span>
      );
    }
    return <React.Fragment key={i}>{part}</React.Fragment>;
  });
};

const SectionIcon: React.FC<{lead?: boolean}> = ({lead}) => (
  <svg width="32" height="32" viewBox="0 0 28 28" fill="none" aria-hidden>
    {lead ? (
      <path
        d="M14 4l2.4 7.2H24l-6 4.4 2.3 7.2L14 18.8 7.7 22.8l2.3-7.2-6-4.4h7.6L14 4z"
        stroke={colors.signal}
        strokeWidth="2"
        strokeLinejoin="round"
      />
    ) : (
      <path
        d="M8 9h12M8 14h12M8 19h8"
        stroke={colors.signal}
        strokeWidth="2.2"
        strokeLinecap="round"
      />
    )}
  </svg>
);

export const StoryScene: React.FC<{
  story: StoryProps;
  index: number;
  total: number;
}> = ({story, index, total}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({frame, fps, config: {damping: 18, stiffness: 90}});
  const cardY = interpolate(enter, [0, 1], [20, 0]);
  const bodyOpacity = interpolate(enter, [0, 1], [0.15, 1]);
  const bullets = bodyBullets(story.slideBody || story.narration || story.keyPoint);

  return (
    <AbsoluteFill
      style={{
        background: `linear-gradient(180deg, ${colors.bgSoft} 0%, ${colors.bg} 72%, #ffffff 100%)`,
        color: colors.text,
        fontFamily: FONT_STACK,
      }}
    >
      <AbsoluteFill
        style={{
          padding: '72px 40px 220px',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            color: colors.textTertiary,
            fontSize: 26,
            fontWeight: 600,
            flexShrink: 0,
          }}
        >
          <span style={{color: colors.signal, fontWeight: 700}}>Connor · AI 速报</span>
          <span>
            {pad(index + 1)} / {pad(total)}
          </span>
        </div>

        <div
          style={{
            marginTop: 22,
            flex: 1,
            minHeight: 0,
            transform: `translateY(${cardY}px)`,
            background: colors.card,
            borderRadius: radii.card,
            boxShadow: shadows.card,
            border: `1px solid ${colors.hairline}`,
            padding: '40px 36px 36px',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              marginBottom: 20,
              flexShrink: 0,
            }}
          >
            <SectionIcon lead={story.role === 'lead'} />
            <div
              style={{
                color: colors.signal,
                fontSize: 28,
                fontWeight: 700,
              }}
            >
              {story.role === 'lead' ? '头条速报' : '今日速报'}
              {story.uncertainty === 'unconfirmed' ? ' · 未确认' : ''}
            </div>
          </div>

          <div
            style={{
              fontSize: 52,
              fontWeight: 700,
              lineHeight: 1.26,
              letterSpacing: '-0.02em',
              color: colors.text,
              flexShrink: 0,
            }}
          >
            {story.title}
          </div>

          {story.keyPoint ? (
            <div
              style={{
                marginTop: 16,
                fontSize: 32,
                lineHeight: 1.42,
                color: colors.accentDark,
                fontWeight: 600,
                flexShrink: 0,
              }}
            >
              {story.keyPoint}
            </div>
          ) : null}

          <div
            style={{
              marginTop: 28,
              opacity: bodyOpacity,
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'flex-start',
              gap: 18,
            }}
          >
            {bullets.map((line, i) => (
              <div
                key={i}
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 16,
                }}
              >
                <div
                  style={{
                    width: 12,
                    height: 12,
                    borderRadius: radii.pill,
                    background: colors.signal,
                    marginTop: 18,
                    flexShrink: 0,
                  }}
                />
                <div
                  style={{
                    fontSize: 38,
                    lineHeight: 1.52,
                    color: colors.inkSoft,
                    fontWeight: 500,
                    flex: 1,
                  }}
                >
                  {renderRichLine(line)}
                </div>
              </div>
            ))}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
