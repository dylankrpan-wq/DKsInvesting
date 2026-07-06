import { PageHeader } from "@/components/PageHeader";
import { PipelineBoard } from "@/components/pipeline/PipelineBoard";
import { allRows } from "@/lib/analytics";

export default function PipelinePage() {
  const rows = allRows();
  return (
    <>
      <PageHeader title="Deal Pipeline" subtitle="Track acquisitions through the funnel · drag cards between stages" />
      <PipelineBoard rows={rows} />
    </>
  );
}
