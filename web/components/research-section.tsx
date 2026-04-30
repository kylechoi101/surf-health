import Link from "next/link";
import {
  Activity,
  AlertTriangle,
  Dna,
  Droplets,
  FlaskConical,
  Microscope,
} from "lucide-react";

const researchAreas = [
  {
    icon: Microscope,
    title: "Fecal indicator bacteria",
    description:
      "The live daily forecast estimates Enterococcus exceedance risk from official California sample history plus coastal and weather covariates.",
    status: "Active",
    href: "/research",
  },
  {
    icon: FlaskConical,
    title: "Harmful algal blooms",
    description:
      "Planned. Not yet in the production forecast, but on the research roadmap for broader water-health context.",
    status: "Planned",
  },
  {
    icon: Dna,
    title: "Microbial diversity",
    description:
      "Planned. Community composition work remains outside the current public release and is not surfaced as a user-facing risk signal.",
    status: "Planned",
  },
  {
    icon: Activity,
    title: "Pathogen detection",
    description:
      "Planned. The current product does not claim direct pathogen detection beyond FIB-based risk forecasting.",
    status: "Planned",
  },
  {
    icon: Droplets,
    title: "Source tracking",
    description:
      "Planned. Useful for future diagnostic workflows, but not part of today’s modeled public output.",
    status: "Planned",
  },
  {
    icon: AlertTriangle,
    title: "Health risk assessment",
    description:
      "Planned. Quantitative exposure work is still research-only and not exposed as a production risk score today.",
    status: "Planned",
  },
];

export function ResearchSection() {
  return (
    <section id="research" className="border-b border-[var(--sl-line)] bg-[var(--sl-bone)]">
      <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8 lg:py-24">
        <div className="max-w-3xl">
          <div className="sl-eyebrow text-[var(--sl-sun-deep)]">Research roadmap</div>
          <h2 className="sl-display mt-4 text-4xl text-[var(--sl-navy-ink)] sm:text-5xl">
            What is live, and what is still research.
          </h2>
          <p className="mt-5 text-lg leading-8 text-[var(--sl-muted)]">
            Shorelife’s production forecast is narrow on purpose. Only fecal indicator bacteria
            risk is live today. The rest of this section is roadmap, not disguised feature scope.
          </p>
        </div>

        <div className="mt-10 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          {researchAreas.map((area) => {
            const card = (
              <article className="paper-panel group flex h-full flex-col rounded-[1.75rem] p-6 transition-transform hover:-translate-y-1">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--sl-ecru-deep)] text-[var(--sl-navy)]">
                    <area.icon className="h-5 w-5" />
                  </div>
                  <span
                    className={
                      area.status === "Active"
                        ? "sl-label rounded-full bg-[var(--sl-risk-low-bg)] px-3 py-1 text-[var(--sl-risk-low-ink)]"
                        : "sl-label rounded-full bg-[var(--sl-ecru-deep)] px-3 py-1 text-[var(--sl-muted)]"
                    }
                  >
                    {area.status}
                  </span>
                </div>

                <h3 className="mt-6 text-2xl font-medium text-[var(--sl-navy)]">{area.title}</h3>
                <p className="mt-4 text-sm leading-7 text-[var(--sl-muted)]">{area.description}</p>
              </article>
            );

            return area.href ? (
              <Link key={area.title} href={area.href} className="block">
                {card}
              </Link>
            ) : (
              <div key={area.title}>{card}</div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
