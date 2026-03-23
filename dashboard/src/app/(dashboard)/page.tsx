"use client";

import useSWR from "swr";
import { fetchApi, fetcher } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Users, FileText, Brain, Clock } from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from "recharts";

interface Stats {
  total_subscribers: number;
  active_subscribers: number;
  inactive_subscribers: number;
  total_tenders: number;
  active_tenders: number;
  enriched_tenders: number;
  enrichment_rate: number;
  onboarding_funnel: { awaiting_name: number; awaiting_sector: number; complete: number };
  last_poll_at: string | null;
}

const FUNNEL_COLORS = ["#f59e0b", "#3b82f6", "#22c55e"];

export default function OverviewPage() {
  const { data: stats, error } = useSWR<Stats>("/api/stats", fetcher, {
    refreshInterval: 30000,
  });

  if (error) return <p className="text-red-500">Failed to load stats</p>;
  if (!stats) return <p className="text-slate-400">Loading...</p>;

  const funnelData = [
    { name: "Awaiting Name", value: stats.onboarding_funnel.awaiting_name },
    { name: "Awaiting Sector", value: stats.onboarding_funnel.awaiting_sector },
    { name: "Complete", value: stats.onboarding_funnel.complete },
  ];

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Dashboard Overview</h1>
        <p className="text-slate-500 text-sm mt-1">Last poll: {formatDate(stats.last_poll_at)}</p>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-slate-500">Total Subscribers</CardTitle>
            <Users className="h-4 w-4 text-slate-400" />
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{stats.active_subscribers}</div>
            <p className="text-xs text-slate-500 mt-1">{stats.inactive_subscribers} inactive</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-slate-500">Active Tenders</CardTitle>
            <FileText className="h-4 w-4 text-slate-400" />
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{stats.active_tenders}</div>
            <p className="text-xs text-slate-500 mt-1">{stats.total_tenders} total fetched</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-slate-500">AI Enrichment</CardTitle>
            <Brain className="h-4 w-4 text-slate-400" />
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{stats.enrichment_rate}%</div>
            <p className="text-xs text-slate-500 mt-1">{stats.enriched_tenders} enriched</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-slate-500">Schedule</CardTitle>
            <Clock className="h-4 w-4 text-slate-400" />
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold">08:00 CAT</div>
            <p className="text-xs text-slate-500 mt-1">Daily Kigali time</p>
          </CardContent>
        </Card>
      </div>

      {/* Onboarding Funnel */}
      <Card>
        <CardHeader>
          <CardTitle>Onboarding Funnel</CardTitle>
        </CardHeader>
        <CardContent>
          {stats.total_subscribers === 0 ? (
            <p className="text-slate-400 text-sm py-8 text-center">No subscribers yet. Share your WhatsApp bot number to start!</p>
          ) : (
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={funnelData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  {funnelData.map((_, i) => (
                    <Cell key={i} fill={FUNNEL_COLORS[i]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
