import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Surf Health",
  description: "California marine beach health forecasts for surfers and beachgoers"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
