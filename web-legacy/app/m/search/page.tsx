"use client";
import { useEffect, useState } from "react";
import { getBeaches, type BeachSummary } from "@/lib/api";
import SearchScreen from "./SearchScreen";

export default function SearchPage() {
  const [beaches, setBeaches] = useState<BeachSummary[]>([]);
  useEffect(() => { getBeaches().then(setBeaches); }, []);
  return <SearchScreen beaches={beaches} />;
}
