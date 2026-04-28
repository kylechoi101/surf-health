import React from "react";
import Link from "next/link";
import { promises as fs } from "fs";
import path from "path";
import { LockupHorizontal } from "@/components/Lockup";
import { Github, Twitter, Mail } from "lucide-react";

const footerLinks = [
  {
    title: "Platform",
    links: [
      { name: "Live Forecast", href: "/#forecast" },
      { name: "Coast Map", href: "/#map" },
      { name: "Methodology", href: "/methodology" },
      { name: "Research", href: "/research" },
    ],
  },
  {
    title: "Data",
    links: [
      { name: "API", href: "https://surf-health-api.onrender.com" },
      { name: "Beaches", href: "/beaches" },
    ],
  },
];

export async function ShorelifeFooter() {
  let productionModel = "";
  let buildDate = "";
  try {
    const healthPath = path.join(process.cwd(), "../data/curated/system_health.json");
    const h = JSON.parse(await fs.readFile(healthPath, "utf8"));
    productionModel = h.model_registry.production_model;
    buildDate = (h.pipeline_freshness as string).split("T")[0].replace(/-/g, ".");
  } catch {}

  return (
    <footer className="bg-navy-ink text-bone pt-24 pb-12 overflow-hidden relative">
      <div className="absolute top-0 left-0 right-0 h-px bg-sun opacity-20" />

      <div className="max-w-7xl mx-auto px-6 relative z-10">
        <div className="grid lg:grid-cols-2 gap-20 mb-20">
          <div>
            <div className="mb-10">
              <LockupHorizontal size={32} subtitle="California" ink="var(--sl-bone)" />
            </div>
            <p className="text-bone/60 max-w-sm mb-10 leading-relaxed text-sm">
              An open-source public health project — real-time microbial water quality forecasting
              across the California coastline.
            </p>
            <div className="flex gap-6">
              {[
                { Icon: Github, href: "https://github.com/kylechoi101" },
                { Icon: Twitter, href: "#" },
                { Icon: Mail, href: "mailto:kylechoidsc@gmail.com" },
              ].map(({ Icon, href }, i) => (
                <a
                  key={i}
                  href={href}
                  className="w-10 h-10 rounded-full bg-bone/5 flex items-center justify-center hover:bg-sun hover:text-navy-ink transition-all border border-bone/10"
                >
                  <Icon className="w-4 h-4" />
                </a>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-10">
            {footerLinks.map((group) => (
              <div key={group.title}>
                <h4 className="sl-label text-sun mb-6 text-[11px] tracking-widest">{group.title}</h4>
                <ul className="space-y-4">
                  {group.links.map((link) => (
                    <li key={link.name}>
                      <Link
                        href={link.href}
                        className="text-bone/50 hover:text-bone transition-colors text-[13px] lowercase"
                      >
                        {link.name}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>

        <div className="pt-12 border-t border-bone/10 flex flex-col md:flex-row justify-between items-center gap-6">
          <div className="sl-mono text-[10px] text-bone/40 uppercase tracking-widest">
            © 2026 Shorelife Project · Open Source
          </div>
          <div className="sl-mono text-[10px] text-bone/20 uppercase tracking-tighter">
            {productionModel ? `${productionModel} · build ${buildDate}` : "Built in San Francisco"}
          </div>
        </div>
      </div>
    </footer>
  );
}
