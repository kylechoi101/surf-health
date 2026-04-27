import StickyHeader from "@/components/StickyHeader";

export default function DesktopLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="site-shell">
      <StickyHeader />
      {children}
    </div>
  );
}
