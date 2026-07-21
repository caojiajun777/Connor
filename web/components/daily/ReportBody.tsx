import { Reveal } from "@/components/shared/Reveal";
import type { PublicBodySection } from "@/lib/types/public";

interface ReportBodyProps {
  sections: PublicBodySection[];
}

export function ReportBody({ sections }: ReportBodyProps) {
  if (!sections.length) {
    return null;
  }

  return (
    <div className="mx-auto max-w-[720px] space-y-12">
      {sections.map((section, index) => (
        <Reveal
          key={section.section_id || section.heading}
          as="section"
          soft
          delayMs={Math.min(index, 5) * 55}
        >
          {section.heading ? (
            <h2 className="type-headline text-[22px] sm:text-[28px]">
              {section.heading}
            </h2>
          ) : null}
          <div className={section.heading ? "mt-4 space-y-4" : "space-y-4"}>
            {section.paragraphs.map((paragraph, pIndex) => (
              <p
                key={`${section.section_id || section.heading}-${pIndex}`}
                className="type-body text-[17px] sm:text-[19px]"
              >
                {paragraph}
              </p>
            ))}
          </div>
        </Reveal>
      ))}
    </div>
  );
}
