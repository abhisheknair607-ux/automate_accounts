import { redirect } from "next/navigation";


export default function ExceptionsPage({ params }: { params: { caseId: string } }) {
  redirect(`/cases/${params.caseId}/reconciliation`);
}
