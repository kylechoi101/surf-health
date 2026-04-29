"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { IconHome, IconSearch } from "./Icons";

export default function TabBar({ beachId }: { beachId?: string }) {
  const path = usePathname();
  const isHome = beachId && (path === `/m/beach/${beachId}` || path === `/m`);
  const isSearch = path === "/m/search" || path === "/m";

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 flex justify-around items-start pt-2 pb-[max(22px,env(safe-area-inset-bottom))] bg-background/95 backdrop-blur-md border-t border-border/50">
      <Link href={beachId ? `/m/beach/${beachId}` : "/m"} 
        className={`flex-1 flex flex-col items-center gap-1 py-1.5 font-sans text-[10px] font-semibold whitespace-nowrap transition-colors ${
          isHome ? "text-primary" : "text-muted-foreground hover:text-foreground"
        }`}>
        <IconHome />
        <span>Today</span>
      </Link>
      <Link href="/m/search" 
        className={`flex-1 flex flex-col items-center gap-1 py-1.5 font-sans text-[10px] font-semibold whitespace-nowrap transition-colors ${
          path === "/m/search" ? "text-primary" : "text-muted-foreground hover:text-foreground"
        }`}>
        <IconSearch />
        <span>Search</span>
      </Link>
    </nav>
  );
}
