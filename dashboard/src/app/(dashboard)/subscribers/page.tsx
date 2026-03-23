"use client";

import { useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import { fetchApi, fetcher } from "@/lib/api";
import { formatDate, statusColor } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Download, ChevronLeft, ChevronRight, UserPlus } from "lucide-react";

interface Subscriber {
  id: number;
  phone_masked: string;
  company_name: string;
  sectors: string;
  onboarding_step: string;
  active: boolean;
  created_at: string | null;
}

interface PaginatedResponse {
  items: Subscriber[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export default function SubscribersPage() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [sectorFilter, setSectorFilter] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [newPhone, setNewPhone] = useState("");
  const [newCompany, setNewCompany] = useState("");
  const [newSector, setNewSector] = useState("all");
  const [addError, setAddError] = useState("");
  const [adding, setAdding] = useState(false);

  const params = new URLSearchParams({ page: String(page), per_page: "15" });
  if (search) params.set("search", search);
  if (sectorFilter) params.set("sector", sectorFilter);

  const { data, error } = useSWR<PaginatedResponse>(
    `/api/subscribers?${params}`,
    fetcher,
    { refreshInterval: 10000 }
  );

  async function handleExport() {
    const token = localStorage.getItem("token");
    const res = await fetch(
      `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/subscribers/export`,
      { headers: { Authorization: `Bearer ${token}` } }
    );
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "subscribers.csv";
    a.click();
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900">Subscribers</h1>
        <div className="flex gap-2">
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger>
              <Button size="sm">
                <UserPlus className="h-4 w-4 mr-2" /> Add Subscriber
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Add Subscriber</DialogTitle>
              </DialogHeader>
              <form
                onSubmit={async (e) => {
                  e.preventDefault();
                  setAdding(true);
                  setAddError("");
                  try {
                    await fetchApi("/api/subscribers", {
                      method: "POST",
                      body: JSON.stringify({ phone: newPhone, company_name: newCompany, sectors: newSector }),
                    });
                    setDialogOpen(false);
                    setNewPhone("");
                    setNewCompany("");
                    setNewSector("all");
                  } catch (err: unknown) {
                    setAddError(err instanceof Error ? err.message : "Failed to add");
                  } finally {
                    setAdding(false);
                  }
                }}
                className="space-y-4"
              >
                <div>
                  <label className="text-sm text-slate-600">Phone (international, no +)</label>
                  <Input placeholder="250788123456" value={newPhone} onChange={(e) => setNewPhone(e.target.value)} required />
                </div>
                <div>
                  <label className="text-sm text-slate-600">Company Name</label>
                  <Input placeholder="Kigali Tech Solutions" value={newCompany} onChange={(e) => setNewCompany(e.target.value)} />
                </div>
                <div>
                  <label className="text-sm text-slate-600">Sector</label>
                  <select value={newSector} onChange={(e) => setNewSector(e.target.value)} className="w-full border rounded-md px-3 py-2 text-sm">
                    <option value="all">All Sectors</option>
                    <option value="ict">ICT</option>
                    <option value="construction">Construction</option>
                    <option value="health">Health</option>
                    <option value="education">Education</option>
                    <option value="consulting">Consulting</option>
                    <option value="supply">Supply</option>
                  </select>
                </div>
                {addError && <p className="text-sm text-red-500">{addError}</p>}
                <Button type="submit" className="w-full" disabled={adding}>
                  {adding ? "Adding..." : "Add Subscriber"}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
          <Button variant="outline" size="sm" onClick={handleExport}>
            <Download className="h-4 w-4 mr-2" /> Export CSV
          </Button>
        </div>
      </div>

      <div className="flex gap-4">
        <Input
          placeholder="Search by company or phone..."
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          className="max-w-xs"
        />
        <select
          value={sectorFilter}
          onChange={(e) => { setSectorFilter(e.target.value); setPage(1); }}
          className="border rounded-md px-3 py-2 text-sm"
        >
          <option value="">All sectors</option>
          <option value="ict">ICT</option>
          <option value="construction">Construction</option>
          <option value="health">Health</option>
          <option value="education">Education</option>
          <option value="consulting">Consulting</option>
          <option value="supply">Supply</option>
        </select>
      </div>

      <Card>
        <CardContent className="p-0">
          {error ? (
            <p className="text-red-500 p-6">Failed to load subscribers</p>
          ) : !data ? (
            <p className="text-slate-400 p-6">Loading...</p>
          ) : data.items.length === 0 ? (
            <p className="text-slate-400 p-6 text-center">No subscribers found</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b">
                <tr>
                  <th className="px-6 py-3 text-left font-medium text-slate-500">Company</th>
                  <th className="px-6 py-3 text-left font-medium text-slate-500">Phone</th>
                  <th className="px-6 py-3 text-left font-medium text-slate-500">Sector</th>
                  <th className="px-6 py-3 text-left font-medium text-slate-500">Status</th>
                  <th className="px-6 py-3 text-left font-medium text-slate-500">Joined</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {data.items.map((sub) => (
                  <tr key={sub.id} className="hover:bg-slate-50 cursor-pointer">
                    <td className="px-6 py-4">
                      <Link href={`/subscribers/${sub.phone_masked}`} className="font-medium text-blue-600 hover:underline">
                        {sub.company_name || "—"}
                      </Link>
                    </td>
                    <td className="px-6 py-4 text-slate-500">{sub.phone_masked}</td>
                    <td className="px-6 py-4">
                      <Badge variant="outline">{sub.sectors}</Badge>
                    </td>
                    <td className="px-6 py-4">
                      <span className={`px-2 py-1 rounded-full text-xs font-medium ${statusColor(sub.active ? sub.onboarding_step : "inactive")}`}>
                        {sub.active ? sub.onboarding_step : "inactive"}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-slate-500">{formatDate(sub.created_at)}</td>
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
            Showing {(data.page - 1) * data.per_page + 1}–{Math.min(data.page * data.per_page, data.total)} of {data.total}
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
