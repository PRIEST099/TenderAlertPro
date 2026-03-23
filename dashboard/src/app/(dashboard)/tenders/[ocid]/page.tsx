"use client";

import { useState, use } from "react";
import useSWR, { mutate } from "swr";
import { fetchApi, fetcher } from "@/lib/api";
import { formatDate, formatCurrency } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ArrowLeft, Brain, ExternalLink } from "lucide-react";
import Link from "next/link";

interface TenderDetail {
  ocid: string;
  title: string;
  description: string;
  buyer_name: string;
  category: string;
  value_amount: number | null;
  value_currency: string;
  deadline: string | null;
  status: string;
  source_url: string;
  ai_summary: string | null;
  fetched_at: string | null;
}

export default function TenderDetailPage({ params }: { params: Promise<{ ocid: string }> }) {
  const { ocid } = use(params);
  const decodedOcid = decodeURIComponent(ocid);
  const [enriching, setEnriching] = useState(false);
  const [enrichError, setEnrichError] = useState<string | null>(null);

  const { data: tender, error } = useSWR<TenderDetail>(
    `/api/tenders/${encodeURIComponent(decodedOcid)}`,
    fetcher
  );

  async function handleEnrich() {
    setEnriching(true);
    setEnrichError(null);
    try {
      await fetchApi(`/api/tenders/${encodeURIComponent(decodedOcid)}/enrich`, { method: "POST" });
      mutate(`/api/tenders/${encodeURIComponent(decodedOcid)}`);
    } catch (err: unknown) {
      setEnrichError(err instanceof Error ? err.message : "Enrichment failed");
    } finally {
      setEnriching(false);
    }
  }

  if (error) return <p className="text-red-500">Tender not found</p>;
  if (!tender) return <p className="text-slate-400">Loading...</p>;

  return (
    <div className="space-y-6 max-w-3xl">
      <Link href="/tenders" className="flex items-center gap-2 text-sm text-slate-500 hover:text-slate-900">
        <ArrowLeft className="h-4 w-4" /> Back to tenders
      </Link>

      <div>
        <h1 className="text-2xl font-bold text-slate-900">{tender.title}</h1>
        <p className="text-slate-500 mt-1">{tender.buyer_name}</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Tender Details</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <p className="text-slate-500">OCID</p>
              <p className="font-mono text-xs">{tender.ocid}</p>
            </div>
            <div>
              <p className="text-slate-500">Category</p>
              <Badge variant="outline">{tender.category}</Badge>
            </div>
            <div>
              <p className="text-slate-500">Value</p>
              <p className="font-semibold">{formatCurrency(tender.value_amount, tender.value_currency)}</p>
            </div>
            <div>
              <p className="text-slate-500">Deadline</p>
              <p>{formatDate(tender.deadline)}</p>
            </div>
            <div>
              <p className="text-slate-500">Status</p>
              <Badge variant={tender.status === "active" ? "default" : "secondary"}>{tender.status}</Badge>
            </div>
            <div>
              <p className="text-slate-500">Fetched</p>
              <p>{formatDate(tender.fetched_at)}</p>
            </div>
          </div>

          {tender.description && (
            <div className="mt-6">
              <p className="text-slate-500 text-sm mb-2">Description</p>
              <p className="text-sm text-slate-700 whitespace-pre-wrap">{tender.description}</p>
            </div>
          )}

          <div className="mt-4">
            <a
              href={tender.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 text-sm text-blue-600 hover:underline"
            >
              <ExternalLink className="h-4 w-4" /> View on Umucyo
            </a>
          </div>
        </CardContent>
      </Card>

      {/* AI Summary */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Brain className="h-5 w-5" /> AI Eligibility Summary
          </CardTitle>
          {!tender.ai_summary && (
            <Button onClick={handleEnrich} disabled={enriching} size="sm">
              {enriching ? "Enriching..." : "Enrich Now"}
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {tender.ai_summary ? (
            <div className="whitespace-pre-wrap text-sm text-slate-700 bg-slate-50 rounded-lg p-4">
              {tender.ai_summary}
            </div>
          ) : (
            <div className="text-center py-8">
              <p className="text-slate-400">No AI summary yet. Click &quot;Enrich Now&quot; to generate one.</p>
              {enrichError && <p className="text-red-500 text-sm mt-2">{enrichError}</p>}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
