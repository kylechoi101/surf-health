"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { IconHome, IconSearch } from "./Icons";

export default function TabBar({ beachId }: { beachId?: string }) {
  const path = usePathname();
  const isHome = beachId && (path === `/m/beach/${beachId}` || path === `/m`);
  const isSearch = path === "/m/search" || path === "/m";

  return (
    <nav className="sh-tabbar">
      <Link href={beachId ? `/m/beach/${beachId}` : "/m"} className={`sh-tab ${isHome ? "active" : ""}`}>
        <IconHome />
        <span>Today</span>
      </Link>
      <Link href="/m/search" className={`sh-tab ${path === "/m/search" ? "active" : ""}`}>
        <IconSearch />
        <span>Search</span>
      </Link>
    </nav>
  );
}
