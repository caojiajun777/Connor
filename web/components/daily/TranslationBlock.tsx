interface TranslationBlockProps {
  text: string;
}

export function TranslationBlock({ text }: TranslationBlockProps) {
  if (!text.trim()) return null;

  return (
    <div className="mt-5 rounded-[18px] bg-surface px-5 py-4 ring-1 ring-[var(--hairline)]">
      <p className="type-kicker text-[12px]">Translation</p>
      <p className="type-body mt-2 whitespace-pre-wrap text-[17px] text-ink-soft">
        {text}
      </p>
    </div>
  );
}
