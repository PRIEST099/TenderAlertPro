"use client";

import { useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import { fetcher } from "@/lib/api";
import { formatDate, formatCurrency } from "@/lib/format";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ChevronLeft, ChevronRight, Brain, Search, X, Clock, CheckCircle2, XCircle } from "lucide-react";

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

function isDeadlinePassed(deadline: string | null): boolean {
  if (!deadline) return false;
  return new Date(deadline) < new Date();
}

function deadlineBadge(deadline: string | null, status: string) {
  if (status !== "active") {
    return <Badge variant="outline" className="text-slate-400 border-slate-200">Closed</Badge>;
  }
  if (!deadline) {
    return <Badge variant="outline" className="text-slate-400">No deadline</Badge>;
  }
  if (isDeadlinePassed(deadline)) {
    return <Badge variant="outline" className="text-red-500 border-red-200 bg-red-50">Expired</Badge>;
  }
  const days = Math.ceil((new Date(deadline).getTime() - Date.now()) / (1000 * 60 * 60 * 24));
  if (days <= 3) {
    return <Badge className="bg-red-500 text-white">{days}d left</Badge>;
  }
  if (days <= 7) {
    return <Badge className="bg-amber-500 text-white">{days}d left</Badge>;
  }
  return <Badge className="bg-green-500 text-white">{days}d left</Badge>;
}

