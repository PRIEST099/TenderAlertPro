"use client";

import { useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import { fetchApi, fetcher } from "@/lib/api";
import { formatDate, formatCurrency } from "@/lib/format";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ChevronLeft, ChevronRight, Brain } from "lucide-react";

interface Tender {
  ocid: string;
  title: string;
  buyer_name: string;
  category: string;
  value_amount: number | null;
  value_currency: string;
  deadline: string | null;
  status: string;
  has_ai_summary: boolean;
  fetched_at: string | null;
}

interface PaginatedResponse {
  items: Tender[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export default function TendersPage() {
  const [page, setPage] = useState(1);
  const [sectorFilter, setSectorFilter] = useState("");
  const [enrichmentFilter, setEnrichmentFilter] = useState("");

  const params = new URLSearchParams({ page: String(page), per_page: "15" });
  if (sectorFilter) params.set("sector", sectorFilter);
  if (enrichmentFilter) params.set("enrichment", enrichmentFilter);

  const { data, error } = useSWR<PaginatedResponse>(
    `/api/tenders?${params}`,
    fetcher,
    { refreshInterval: 30000 }
  );

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-slate-900">Tenders</h1>

      <div className="flex gap-4">
        <select
          value={sectorFilter}
          onChange={(e) => { setSectorFilter(e.target.value); setPage(1); }}
          className="border rounded-md px-3 py-2 text-sm"
        >
          <option value="">All sectors</option>
          <option value="ict">ICT</option>
          <option value="construction">Construction</option>
          <option value="services">Services</option>
          <option value="goods">Goods</option>
        </select>
        <select
          value={enrichmentFilter}
          onChange={(e) => { setEnrichmentFilter(e.target.value); setPage(1); }}
          className="border rounded-md px-3 py-2 text-sm"
        >
          <option value="">All</option>
          <option value="enriched">AI Enriched</option>
          <option value="pending">Pending Enrichment</option>
        </select>
      </div>

      <Card>
        <CardContent className="p-0">
          {error ? (
            <p className="text-red-500 p-6">Failed to load tenders</p>
          ) : !data ? (
            <p className="text-slate-400 p-6">Loading...</p>
          ) : data.items.length === 0 ? (
            <p className="text-slate-400 p-6 text-center">No tenders found</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b">
                <tr>
                  <th className="px-4 py-3 text-left font-medium text-slate-500">Title</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-500">Buyer</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-500">Category</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-500">Value</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-500">Deadline</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-500">AI</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {data.items.map((tender) => (
                  <tr key={tender.ocid} className="hover:bg-slate-50">
                    <td className="px-4 py-3 max-w-xs">
                      <Link
                        href={`/tenders/${encodeURIComponent(tender.ocid)}`}
                        className="font-medium text-blue-600 hover:underline line-clamp-2"
                      >
                        {tender.title}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-slate-500 max-w-[200px] truncate">{tender.buyer_name}</td>
                    <td className="px-4 py-3">
                      <Badge variant="outline">{tender.category}</Badge>
                    </td>
                    <td className="px-4 py-3 text-slate-700 whitespace-nowrap">
                      {formatCurrency(tender.value_amount, tender.value_currency)}
                    </td>
                    <td className="px-4 py-3 text-slate-500 whitespace-nowrap">{formatDate(tender.deadline)}</td>
                    <td className="px-4 py-3">
                      {tender.has_ai_summary ? (
                        <Brain className="h-4 w-4 text-green-600" />
                      ) : (
                        <span className="text-xs text-slate-300">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {data && data.pages > 1 && (
        <div className="flex items-center justify-between">
          <p className="text-sm text-slate-500">
            Page {data.page} of {data.pages} ({data.total} tenders)
          </p>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <Button variant="outline" size="sm" disabled={page >= data.pages} onClick={() => setPage(page + 1)}>
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
