import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Info,
  RefreshCw,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  ApiErrorEntry,
  ApiErrorSummaryGroup,
  ApiErrorsMeta,
  ApiErrorsSource,
} from "@/lib/api";
import { isoTimeAgo, timeAgo } from "@/lib/utils";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { FilterGroup, Segmented } from "@nous-research/ui/ui/components/segmented";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import { Input } from "@nous-research/ui/ui/components/input";
import {
  Select,
  SelectOption,
} from "@nous-research/ui/ui/components/select";
import { useI18n } from "@/i18n";
import { usePageHeader } from "@/contexts/usePageHeader";
import { PluginSlot } from "@/plugins";

const SOURCES: readonly ApiErrorsSource[] = ["store", "logs"];
const WINDOWS = [
  { value: "60", label: "1h" },
  { value: "360", label: "6h" },
  { value: "1440", label: "24h" },
  { value: "10080", label: "7d" },
] as const;
const LIMIT = 200;
const POLL_MS = 15000;

const filterGroupClass =
  "flex min-w-0 w-full flex-col items-start gap-1.5 sm:w-auto sm:max-w-full sm:flex-row sm:items-center";

const segmentedClass = "w-fit max-w-full flex-wrap justify-start self-start";

const relativeTs = (ts: number | string) =>
  typeof ts === "number" ? timeAgo(ts) : isoTimeAgo(ts);

const absoluteTs = (ts: number | string) => {
  const date = new Date(typeof ts === "number" ? ts * 1000 : ts);
  return Number.isNaN(date.getTime()) ? String(ts) : date.toLocaleString();
};

const formatAttempt = (entry: ApiErrorEntry) => {
  if (entry.retry_count == null && entry.max_retries == null) return "—";
  return `${entry.retry_count ?? "?"}/${entry.max_retries ?? "?"}`;
};