export default function TendersPage() {
  const [page, setPage] = useState(1);
  const [sectorFilter, setSectorFilter] = useState("");
  const [enrichmentFilter, setEnrichmentFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("open");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [valueMin, setValueMin] = useState("");
  const [valueMax, setValueMax] = useState("");

  const [perPage, setPerPage] = useState(20);

  const params = new URLSearchParams({ page: String(page), per_page: String(perPage) });
  if (sectorFilter) params.set("sector", sectorFilter);
  if (enrichmentFilter) params.set("enrichment", enrichmentFilter);
  if (statusFilter === "open") {
    params.set("deadline_from", new Date().toISOString());
  } else if (statusFilter === "expired") {
    params.set("deadline_to", new Date().toISOString());
  }
  if (searchQuery) params.set("search", searchQuery);
  if (valueMin) params.set("value_min", valueMin);
  if (valueMax) params.set("value_max", valueMax);

  const { data, error } = useSWR<PaginatedResponse>(
    `/api/tenders?${params}`,
    fetcher,
    { refreshInterval: 30000 }
  );

  function handleSearch() {
    setSearchQuery(searchInput.trim());
    setPage(1);
  }

  function clearSearch() {
    setSearchInput("");
    setSearchQuery("");
    setPage(1);
  }

  const activeCount = data?.items.filter(t => !isDeadlinePassed(t.deadline) && t.status === "active").length ?? 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900">Tenders</h1>
        {data && (
          <p className="text-sm text-slate-500">
            {data.total} total {statusFilter === "open" && `\u2022 ${activeCount} accepting applications`}
          </p>
        )}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        {/* Status filter tabs */}
        <div className="flex rounded-lg border overflow-hidden">
          {[
            { value: "open", label: "Open", icon: <CheckCircle2 className="h-3.5 w-3.5" /> },
            { value: "all", label: "All", icon: <Clock className="h-3.5 w-3.5" /> },
            { value: "expired", label: "Expired", icon: <XCircle className="h-3.5 w-3.5" /> },
          ].map((tab) => (
            <button
              key={tab.value}
              onClick={() => { setStatusFilter(tab.value); setPage(1); }}
              className={`flex items-center gap-1.5 px-3 py-2 text-sm font-medium transition-colors ${
                statusFilter === tab.value
                  ? "bg-slate-900 text-white"
                  : "bg-white text-slate-600 hover:bg-slate-50"
              }`}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </div>

        <select
          value={sectorFilter}
          onChange={(e) => { setSectorFilter(e.target.value); setPage(1); }}
          className="border rounded-lg px-3 py-2 text-sm bg-white"
        >
          <option value="">All sectors</option>
          <option value="ict">ICT</option>
          <option value="construction">Construction / Works</option>
          <option value="services">Services / Consulting</option>
          <option value="goods">Goods / Supply</option>
        </select>

        <select
          value={enrichmentFilter}
          onChange={(e) => { setEnrichmentFilter(e.target.value); setPage(1); }}
          className="border rounded-lg px-3 py-2 text-sm bg-white"
        >
          <option value="">AI: All</option>
          <option value="enriched">AI Enriched</option>
          <option value="pending">Pending Enrichment</option>
        </select>

        {/* Price range */}
        <div className="flex items-center gap-1">
          <Input
            type="number"
            placeholder="Min value (RWF)"
            value={valueMin}
            onChange={(e) => { setValueMin(e.target.value); setPage(1); }}
            className="w-[140px] text-sm"
          />
          <span className="text-slate-400">-</span>
          <Input
            type="number"
            placeholder="Max value (RWF)"
            value={valueMax}
            onChange={(e) => { setValueMax(e.target.value); setPage(1); }}
            className="w-[140px] text-sm"
          />
        </div>

        {/* Search */}
        <div className="flex gap-2 flex-1 min-w-[200px]">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
            <Input
              placeholder="Search by title, buyer, or OCID..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              className="pl-9"
            />
            {searchQuery && (
              <button onClick={clearSearch} className="absolute right-3 top-1/2 -translate-y-1/2">
                <X className="h-4 w-4 text-slate-400 hover:text-slate-600" />
              </button>
            )}
          </div>
          <Button onClick={handleSearch} size="sm" variant="outline">Search</Button>
        </div>
      </div>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          {error ? (
            <p className="text-red-500 p-6">Failed to load tenders</p>
          ) : !data ? (
            <p className="text-slate-400 p-6">Loading...</p>
          ) : data.items.length === 0 ? (
            <p className="text-slate-400 p-6 text-center">No tenders found matching your filters</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 border-b">
                  <tr>
                    <th className="px-4 py-3 text-left font-medium text-slate-500">Title</th>
                    <th className="px-4 py-3 text-left font-medium text-slate-500">Buyer</th>
                    <th className="px-4 py-3 text-left font-medium text-slate-500">Category</th>
                    <th className="px-4 py-3 text-left font-medium text-slate-500">Value</th>
                    <th className="px-4 py-3 text-left font-medium text-slate-500">Deadline</th>
                    <th className="px-4 py-3 text-left font-medium text-slate-500">Status</th>
                    <th className="px-4 py-3 text-left font-medium text-slate-500">AI</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {data.items.map((tender) => (
                    <tr key={tender.ocid} className={`hover:bg-slate-50 ${isDeadlinePassed(tender.deadline) ? "opacity-60" : ""}`}>
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
                      <td className="px-4 py-3">{deadlineBadge(tender.deadline, tender.status)}</td>
                      <td className="px-4 py-3">
                        {tender.has_ai_summary ? (
                          <Brain className="h-4 w-4 text-green-600" />
                        ) : (
                          <span className="text-xs text-slate-300">&mdash;</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {data && data.total > 0 && (
        <div className="flex items-center justify-between flex-wrap gap-4">
          <div className="flex items-center gap-4">
            <p className="text-sm text-slate-500">
              Showing {(page - 1) * perPage + 1}–{Math.min(page * perPage, data.total)} of {data.total} tenders
            </p>
            <select
              value={perPage}
              onChange={(e) => { setPerPage(Number(e.target.value)); setPage(1); }}
              className="border rounded-md px-2 py-1 text-sm bg-white"
            >
              <option value={10}>10 per page</option>
              <option value={20}>20 per page</option>
              <option value={50}>50 per page</option>
              <option value={100}>100 per page</option>
            </select>
          </div>

          {data.pages > 1 && (
            <div className="flex items-center gap-1">
              <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(1)}>
                First
              </Button>
              <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                <ChevronLeft className="h-4 w-4" />
              </Button>

              {/* Page numbers */}
              {Array.from({ length: data.pages }, (_, i) => i + 1)
                .filter(p => p === 1 || p === data.pages || Math.abs(p - page) <= 2)
                .reduce<(number | string)[]>((acc, p, i, arr) => {
                  if (i > 0 && typeof arr[i - 1] === "number" && (p as number) - (arr[i - 1] as number) > 1) {
                    acc.push("...");
                  }
                  acc.push(p);
                  return acc;
                }, [])
                .map((p, i) =>
                  typeof p === "string" ? (
                    <span key={`dots-${i}`} className="px-2 text-slate-400">...</span>
                  ) : (
                    <Button
                      key={p}
                      variant={p === page ? "default" : "outline"}
                      size="sm"
                      className="min-w-[36px]"
                      onClick={() => setPage(p as number)}
                    >
                      {p}
                    </Button>
                  )
                )}

              <Button variant="outline" size="sm" disabled={page >= data.pages} onClick={() => setPage(page + 1)}>
                <ChevronRight className="h-4 w-4" />
              </Button>
              <Button variant="outline" size="sm" disabled={page >= data.pages} onClick={() => setPage(data.pages)}>
                Last
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
