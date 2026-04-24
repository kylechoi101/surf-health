import { getBeaches } from "@/lib/api";
import SearchScreen from "./SearchScreen";

export const revalidate = 300;

export default async function SearchPage() {
  const beaches = await getBeaches();
  return <SearchScreen beaches={beaches} />;
}
