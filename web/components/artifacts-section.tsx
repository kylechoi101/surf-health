import Link from "next/link";
import {
  Activity,
  BookOpen,
  Code2,
  ExternalLink,
  FileText,
  LineChart,
  ShieldCheck,
} from "lucide-react";

const artifacts = [
  {
    type: "Method",
    title: "Methodology",
    description: "Model design, promotion rules, limitations, and scientific references.",
    href: "/methodology",
    icon: BookOpen,
  },
  {
    type: "Research",
    title: "Risk labels",
    description: "How public bands map to exceedance thresholds and why unsupported sites stay neutral.",
    href: "/research/labels",
    icon: ShieldCheck,
  },
  {
    type: "Research",
    title: "Data sources",
    description: "BeachWatch, CDIP, NDBC, Open-Meteo, USGS, and the curated warehouse behind the forecast.",
    href: "/research/sources",
    icon: FileText,
  },
  {
    type: "Research",
    title: "Calibration",
    description: "Production metrics, spatial holdouts, and the latest promotion status from pipeline output.",
    href: "/research/calibration",
    icon: LineChart,
  },
  {
    type: "Open data",
    title: "Model registry JSON",
    description: "The tracked model-version artifact in the public repository.",
    href: "https://raw.githubusercontent.com/kylechoi101/surf-health/main/data/curated/model_version.json",
    icon: Activity,
    external: true,
  },
  {
    type: "Code",
    title: "Source repository",
    description: "Backend, mobile, web, and data pipeline code for the Shorelife stack.",
    href: "https://github.com/kylechoi101/surf-health",
    icon: Code2,
    external: true,
  },
];

export function ArtifactsSection() {
  return (
    <section id="artifacts" className="bg-[var(--sl-ecru)]">
      <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8 lg:py-24">
        <div className="flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-3xl">
            <div className="sl-eyebrow text-[var(--sl-sun-deep)]">Open artifacts</div>
            <h2 className="sl-display mt-4 text-4xl text-[var(--sl-navy-ink)] sm:text-5xl">
              Read the sources behind the forecast.
            </h2>
            <p className="mt-5 text-lg leading-8 text-[var(--sl-muted)]">
              This section only links to real documents, real routes, and the real repository. No
              fabricated authors, no fake download counters, no decorative placeholder artifacts.
            </p>
          </div>

          <Link
            href="https://github.com/kylechoi101/surf-health"
            target="_blank"
            className="sl-label inline-flex items-center gap-2 text-[var(--sl-navy)]"
          >
            Open GitHub
            <ExternalLink className="h-4 w-4" />
          </Link>
        </div>

        <div className="mt-10 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          {artifacts.map((artifact) => (
            <Link
              key={artifact.title}
              href={artifact.href}
              target={artifact.external ? "_blank" : undefined}
              className="paper-panel group flex h-full flex-col justify-between rounded-[1.75rem] p-6 transition-transform hover:-translate-y-1"
            >
              <div>
                <div className="flex items-start justify-between gap-4">
                  <span className="sl-label rounded-full bg-[var(--sl-ecru-deep)] px-3 py-1 text-[var(--sl-navy)]">
                    {artifact.type}
                  </span>
                  <artifact.icon className="h-5 w-5 text-[var(--sl-muted)] transition-colors group-hover:text-[var(--sl-navy)]" />
                </div>

                <h3 className="mt-6 text-2xl font-medium text-[var(--sl-navy)]">{artifact.title}</h3>
                <p className="mt-4 text-sm leading-7 text-[var(--sl-muted)]">{artifact.description}</p>
              </div>

              <div className="sl-label mt-8 flex items-center gap-2 text-[var(--sl-navy)]">
                {artifact.external ? "Open link" : "Read page"}
                {artifact.external ? (
                  <ExternalLink className="h-4 w-4" />
                ) : (
                  <BookOpen className="h-4 w-4" />
                )}
              </div>
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}
