export function formatCurrency(amount: number | null | undefined, currency = "RWF"): string {
  if (amount == null) return "Value TBD";
  return `${currency} ${amount.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

export function maskPhone(phone: string): string {
  if (phone.length <= 6) return phone;
  return phone.slice(0, 6) + "***" + phone.slice(-3);
}

export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return dateStr.slice(0, 10);
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export function statusColor(status: string): string {
  switch (status) {
    case "complete": return "bg-green-100 text-green-800";
    case "active": return "bg-green-100 text-green-800";
    case "awaiting_name": return "bg-yellow-100 text-yellow-800";
    case "awaiting_sector": return "bg-blue-100 text-blue-800";
    case "inactive": return "bg-gray-100 text-gray-800";
    default: return "bg-gray-100 text-gray-800";
  }
}
