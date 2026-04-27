import { getBeaches } from "@/lib/api";
import BeachDetail from "./BeachDetail";

export async function generateStaticParams() {
  const beaches = await getBeaches({ cache: 'force-cache' });
  return beaches.map((b) => ({
    id: b.id,
  }));
}

export default async function Page(props: { params: Promise<{ id: string }> }) {
  await props.params;
  return <BeachDetail />;
}
