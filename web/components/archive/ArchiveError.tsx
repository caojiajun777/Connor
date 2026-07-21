export function ArchiveError() {
  return (
    <div className="apple-tile px-8 py-16 text-center">
      <p className="text-[24px] font-semibold tracking-tight text-text-primary">
        Temporarily unavailable
      </p>
      <p className="mx-auto mt-3 max-w-md text-[17px] text-text-secondary">
        Could not load reports. Please try again in a moment.
      </p>
    </div>
  );
}
