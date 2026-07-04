import { PageHeader } from "@/components/PageHeader";
import { RollupFinder } from "@/components/RollupFinder";

export default function RollupPage() {
  return (
    <>
      <PageHeader
        title="Roll-Up Opportunity Finder"
        subtitle="Cluster fragmented same-industry targets into a platform and model the consolidation economics"
      />
      <RollupFinder />
    </>
  );
}
