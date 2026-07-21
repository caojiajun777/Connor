/**
 * Cobalt high-tech page atmosphere — flowing washes aligned with the
 * homepage CRT continuum. Full absolute coverage, no WebGL gaps.
 */
export function ReportShaderBackground() {
  return (
    <div className="report-atmosphere" aria-hidden>
      <div className="report-atmosphere-base" />
      <div className="report-atmosphere-flow report-atmosphere-flow-a" />
      <div className="report-atmosphere-flow report-atmosphere-flow-b" />
      <div className="report-atmosphere-flow report-atmosphere-flow-c" />
      <div className="report-atmosphere-grid" />
      <div className="report-atmosphere-scan" />
      <div className="report-atmosphere-grain" />
      <div className="report-atmosphere-veil" />
    </div>
  );
}
