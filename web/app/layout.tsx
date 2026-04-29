import type { Metadata, Viewport } from "next";
import { Analytics } from "@vercel/analytics/next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Shorelife | Daily California beach health forecasts",
  description:
    "Daily California beach health forecasts built from official bacteria samples, surf context, and coastal environmental data.",
  applicationName: "Shorelife",
  metadataBase: new URL("https://kylechoi101.github.io/surf-health"),
  icons: {
    icon: [
      {
        url: "/icon-light-32x32.png",
        media: "(prefers-color-scheme: light)",
      },
      {
        url: "/icon-dark-32x32.png",
        media: "(prefers-color-scheme: dark)",
      },
    ],
    apple: "/apple-icon.png",
  },
  openGraph: {
    title: "Shorelife | Daily California beach health forecasts",
    description:
      "Daily California beach health forecasts built from official bacteria samples, surf context, and coastal environmental data.",
    siteName: "Shorelife",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Shorelife | Daily California beach health forecasts",
    description:
      "Daily California beach health forecasts built from official bacteria samples, surf context, and coastal environmental data.",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="bg-background">
      <body className="min-h-screen font-sans antialiased">
        {children}
        {process.env.NODE_ENV === "production" && <Analytics />}
      </body>
    </html>
  );
}
