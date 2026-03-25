"use client";

import { useState, use } from "react";
import useSWR from "swr";
import { fetchApi, fetcher } from "@/lib/api";
import { formatDate, statusColor } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ArrowLeft, Send, MessageSquare, ChevronLeft, ChevronRight, Shield, ShieldOff, Crown, Zap } from "lucide-react";
import Link from "next/link";

interface SubscriberDetail {
  id: number;
  phone: string;
  company_name: string;
  sectors: string;
  onboarding_step: string;
  active: boolean;
  subscription_tier: string;
  rate_limit_exempt: boolean;
  credits: number;
  deep_analyses_used: number;
  created_at: string | null;
}

interface InteractionLog {
  id: number;
  phone: string;
  direction: string;
  msg_type: string;
  content: string;
  command: string;
  timestamp: string;
}

interface LogsResponse {
  subscriber: Record<string, unknown>;
  logs: InteractionLog[];
  total: number;
}

export default function SubscriberDetailPage({ params }: { params: Promise<{ phone: string }> }) {
  const { phone } = use(params);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [sendResult, setSendResult] = useState<string | null>(null);
  const [logPage, setLogPage] = useState(1);
  const [toggling, setToggling] = useState(false);
  const [upgrading, setUpgrading] = useState(false);
  const logsPerPage = 20;

  const { data: sub, error, mutate: mutateSub } = useSWR<SubscriberDetail>(
    `/api/subscribers/${phone}`,
    fetcher
  );

  const { data: logsData } = useSWR<LogsResponse>(
    `/api/logs/subscriber/${phone}?limit=${logsPerPage}&offset=${(logPage - 1) * logsPerPage}`,
    fetcher,
    { refreshInterval: 10000 }
  );

  async function handleSend() {
    if (!message.trim()) return;
    setSending(true);
    setSendResult(null);
    try {
      await fetchApi(`/api/subscribers/${phone}/message`, {
        method: "POST",
        body: JSON.stringify({ message }),
      });
      setSendResult("Message sent!");
      setMessage("");
    } catch (err: unknown) {
      setSendResult(`Failed: ${err instanceof Error ? err.message : "Unknown error"}`);
    } finally {
      setSending(false);
    }
  }

  async function handleToggleRateLimit() {
    setToggling(true);
    try {
      await fetchApi(`/api/subscribers/${phone}/toggle-rate-limit`, { method: "POST" });
      mutateSub();
    } catch { /* ignore */ }
    finally { setToggling(false); }
  }

  async function handleUpgradeTier(tier: string) {
    setUpgrading(true);
    try {
      await fetchApi(`/api/subscribers/${phone}/upgrade`, {
        method: "POST",
        body: JSON.stringify({ tier }),
      });
      mutateSub();
    } catch { /* ignore */ }
    finally { setUpgrading(false); }
  }

  if (error) return <p className="text-red-500">Subscriber not found</p>;
  if (!sub) return <p className="text-slate-400">Loading...</p>;

  const totalLogPages = logsData ? Math.ceil(logsData.total / logsPerPage) : 0;

  return (
    <div className="space-y-6 max-w-4xl">
      <Link href="/subscribers" className="flex items-center gap-2 text-sm text-slate-500 hover:text-slate-900">
        <ArrowLeft className="h-4 w-4" /> Back to subscribers
      </Link>

      <h1 className="text-2xl font-bold text-slate-900">{sub.company_name || "Unnamed subscriber"}</h1>

      <Card>
        <CardHeader>
          <CardTitle>Subscriber Details</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
            <div>
              <p className="text-slate-500">Phone</p>
              <p className="font-mono">{sub.phone}</p>
            </div>
            <div>
              <p className="text-slate-500">Company</p>
              <p>{sub.company_name || "\u2014"}</p>
            </div>
            <div>
              <p className="text-slate-500">Sector</p>
              <Badge variant="outline">{sub.sectors}</Badge>
            </div>
            <div>
              <p className="text-slate-500">Status</p>
              <span className={`px-2 py-1 rounded-full text-xs font-medium ${statusColor(sub.active ? sub.onboarding_step : "inactive")}`}>
                {sub.active ? sub.onboarding_step : "inactive"}
              </span>
            </div>
            <div>
              <p className="text-slate-500">Subscription</p>
              <Badge variant={sub.subscription_tier === "pro" ? "default" : "outline"} className={sub.subscription_tier === "pro" ? "bg-amber-500" : ""}>
                <Crown className="h-3 w-3 mr-1" />
                {sub.subscription_tier.toUpperCase()}
              </Badge>
            </div>
            <div>
              <p className="text-slate-500">Credits</p>
              <p className="font-semibold">{sub.credits}</p>
            </div>
            <div>
              <p className="text-slate-500">Deep Analyses Used</p>
              <p className="font-semibold">{sub.deep_analyses_used}</p>
            </div>
            <div>
              <p className="text-slate-500">Joined</p>
              <p>{formatDate(sub.created_at)}</p>
            </div>
            <div>
              <p className="text-slate-500">Total Interactions</p>
              <p className="font-semibold">{logsData?.total ?? "..."}</p>
            </div>
          </div>

          {/* Admin Controls */}
          <div className="border-t pt-4 flex flex-wrap gap-3">
            <Button
              variant={sub.rate_limit_exempt ? "destructive" : "outline"}
              size="sm"
              onClick={handleToggleRateLimit}
              disabled={toggling}
            >
              {sub.rate_limit_exempt ? <ShieldOff className="h-4 w-4 mr-2" /> : <Shield className="h-4 w-4 mr-2" />}
              {toggling ? "Updating..." : sub.rate_limit_exempt ? "Re-enable Rate Limit" : "Lift Rate Limit"}
            </Button>

            {/* Tier upgrade/downgrade buttons */}
            {(["free", "regular", "pro", "business"] as const).filter(t => t !== sub.subscription_tier).map(tier => {
              const tierConfig: Record<string, { label: string; icon: string; className: string }> = {
                free: { label: "Downgrade to Free", icon: "", className: "" },
                regular: { label: "Set to Regular", icon: "🟢", className: "border-green-400 text-green-700 hover:bg-green-50" },
                pro: { label: "Set to Pro", icon: "👑", className: "border-amber-400 text-amber-700 hover:bg-amber-50" },
                business: { label: "Set to Business", icon: "💎", className: "border-blue-400 text-blue-700 hover:bg-blue-50" },
              };
              const cfg = tierConfig[tier];
              return (
                <Button
                  key={tier}
                  variant="outline"
                  size="sm"
                  onClick={() => handleUpgradeTier(tier)}
                  disabled={upgrading}
                  className={cfg.className}
                >
                  {cfg.icon && <span className="mr-1">{cfg.icon}</span>}
                  {upgrading ? "Updating..." : cfg.label}
                </Button>
              );
            })}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Send Manual Message</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-3">
            <Input
              placeholder="Type a WhatsApp message..."
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSend()}
            />
            <Button onClick={handleSend} disabled={sending || !message.trim()}>
              <Send className="h-4 w-4 mr-2" />
              {sending ? "Sending..." : "Send"}
            </Button>
          </div>
          {sendResult && (
            <p className={`text-sm mt-2 ${sendResult.startsWith("Failed") ? "text-red-500" : "text-green-600"}`}>
              {sendResult}
            </p>
          )}
        </CardContent>
      </Card>

      {/* Interaction History */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <MessageSquare className="h-5 w-5" />
            Interaction History
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!logsData ? (
            <p className="text-slate-400 py-4">Loading interactions...</p>
          ) : logsData.logs.length === 0 ? (
            <p className="text-slate-400 py-4 text-center">No interactions recorded yet</p>
          ) : (
            <>
              <div className="space-y-2">
                {logsData.logs.map((log) => (
                  <div
                    key={log.id}
                    className={`flex gap-3 p-3 rounded-lg text-sm ${
                      log.direction === "inbound"
                        ? "bg-blue-50 border border-blue-100"
                        : "bg-slate-50 border border-slate-100"
                    }`}
                  >
                    <div className="flex-shrink-0 pt-0.5">
                      <Badge variant={log.direction === "inbound" ? "default" : "outline"} className="text-xs">
                        {log.direction === "inbound" ? "IN" : "OUT"}
                      </Badge>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        {log.command && (
                          <Badge variant="secondary" className="text-xs">{log.command}</Badge>
                        )}
                        <span className="text-xs text-slate-400">{log.msg_type}</span>
                      </div>
                      <p className="text-slate-700 break-words">{log.content || "(no content)"}</p>
                    </div>
                    <div className="flex-shrink-0 text-xs text-slate-400 whitespace-nowrap">
                      {log.timestamp.replace("T", " ").slice(0, 19)}
                    </div>
                  </div>
                ))}
              </div>

              {totalLogPages > 1 && (
                <div className="flex items-center justify-between mt-4">
                  <p className="text-sm text-slate-500">
                    Page {logPage} of {totalLogPages} ({logsData.total} interactions)
                  </p>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" disabled={logPage <= 1} onClick={() => setLogPage(logPage - 1)}>
                      <ChevronLeft className="h-4 w-4" />
                    </Button>
                    <Button variant="outline" size="sm" disabled={logPage >= totalLogPages} onClick={() => setLogPage(logPage + 1)}>
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
