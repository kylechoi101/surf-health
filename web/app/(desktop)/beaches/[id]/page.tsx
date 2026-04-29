import { getBeaches } from "@/lib/api";
import BeachDetail from "./BeachDetail";

export async function generateStaticParams() {
  try {
    const beaches = await getBeaches({ cache: 'force-cache' });
    return beaches.map((b) => ({
      id: b.id,
    }));
  } catch (err) {
    return [{ id: "_" }];
  }
}

export default async function Page(props: { params: Promise<{ id: string }> }) {
  await props.params;
  return <BeachDetail />;
}