export default function ErrorsPage() {
  const [source, setSource] = useState<ApiErrorsSource | null>(null);
  const [meta, setMeta] = useState<ApiErrorsMeta | null>(null);
  const [windowMinutes, setWindowMinutes] = useState<string>("1440");
  const [providerInput, setProviderInput] = useState("");
  const [provider, setProvider] = useState("");
  const [statusInput, setStatusInput] = useState("");
  const [statusCode, setStatusCode] = useState("");
  const [errors, setErrors] = useState<ApiErrorEntry[]>([]);
  const [groups, setGroups] = useState<ApiErrorSummaryGroup[]>([]);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { t } = useI18n();
  const { setAfterTitle, setEnd } = usePageHeader();

  // Debounce the free-text filters so each keystroke doesn't fire a request.
  useEffect(() => {
    const id = setTimeout(() => setProvider(providerInput.trim()), 400);
    return () => clearTimeout(id);
  }, [providerInput]);

  useEffect(() => {
    const id = setTimeout(() => setStatusCode(statusInput.trim()), 400);
    return () => clearTimeout(id);
  }, [statusInput]);

  // Meta tells us which source the backend serves by default and carries the
  // honesty note for logs mode (shown next to the toggle).
  useEffect(() => {
    api
      .getErrorsMeta()
      .then((m) => {
        setMeta(m);
        setSource((s) => s ?? m.default_source);
      })
      .catch(() => setMeta(null));
  }, []);

  const fetchErrors = useCallback(() => {
    setLoading(true);
    setError(null);
    const since = Number(windowMinutes);
    Promise.all([
      api.getErrors({
        limit: LIMIT,
        since_minutes: since,
        provider: provider || undefined,
        status_code: statusCode || undefined,
        source: source ?? undefined,
      }),
      api.getErrorsSummary(since),
    ])
      .then(([errorsResp, summaryResp]) => {
        setErrors(errorsResp.errors);
        setGroups(summaryResp.groups);
      })
      .catch((err) => setError(String(err)))
      .finally(() => setLoading(false));
  }, [windowMinutes, provider, statusCode, source]);

  useEffect(() => {
    fetchErrors();
  }, [fetchErrors]);

  // Poll: the store is written by whichever process ran the failed turn, so
  // there is no push channel to subscribe to — a 15s read is the live path.
  useEffect(() => {
    const interval = setInterval(fetchErrors, POLL_MS);
    return () => clearInterval(interval);
  }, [fetchErrors]);

  useLayoutEffect(() => {
    setAfterTitle(
      <span className="flex items-center gap-1.5">
        <Badge tone="secondary" className="text-xs">
          {(source ?? meta?.default_source ?? "store").toUpperCase()} ·{" "}
          {WINDOWS.find((w) => w.value === windowMinutes)?.label ??
            windowMinutes}
        </Badge>
        <Button
          type="button"
          ghost
          size="icon"
          className="text-muted-foreground hover:text-foreground"
          onClick={fetchErrors}
          disabled={loading}
          aria-label={t.common.refresh}
        >
          {loading ? <Spinner /> : <RefreshCw />}
        </Button>
      </span>,
    );
    setEnd(
      <Badge tone="success" className="text-xs">
        <span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
        {t.common.live}
      </Badge>,
    );
    return () => {
      setAfterTitle(null);
      setEnd(null);
    };
  }, [
    fetchErrors,
    loading,
    meta,
    setAfterTitle,
    setEnd,
    source,
    t.common.live,
    t.common.refresh,
    windowMinutes,
  ]);

  const toggleExpanded = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const applyGroupFilter = (group: ApiErrorSummaryGroup) => {
    setProviderInput(group.provider ?? "");
    setProvider(group.provider ?? "");
    setStatusInput(group.status_code != null ? String(group.status_code) : "");
    setStatusCode(group.status_code != null ? String(group.status_code) : "");
  };

  return (
    <div className="flex min-w-0 max-w-full flex-col gap-4">
      <PluginSlot name="errors:top" />
      <div
        role="toolbar"
        aria-label={t.app.nav.errors}
        className="flex min-w-0 max-w-full flex-col items-start gap-3 sm:flex-row sm:flex-wrap sm:items-start sm:gap-x-6 sm:gap-y-3"
      >
        <FilterGroup label={t.errors.source} className={filterGroupClass}>
          <Segmented
            className={segmentedClass}
            value={source ?? meta?.default_source ?? "store"}
            onChange={(v) => setSource(v as ApiErrorsSource)}
            options={SOURCES.map((s) => ({
              value: s,
              label: s.toUpperCase(),
            }))}
          />
          {meta?.logs_cons_note && (
            <span
              className="flex items-center gap-1 text-xs text-muted-foreground"
              title={meta.logs_cons_note}
            >
              <Info className="h-3.5 w-3.5 shrink-0" />
              {source === "logs" && (
                <span className="max-w-xs">{meta.logs_cons_note}</span>
              )}
            </span>
          )}
        </FilterGroup>

        <FilterGroup label={t.errors.window} className={filterGroupClass}>
          <Select
            value={windowMinutes}
            onValueChange={setWindowMinutes}
          >
            {WINDOWS.map((w) => (
              <SelectOption key={w.value} value={w.value}>
                {w.label}
              </SelectOption>
            ))}
          </Select>
        </FilterGroup>

        <FilterGroup label={t.errors.provider} className={filterGroupClass}>
          <Input
            value={providerInput}
            onChange={(e) => setProviderInput(e.target.value)}
            placeholder={t.errors.providerPlaceholder}
            className="w-full sm:w-44"
          />
        </FilterGroup>

        <FilterGroup label={t.errors.statusCode} className={filterGroupClass}>
          <Input
            value={statusInput}
            onChange={(e) => setStatusInput(e.target.value)}
            placeholder={t.errors.statusCodePlaceholder}
            inputMode="numeric"
            className="w-full sm:w-28"
          />
        </FilterGroup>
      </div>

      {groups.length > 0 && (
        <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2">
          {groups.map((g, i) => (
            <button
              key={`${g.provider}-${g.status_code}-${g.reason}-${i}`}
              type="button"
              onClick={() => applyGroupFilter(g)}
              className="cursor-pointer"
              title={t.errors.provider}
            >
              <Badge tone="warning" className="text-xs">
                {g.provider ?? t.common.unknown} ·{" "}
                {g.status_code ?? "?"}
                {g.reason ? ` · ${g.reason}` : ""} × {g.count}
              </Badge>
            </button>
          ))}
        </div>
      )}

      <Card className="min-w-0 max-w-full overflow-hidden">
        <CardHeader className="py-3 px-4">
          <CardTitle className="text-sm flex items-center gap-2">
            <AlertTriangle className="h-4 w-4" />
            {t.app.nav.errors}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {error && (
            <div className="bg-destructive/10 border-b border-destructive/20 p-3">
              <p className="text-sm text-destructive">{error}</p>
            </div>
          )}

          <div className="max-w-full overflow-x-auto">
            <table className="w-full font-mondwest normal-case text-sm">
              <thead>
                <tr className="border-b border-border text-muted-foreground text-xs">
                  <th className="text-left py-2 pl-4 pr-4 font-medium">
                    {t.errors.colTime}
                  </th>
                  <th className="text-left py-2 pr-4 font-medium">
                    {t.errors.provider}
                  </th>
                  <th className="text-left py-2 pr-4 font-medium">
                    {t.errors.colModel}
                  </th>
                  <th className="text-left py-2 pr-4 font-medium">
                    {t.errors.statusCode}
                  </th>
                  <th className="text-left py-2 pr-4 font-medium">
                    {t.errors.colReason}
                  </th>
                  <th className="text-left py-2 pr-4 font-medium">
                    {t.errors.colAttempt}
                  </th>
                  <th className="text-left py-2 pr-4 font-medium">
                    {t.errors.colSession}
                  </th>
                  <th className="py-2 pr-4 font-medium" aria-hidden />
                </tr>
              </thead>
              <tbody>
                {errors.length === 0 && !loading && (
                  <tr>
                    <td
                      colSpan={8}
                      className="text-muted-foreground text-center py-8"
                    >
                      {t.errors.noErrors}
                    </td>
                  </tr>
                )}
                {errors.map((entry) => (
                  <ErrorRow
                    key={entry.id}
                    entry={entry}
                    expanded={expanded.has(entry.id)}
                    onToggle={() => toggleExpanded(entry.id)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
      <PluginSlot name="errors:bottom" />
    </div>
  );
}

function ErrorRow({
  entry,
  expanded,
  onToggle,
}: {
  entry: ApiErrorEntry;
  expanded: boolean;
  onToggle: () => void;
}) {
  const { t } = useI18n();
  const hasMessage = !!entry.error_message;
  return (
    <>
      <tr
        className="border-b border-border/50 hover:bg-secondary/20 transition-colors cursor-pointer"
        onClick={hasMessage ? onToggle : undefined}
      >
        <td
          className="py-2 pl-4 pr-4 whitespace-nowrap text-muted-foreground"
          title={absoluteTs(entry.ts)}
        >
          {relativeTs(entry.ts)}
        </td>
        <td className="py-2 pr-4">{entry.provider ?? "—"}</td>
        <td className="py-2 pr-4">
          <span className="font-mono-ui text-xs">{entry.model ?? "—"}</span>
        </td>
        <td className="py-2 pr-4 whitespace-nowrap">
          {entry.status_code ?? "—"}
          {!entry.retryable && (
            <Badge tone="destructive" className="ml-2 text-xs">
              {t.errors.terminal}
            </Badge>
          )}
        </td>
        <td className="py-2 pr-4">{entry.reason ?? "—"}</td>
        <td className="py-2 pr-4 whitespace-nowrap text-muted-foreground">
          {formatAttempt(entry)}
        </td>
        <td className="py-2 pr-4">
          {entry.session_id ? (
            <Link
              to={`/chat?resume=${encodeURIComponent(entry.session_id)}`}
              onClick={(e) => e.stopPropagation()}
              className="font-mono-ui text-xs text-midground hover:underline"
              title={entry.session_id}
            >
              {entry.session_id.slice(0, 8)}
            </Link>
          ) : (
            "—"
          )}
        </td>
        <td className="py-2 pr-4 text-muted-foreground">
          {hasMessage &&
            (expanded ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            ))}
        </td>
      </tr>
      {expanded && hasMessage && (
        <tr className="border-b border-border/50">
          <td colSpan={8} className="py-3 px-4 bg-secondary/10">
            <pre className="whitespace-pre-wrap break-words font-mono-ui text-xs leading-5">
              {entry.error_message}
            </pre>
          </td>
        </tr>
      )}
    </>
  );
}
