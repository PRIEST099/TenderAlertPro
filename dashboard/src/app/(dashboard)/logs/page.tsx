"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetchApi, fetcher } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ChevronLeft, ChevronRight, Shield, AlertTriangle, Brain } from "lucide-react";

interface InteractionLog {
  id: number;
  phone: string;
  direction: string;
  msg_type: string;
  content: string;
  command: string;
  timestamp: string;
}

interface UserActivity {
  phone: string;
  company_name: string;
  inbound_count: number;
  outbound_count: number;
  total: number;
  first_seen: string | null;
  last_seen: string | null;
  active: boolean;
  risk_level: string;
}

interface ActivityResponse {
  period: string;
  users: UserActivity[];
  total_users: number;
  total_interactions: number;
  suspicious_count: number;
  warning_count: number;
}

interface FraudReport {
  period: string;
  total_users: number;
  total_interactions: number;
  suspicious_users: UserActivity[];
  warnings: string[];
  ai_analysis: string | null;
}

export default function LogsPage() {
  const [page, setPage] = useState(1);
  const [phoneFilter, setPhoneFilter] = useState("");
  const [period, setPeriod] = useState<"today" | "week" | "month">("today");
  const [analyzing, setAnalyzing] = useState(false);
  const [fraudReport, setFraudReport] = useState<FraudReport | null>(null);

  // Interaction logs
  const logParams = new URLSearchParams({ page: String(page), per_page: "20" });
  if (phoneFilter) logParams.set("phone", phoneFilter);

  const { data: logsData } = useSWR(
    `/api/logs?${logParams}`,
    fetcher,
    { refreshInterval: 10000 }
  );

  // Activity stats
  const { data: activityData } = useSWR<ActivityResponse>(
    `/api/logs/activity?period=${period}`,
    fetcher,
    { refreshInterval: 15000 }
  );

  async function runAnalysis() {
    setAnalyzing(true);
    try {
      const report = await fetchApi<FraudReport>(`/api/logs/analyze?period=${period}`, { method: "POST" });
      setFraudReport(report);
    } catch (err: unknown) {
      setFraudReport({
        period, total_users: 0, total_interactions: 0,
        suspicious_users: [], warnings: [],
        ai_analysis: `Analysis failed: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    } finally {
      setAnalyzing(false);
    }
  }

  const logs = (logsData as { items: InteractionLog[]; total: number; pages: number } | undefined);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900">Interaction Logs & Fraud Detection</h1>
        <div className="flex gap-2">
          <select
            value={period}
            onChange={(e) => { setPeriod(e.target.value as "today" | "week" | "month"); setFraudReport(null); }}
            className="border rounded-md px-3 py-2 text-sm"
          >
            <option value="today">Today</option>
            <option value="week">This Week</option>
            <option value="month">This Month</option>
          </select>
          <Button onClick={runAnalysis} disabled={analyzing}>
            <Brain className="h-4 w-4 mr-2" />
            {analyzing ? "Analyzing..." : "AI Fraud Analysis"}
          </Button>
        </div>
      </div>

      {/* Activity Overview */}
      {activityData && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <Card>
            <CardContent className="pt-6">
              <div className="text-2xl font-bold">{activityData.total_users}</div>
              <p className="text-xs text-slate-500">Active Users ({period})</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6">
              <div className="text-2xl font-bold">{activityData.total_interactions}</div>
              <p className="text-xs text-slate-500">Total Interactions</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6">
              <div className="text-2xl font-bold text-yellow-600">{activityData.warning_count}</div>
              <p className="text-xs text-slate-500">Warnings</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6">
              <div className="text-2xl font-bold text-red-600">{activityData.suspicious_count}</div>
              <p className="text-xs text-slate-500">Suspicious</p>
            </CardContent>
          </Card>
        </div>
      )}

      {/* User Activity Table */}
      {activityData && activityData.users.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Shield className="h-5 w-5" /> User Activity ({period})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b">
                <tr>
                  <th className="px-4 py-3 text-left font-medium text-slate-500">Phone</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-500">Company</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-500">Inbound</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-500">Outbound</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-500">Total</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-500">Last Seen</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-500">Risk</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {activityData.users.map((user) => (
                  <tr
                    key={user.phone}
                    className={`hover:bg-slate-50 cursor-pointer ${user.risk_level === "suspicious" ? "bg-red-50" : user.risk_level === "warning" ? "bg-yellow-50" : ""}`}
                    onClick={() => { setPhoneFilter(user.phone); setPage(1); }}
                  >
                    <td className="px-4 py-3 font-mono text-xs">{user.phone}</td>
                    <td className="px-4 py-3">{user.company_name}</td>
                    <td className="px-4 py-3">{user.inbound_count}</td>
                    <td className="px-4 py-3">{user.outbound_count}</td>
                    <td className="px-4 py-3 font-semibold">{user.total}</td>
                    <td className="px-4 py-3 text-slate-500">{formatDate(user.last_seen)}</td>
                    <td className="px-4 py-3">
                      <Badge variant={user.risk_level === "suspicious" ? "destructive" : user.risk_level === "warning" ? "secondary" : "outline"}>
                        {user.risk_level === "suspicious" && <AlertTriangle className="h-3 w-3 mr-1" />}
                        {user.risk_level}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {/* AI Fraud Report */}
      {fraudReport && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Brain className="h-5 w-5" /> AI Fraud Analysis — {fraudReport.period}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-3 gap-4 mb-4 text-sm">
              <div><span className="text-slate-500">Users analyzed:</span> <strong>{fraudReport.total_users}</strong></div>
              <div><span className="text-slate-500">Interactions:</span> <strong>{fraudReport.total_interactions}</strong></div>
              <div><span className="text-slate-500">Flagged:</span> <strong className="text-red-600">{fraudReport.suspicious_users.length}</strong></div>
            </div>
            {fraudReport.ai_analysis && (
              <div className="bg-slate-50 rounded-lg p-4 whitespace-pre-wrap text-sm text-slate-700">
                {fraudReport.ai_analysis}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Interaction Logs */}
      <Card>
        <CardHeader>
          <CardTitle>Interaction Logs</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-4 mb-4">
            <Input
              placeholder="Filter by phone number..."
              value={phoneFilter}
              onChange={(e) => { setPhoneFilter(e.target.value); setPage(1); }}
              className="max-w-xs"
            />
            {phoneFilter && (
              <Button variant="outline" size="sm" onClick={() => { setPhoneFilter(""); setPage(1); }}>
                Clear filter
              </Button>
            )}
          </div>

          {!logs ? (
            <p className="text-slate-400 py-4">Loading...</p>
          ) : logs.items.length === 0 ? (
            <p className="text-slate-400 py-4 text-center">No interactions logged yet</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 border-b">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium text-slate-500">Time</th>
                    <th className="px-3 py-2 text-left font-medium text-slate-500">Phone</th>
                    <th className="px-3 py-2 text-left font-medium text-slate-500">Dir</th>
                    <th className="px-3 py-2 text-left font-medium text-slate-500">Type</th>
                    <th className="px-3 py-2 text-left font-medium text-slate-500">Command</th>
                    <th className="px-3 py-2 text-left font-medium text-slate-500">Content</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {logs.items.map((log: InteractionLog) => (
                    <tr key={log.id} className="hover:bg-slate-50">
                      <td className="px-3 py-2 text-xs text-slate-500 whitespace-nowrap">
                        {log.timestamp.replace("T", " ").slice(0, 19)}
                      </td>
                      <td className="px-3 py-2 font-mono text-xs">
                        <button
                          className="text-blue-600 hover:underline"
                          onClick={() => { setPhoneFilter(log.phone); setPage(1); }}
                        >
                          {log.phone}
                        </button>
                      </td>
                      <td className="px-3 py-2">
                        <Badge variant={log.direction === "inbound" ? "default" : "outline"}>
                          {log.direction === "inbound" ? "→ IN" : "← OUT"}
                        </Badge>
                      </td>
                      <td className="px-3 py-2 text-xs">{log.msg_type}</td>
                      <td className="px-3 py-2">
                        {log.command && <Badge variant="secondary">{log.command}</Badge>}
                      </td>
                      <td className="px-3 py-2 text-xs text-slate-600 max-w-xs truncate">{log.content}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {logs && logs.pages > 1 && (
            <div className="flex items-center justify-between mt-4">
              <p className="text-sm text-slate-500">Page {page} of {logs.pages}</p>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <Button variant="outline" size="sm" disabled={page >= logs.pages} onClick={() => setPage(page + 1)}>
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
