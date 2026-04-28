import type { Metadata } from "next";
import { Fraunces, Inter, JetBrains_Mono } from "next/font/google";

import "./globals.css";

const fraunces = Fraunces({ subsets: ["latin"], variable: "--font-fraunces" });
const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const jetbrainsMono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains" });

export const metadata: Metadata = {
  title: "Shorelife — Know before you paddle out",
  description: "Daily bacteria + surf health forecasts for 300+ California beaches.",
  metadataBase: new URL("https://shorelife.app"),
  icons: {
    icon: "/icon.svg",
    apple: "/apple-icon.png",
  },
  manifest: "/manifest.json",
  openGraph: {
    type: "website",
    url: "https://shorelife.app",
    siteName: "Shorelife",
    title: "Shorelife — Know before you paddle out",
    description: "Daily bacteria + surf health forecasts for 300+ California beaches.",
    images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: "Shorelife — California beach health forecasts" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Shorelife — Know before you paddle out",
    description: "Daily bacteria + surf health forecasts for 300+ California beaches.",
    images: ["/opengraph-image"],
  },
};

const jsonLd = {
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Organization",
      "name": "Shorelife",
      "url": "https://shorelife.app",
      "description": "Open-source California coastal water quality forecasting.",
      "email": "kylechoidsc@gmail.com",
      "sameAs": ["https://github.com/kylechoi101/surf-health"],
    },
    {
      "@type": "Dataset",
      "name": "Shorelife Coastal Water Quality Forecasts",
      "description": "Daily calibrated bacterial exceedance probability forecasts for 300+ California beaches.",
      "url": "https://shorelife.app/research",
      "creator": { "@type": "Organization", "name": "Shorelife" },
      "spatialCoverage": "California, USA",
      "license": "https://opensource.org/licenses/MIT",
      "distribution": {
        "@type": "DataDownload",
        "contentUrl": "https://surf-health-api.onrender.com/beaches",
        "encodingFormat": "application/json",
      },
    },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${fraunces.variable} ${inter.variable} ${jetbrainsMono.variable}`}>
      <head>
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
      </head>
      <body className="font-sans antialiased selection:bg-accent selection:text-accent-foreground">
        {children}
      </body>
    </html>
  );
}
