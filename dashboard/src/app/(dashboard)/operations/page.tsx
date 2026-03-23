"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetchApi, fetcher } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { RefreshCw, Send, Brain, Clock } from "lucide-react";

interface OperationStatus {
  last_poll_at: string | null;
  total_tenders: number;
  total_subscribers: number;
  scheduler_active: boolean;
  next_run: string | null;
}

interface OperationResult {
  success: boolean;
  message: string;
  count: number;
}

export default function OperationsPage() {
  const [pollResult, setPollResult] = useState<OperationResult | null>(null);
  const [sendResult, setSendResult] = useState<OperationResult | null>(null);
  const [enrichResult, setEnrichResult] = useState<OperationResult | null>(null);
  const [enrichLimit, setEnrichLimit] = useState(5);
  const [loading, setLoading] = useState<string | null>(null);

  const { data: status } = useSWR<OperationStatus>(
    "/api/operations/status",
    fetcher,
    { refreshInterval: 15000 }
  );

  async function runOperation(op: "poll" | "send" | "enrich") {
    setLoading(op);
    const setter = { poll: setPollResult, send: setSendResult, enrich: setEnrichResult }[op];
    try {
      const url = op === "enrich" ? `/api/operations/${op}?limit=${enrichLimit}` : `/api/operations/${op}`;
      const result = await fetchApi<OperationResult>(url, { method: "POST" });
      setter(result);
    } catch (err: unknown) {
      setter({ success: false, message: err instanceof Error ? err.message : "Failed", count: 0 });
    } finally {
      setLoading(null);
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-slate-900">Operations</h1>

      {/* Status Card */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Clock className="h-5 w-5" /> System Status
          </CardTitle>
        </CardHeader>
        <CardContent>
          {status ? (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
              <div>
                <p className="text-slate-500">Last Poll</p>
                <p className="font-medium">{formatDate(status.last_poll_at)}</p>
              </div>
              <div>
                <p className="text-slate-500">Total Tenders</p>
                <p className="font-medium">{status.total_tenders}</p>
              </div>
              <div>
                <p className="text-slate-500">Total Subscribers</p>
                <p className="font-medium">{status.total_subscribers}</p>
              </div>
              <div>
                <p className="text-slate-500">Next Run</p>
                <p className="font-medium">{status.next_run || "—"}</p>
              </div>
            </div>
          ) : (
            <p className="text-slate-400">Loading...</p>
          )}
        </CardContent>
      </Card>

      {/* Manual Operations */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Poll */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <RefreshCw className="h-4 w-4" /> Poll Tenders
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-slate-500">Fetch fresh tenders from the RPPA Umucyo API right now.</p>
            <Button onClick={() => runOperation("poll")} disabled={loading === "poll"} className="w-full">
              {loading === "poll" ? "Polling..." : "Poll Now"}
            </Button>
            {pollResult && (
              <p className={`text-sm ${pollResult.success ? "text-green-600" : "text-red-500"}`}>
                {pollResult.message}
              </p>
            )}
          </CardContent>
        </Card>

        {/* Enrich */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Brain className="h-4 w-4" /> AI Enrichment
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-slate-500">Run Claude AI eligibility analysis on unenriched tenders.</p>
            <div className="flex items-center gap-2">
              <label className="text-sm text-slate-600 whitespace-nowrap">Batch size:</label>
              <select
                value={enrichLimit}
                onChange={(e) => setEnrichLimit(Number(e.target.value))}
                className="border rounded-md px-2 py-1 text-sm flex-1"
              >
                {[1, 3, 5, 10, 20, 50].map((n) => (
                  <option key={n} value={n}>{n} tender{n > 1 ? "s" : ""}</option>
                ))}
              </select>
            </div>
            <Button onClick={() => runOperation("enrich")} disabled={loading === "enrich"} className="w-full">
              {loading === "enrich" ? "Enriching..." : `Enrich ${enrichLimit} Now`}
            </Button>
            {enrichResult && (
              <p className={`text-sm ${enrichResult.success ? "text-green-600" : "text-red-500"}`}>
                {enrichResult.message}
              </p>
            )}
          </CardContent>
        </Card>

        {/* Send */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Send className="h-4 w-4" /> Send Digest
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-slate-500">Send today&apos;s tender digest to all active subscribers via WhatsApp.</p>
            <Button onClick={() => runOperation("send")} disabled={loading === "send"} variant="destructive" className="w-full">
              {loading === "send" ? "Sending..." : "Send Digest Now"}
            </Button>
            {sendResult && (
              <p className={`text-sm ${sendResult.success ? "text-green-600" : "text-red-500"}`}>
                {sendResult.message}
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
