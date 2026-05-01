"use client";
import { useEffect, useState } from "react";
import { getBeaches, type BeachSummary } from "@/lib/api";
import { filterModeledBeaches } from "@/lib/coverage";
import SearchScreen from "./SearchScreen";

export default function SearchPage() {
  const [beaches, setBeaches] = useState<BeachSummary[]>([]);
  useEffect(() => { getBeaches().then((items) => setBeaches(filterModeledBeaches(items))); }, []);
  return <SearchScreen beaches={beaches} />;
}
