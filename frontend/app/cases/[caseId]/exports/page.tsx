import { CaseSectionView } from "@/components/case-section-view";


export default function ExportsPage({ params }: { params: { caseId: string } }) {
  return <CaseSectionView caseId={params.caseId} section="exports" />;
}
