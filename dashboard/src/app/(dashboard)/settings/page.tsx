"use client";

import useSWR from "swr";
import { fetchApi, fetcher } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Shield, Phone, Brain, Database } from "lucide-react";

interface Settings {
  whatsapp_token_valid: boolean;
  whatsapp_sender_status: Record<string, unknown>;
  anthropic_key_set: boolean;
  webhook_verify_token: string;
  admin_number: string;
  database_path: string;
  cors_origins: string[];
}

export default function SettingsPage() {
  const { data: settings, error } = useSWR<Settings>(
    "/api/settings",
    fetcher
  );

  if (error) return <p className="text-red-500">Failed to load settings</p>;
  if (!settings) return <p className="text-slate-400">Loading...</p>;

  const senderStatus = settings.whatsapp_sender_status as Record<string, string>;

  return (
    <div className="space-y-6 max-w-3xl">
      <h1 className="text-2xl font-bold text-slate-900">Settings</h1>

      {/* WhatsApp */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Phone className="h-5 w-5" /> WhatsApp Configuration
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-sm text-slate-500">Token Status</span>
            <Badge variant={settings.whatsapp_token_valid ? "default" : "destructive"}>
              {settings.whatsapp_token_valid ? "Valid" : "Invalid"}
            </Badge>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-slate-500">Sender Number</span>
            <span className="text-sm font-mono">{senderStatus.display_phone_number || "—"}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-slate-500">Verified Name</span>
            <span className="text-sm">{senderStatus.verified_name || "—"}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-slate-500">Verification Status</span>
            <Badge variant={senderStatus.code_verification_status === "VERIFIED" ? "default" : "secondary"}>
              {(senderStatus.code_verification_status as string) || "—"}
            </Badge>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-slate-500">Admin Number</span>
            <span className="text-sm font-mono">{settings.admin_number}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-slate-500">Webhook Verify Token</span>
            <span className="text-sm font-mono">{settings.webhook_verify_token}</span>
          </div>
        </CardContent>
      </Card>

      {/* AI */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Brain className="h-5 w-5" /> Anthropic (Claude AI)
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between">
            <span className="text-sm text-slate-500">API Key</span>
            <Badge variant={settings.anthropic_key_set ? "default" : "destructive"}>
              {settings.anthropic_key_set ? "Configured" : "Missing"}
            </Badge>
          </div>
        </CardContent>
      </Card>

      {/* System */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="h-5 w-5" /> System
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-sm text-slate-500">Database Path</span>
            <span className="text-sm font-mono">{settings.database_path}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-slate-500">CORS Origins</span>
            <span className="text-sm">{settings.cors_origins.join(", ")}</span>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
