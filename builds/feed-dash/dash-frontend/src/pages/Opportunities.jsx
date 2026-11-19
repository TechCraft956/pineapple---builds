/**
 * Opportunities — live view over the Shared Feed service.
 * Polls GET /api/feed/opportunities every 30 seconds and re-renders on
 * change: update the feed data and this view updates with no rebuild and
 * no manual refresh. Reads are unauthenticated by design (no secret in
 * this bundle); writes go through the feed service's bearer token only.
 * If the feed is unreachable the page degrades to an error state instead
 * of failing the whole dashboard.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { feedApi } from "../lib/api";

const POLL_MS = 30000;

function RiskPill({ level }) {
  const tones = { low: "bg-emerald-500/15 text-emerald-300", medium: "bg-amber-500/15 text-amber-300", high: "bg-red-500/15 text-red-300" };
  const tone = tones[level] || tones.medium;
  return <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${tone}`}>{level || "unknown"}</span>;
}

export default function Opportunities() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [pollCount, setPollCount] = useState(0);
  const timerRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const res = await feedApi.listOpportunities({ limit: 50, sort: "collected_at_desc" });
      setItems(res.data.items || []);
      setTotal(res.data.total ?? 0);
      setLastUpdated(new Date().toISOString());
      setError(null);
    } catch (err) {
      setError("Feed unreachable — showing last known data.");
      console.error("Failed to load feed opportunities", err);
    } finally {
      setLoading(false);
      setPollCount((c) => c + 1);
    }
  }, []);

  useEffect(() => {
    load();
    timerRef.current = setInterval(load, POLL_MS);
    return () => clearInterval(timerRef.current);
  }, [load]);

  if (loading) {
    return <div className="flex items-center justify-center gap-2 py-20 text-zinc-500"><Loader2 size={18} className="animate-spin" /> Loading opportunities from the shared feed...</div>;
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col gap-2 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">Opportunities</h1>
          <p className="mt-1 text-sm text-zinc-500">Live from the shared feed — polls every 30s, no rebuild, no manual refresh.</p>
        </div>
        <div className="text-xs text-zinc-500">
          <div>{total} record{total === 1 ? "" : "s"} in feed</div>
          {lastUpdated && <div>Last poll: <span className="text-zinc-300">{new Date(lastUpdated).toLocaleTimeString()}</span> (poll #{pollCount})</div>}
        </div>
      </div>

      {error && <div className="rounded-md bg-amber-500/10 px-4 py-3 text-sm text-amber-300">{error}</div>}

      {!items.length && !error && (
        <div className="py-20 text-center text-zinc-500">No opportunities in the feed yet.</div>
      )}

      <div className="space-y-3">
        {items.map((item) => (
          <div key={item.id} className="module-card">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-base font-medium text-zinc-100">{item.title}</div>
                <div className="mt-1 text-xs text-zinc-500">
                  {item.type} · {item.source} · collected {item.collected_at ? new Date(item.collected_at).toLocaleString() : "unknown"}
                </div>
              </div>
              <RiskPill level={item.risk_level} />
            </div>
            <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm text-zinc-300">
              <span>Est. value: <span className="text-zinc-100">{item.est_value_unknown ? "unknown" : `$${item.est_value}`}</span></span>
              <span>Cost: <span className="text-zinc-100">${item.purchase_price}</span></span>
              <span>Confidence: <span className="text-zinc-100">{Math.round((item.confidence ?? 0) * 100)}%</span></span>
              <span>Approval: <span className="text-zinc-100">{item.approval_status}</span></span>
            </div>
            {item.next_action && <div className="mt-2 text-sm text-zinc-400">Next: {item.next_action}</div>}
            {item.evidence && <div className="mt-1 text-xs text-zinc-500">{item.evidence}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}
