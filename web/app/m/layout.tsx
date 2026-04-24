import type { Metadata, Viewport } from "next";
import "./mobile.css";

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
    <div className="sh-app-root">
      {children}
    </div>
  );
}
