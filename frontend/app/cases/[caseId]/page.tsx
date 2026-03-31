import { CaseOverview } from "@/components/case-overview";


export default function CasePage({ params }: { params: { caseId: string } }) {
  return <CaseOverview caseId={params.caseId} />;
}
