import { Header } from "@/components/header";

export default function DesktopLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="site-shell">
      <Header />
      {children}
    </div>
  );
}
