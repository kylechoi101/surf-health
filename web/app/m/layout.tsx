import type { Metadata, Viewport } from "next";

export const metadata: Metadata = {
  title: "Surf Health",
  description: "California beach bacteria forecast",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  viewportFit: "cover",
};

export default function MobileLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-background text-foreground min-h-[100dvh] antialiased">
      {children}
    </div>
  );
}
