"use client";

import { useState, use } from "react";
import useSWR from "swr";
import { fetchApi, fetcher } from "@/lib/api";
import { formatDate, statusColor } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ArrowLeft, Send } from "lucide-react";
import Link from "next/link";

interface SubscriberDetail {
  id: number;
  phone: string;
  company_name: string;
  sectors: string;
  onboarding_step: string;
  active: boolean;
  created_at: string | null;
}

export default function SubscriberDetailPage({ params }: { params: Promise<{ phone: string }> }) {
  const { phone } = use(params);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [sendResult, setSendResult] = useState<string | null>(null);

  const { data: sub, error } = useSWR<SubscriberDetail>(
    `/api/subscribers/${phone}`,
    fetcher
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

  if (error) return <p className="text-red-500">Subscriber not found</p>;
  if (!sub) return <p className="text-slate-400">Loading...</p>;

  return (
    <div className="space-y-6 max-w-2xl">
      <Link href="/subscribers" className="flex items-center gap-2 text-sm text-slate-500 hover:text-slate-900">
        <ArrowLeft className="h-4 w-4" /> Back to subscribers
      </Link>

      <h1 className="text-2xl font-bold text-slate-900">{sub.company_name || "Unnamed subscriber"}</h1>

      <Card>
        <CardHeader>
          <CardTitle>Subscriber Details</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <p className="text-slate-500">Phone</p>
              <p className="font-mono">{sub.phone}</p>
            </div>
            <div>
              <p className="text-slate-500">Company</p>
              <p>{sub.company_name || "—"}</p>
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
              <p className="text-slate-500">Joined</p>
              <p>{formatDate(sub.created_at)}</p>
            </div>
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
    </div>
  );
}
