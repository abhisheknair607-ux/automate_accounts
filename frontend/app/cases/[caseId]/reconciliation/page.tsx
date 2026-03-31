import { CaseSectionView } from "@/components/case-section-view";


export default function ReconciliationPage({ params }: { params: { caseId: string } }) {
  return <CaseSectionView caseId={params.caseId} section="reconciliation" />;
}
