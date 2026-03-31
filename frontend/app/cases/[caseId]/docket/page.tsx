import { CaseSectionView } from "@/components/case-section-view";


export default function DocketPage({ params }: { params: { caseId: string } }) {
  return <CaseSectionView caseId={params.caseId} section="docket" />;
}
