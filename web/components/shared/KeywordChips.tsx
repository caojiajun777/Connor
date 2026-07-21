interface KeywordChipsProps {
  keywords: string[];
}

export function KeywordChips({ keywords }: KeywordChipsProps) {
  if (!keywords.length) return null;

  return (
    <ul className="flex flex-wrap justify-center gap-2">
      {keywords.map((kw, index) => (
        <li
          key={kw}
          className="chip anim-fade-in"
          style={{ animationDelay: `${Math.min(index, 6) * 40}ms` }}
        >
          {kw}
        </li>
      ))}
    </ul>
  );
}
