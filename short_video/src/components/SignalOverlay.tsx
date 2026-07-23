import React from 'react';
import {AbsoluteFill} from 'remotion';

/** Very light grain for soft paper feel — no CRT / cyber look. */
export const SignalOverlay: React.FC<{intensity?: number}> = ({intensity = 0.025}) => {
  return (
    <AbsoluteFill
      style={{
        pointerEvents: 'none',
        opacity: intensity,
        backgroundImage:
          'radial-gradient(circle at 1px 1px, rgba(0,0,0,0.05) 1px, transparent 0)',
        backgroundSize: '16px 16px',
      }}
    />
  );
};

export const GlitchFlash: React.FC<{activeFrames?: number}> = () => null;
