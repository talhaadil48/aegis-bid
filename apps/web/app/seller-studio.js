"use client";

import { useCallback, useEffect, useState } from "react";
import { AuctionForm, auctionDetails } from "./auction-form";

const number = new Intl.NumberFormat("en-US");
const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
const clockTime = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit" });

function auctionState(auction, now) {
  if (auction.status === "CLOSED") return "Closed";
  if (new Date(auction.opens_at).getTime() > now) return "Scheduled";
  return new Date(auction.closes_at).getTime() <= now ? "Closing" : "Open";
}

function remaining(ms) {
  const seconds = Math.max(0, Math.ceil(ms / 1000));
  const parts = [
    [Math.floor(seconds / 86400), "d"],
    [Math.floor(seconds / 3600) % 24, "h"],
    [Math.floor(seconds / 60) % 60, "m"],
    [seconds % 60, "s"],
  ];
  return parts.filter(([value]) => value).slice(0, 2).map(([value, unit]) => value + unit).join(" ") || "0s";
}

function Status({ value }) {
  return <span className="seller-status" data-status={value.toLowerCase()}>{value.toLowerCase()}</span>;
}

function RecentBids({ activity, money }) {
  const stats = [
    ["Bidders", "bidders"],
    ["Total bids", "total"],
    ["Accepted", "accepted"],
    ["Rejected", "rejected"],
    ["Queued", "queued"],
    ["Late / closed", "closed"],
  ];
  return (
    <section className="seller-card seller-bids">
      <h3>Latest bids</h3>
      {!activity ? <p>Loading bid activity…</p> : (
        <>
          <dl className="seller-counts">
            {stats.map(([label, key]) => (
              <div key={key}><dt>{label}</dt><dd>{number.format(activity.counts[key])}</dd></div>
            ))}
          </dl>
          {activity.recent.length === 0 ? <p>No bids have been submitted yet.</p> : (
            <div className="scroll">
              <table>
                <caption>Five most recent bid requests</caption>
                <thead><tr><th>Bid</th><th>Offer</th><th>Received</th><th>Status</th><th>Decision reason</th></tr></thead>
                <tbody>
                  {activity.recent.map((bid) => (
                    <tr key={bid.request_id}>
                      <td><strong>#{bid.intake_seq}</strong><small>{bid.request_id.slice(0, 8)}</small></td>
                      <td>{money(bid.amount_cents)}</td>
                      <td><time dateTime={bid.admitted_at} title={dateTime.format(new Date(bid.admitted_at))}>{clockTime.format(new Date(bid.admitted_at))}</time></td>
                      <td><Status value={bid.state} /></td>
                      <td>{bid.reason || "Awaiting decision"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function downloadAudit(evidence) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(evidence, null, 2)], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `audit-${evidence.auction.id}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function SellerAuction({ api, entry, owned, now, money, onSnapshot }) {
  const id = entry.id;
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [closing, setClosing] = useState(false);
  const [audit, setAudit] = useState(null);
  const [loadingAudit, setLoadingAudit] = useState(false);

  useEffect(() => {
    let active = true;
    let timer;
    async function update() {
      try {
        const [auction, activity] = await Promise.all([
          api("/auctions/" + id),
          owned ? api(`/seller/auctions/${id}/activity`) : null,
        ]);
        const allocation = auction.status === "CLOSED" ? await api(`/auctions/${id}/winners`) : null;
        if (active) {
          setData({ auction, activity, allocation });
          onSnapshot(auction);
          setError("");
        }
      } catch (err) {
        if (active) setError(err.message);
      } finally {
        if (active) timer = setTimeout(update, 3000);
      }
    }
    update();
    return () => { active = false; clearTimeout(timer); };
  }, [api, id, owned, onSnapshot]);

  async function endAuction() {
    if (!window.confirm(`End “${entry.title}” now? Eligible queued bids will finish before winners are chosen.`)) return;
    setClosing(true);
    setActionError("");
    try {
      await api(`/admin/auctions/${id}/close`, {});
    } catch (err) {
      setActionError(err.message);
      setClosing(false);
    }
  }

  async function loadAudit() {
    setLoadingAudit(true);
    setActionError("");
    try {
      setAudit(await api("/audit/auctions/" + id));
    } catch (err) {
      setActionError(err.message);
    } finally {
      setLoadingAudit(false);
    }
  }

  const auction = data?.auction || entry;
  const state = auctionState(auction, now);
  const deadline = new Date(state === "Scheduled" ? auction.opens_at : auction.closes_at);
  return (
    <div className="seller-detail">
      {(error || actionError) && <p role="alert" className="error">{actionError || error}</p>}
      <section className="seller-card seller-overview">
        <div className="seller-overview-header">
          <div>
            <Status value={state} />
            <h2>{auction.title}</h2>
            <p>{auction.stock === 1 ? "1 unit" : `${auction.stock} units`} · {state === "Scheduled" ? "Opens" : "Closes"} {dateTime.format(deadline)}</p>
          </div>
          {owned && state === "Open" && (
            <button type="button" className="quiet seller-end" disabled={closing} onClick={endAuction}>
              {closing ? "Ending auction…" : "End auction"}
            </button>
          )}
        </div>
        <dl className="seller-prices">
          <div><dt>Highest offer</dt><dd>{data ? money(auction.high_cents) : "—"}</dd></div>
          <div><dt>Minimum next bid</dt><dd>{data && state === "Open" ? money(auction.minimum_next_cents) : "—"}</dd></div>
          <div>
            <dt>{state === "Scheduled" ? "Starts in" : "Time remaining"}</dt>
            <dd>{["Open", "Scheduled"].includes(state) ? remaining(deadline.getTime() - now) : state}</dd>
          </div>
        </dl>
        {data && <p className="seller-rules">Reserve {money(auction.min_price_cents)} · Increment {money(auction.increment_cents)}</p>}
      </section>
      {owned && <RecentBids activity={data?.activity} money={money} />}
      {data?.allocation?.state === "FINAL" && (
        <section className="seller-card">
          <h3>Final allocation</h3>
          {data.allocation.winners.length === 0 ? <p>No eligible offers.</p> : (
            <ol className="seller-winners">
              {data.allocation.winners.map((winner) => <li key={winner.rank}>{money(winner.amount_cents)}</li>)}
            </ol>
          )}
        </section>
      )}
      {owned && (
        <section className="seller-card">
          <div className="seller-audit-head">
            <div><h3>Auction audit</h3><p>Decision history and final allocation for independent verification.</p></div>
            <button type="button" className="quiet" disabled={loadingAudit} onClick={loadAudit}>
              {loadingAudit ? "Loading…" : audit ? "Refresh audit" : "Load audit evidence"}
            </button>
          </div>
          {audit && (
            <div className="seller-audit-result">
              <div>
                <strong>{number.format(audit.events.length)} recorded events</strong>
                <p>{audit.signature ? "Signed export" : "Unsigned export"}</p>
                <code title={audit.anchor}>{audit.anchor.slice(0, 16)}…</code>
              </div>
              <button type="button" onClick={() => downloadAudit(audit)}>Download JSON</button>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

export default function SellerStudio({ api, user, now, money }) {
  const [scope, setScope] = useState("mine");
  const [market, setMarket] = useState([]);
  const [mine, setMine] = useState([]);
  const [loadedScope, setLoadedScope] = useState(null);
  const [refresh, setRefresh] = useState(0);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState("");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    const setRows = scope === "mine" ? setMine : setMarket;
    api(scope === "mine" ? "/seller/auctions" : "/auctions")
      .then((rows) => {
        if (active) { setRows(rows); setLoadedScope(scope); }
      })
      .catch((err) => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [api, scope, refresh]);

  const onSnapshot = useCallback((snapshot) => {
    function updateRows(rows) {
      return rows.map((row) => (
        row.id === snapshot.id && (row.status !== snapshot.status || row.closes_at !== snapshot.closes_at)
          ? { ...row, status: snapshot.status, closes_at: snapshot.closes_at }
          : row
      ));
    }
    setMine(updateRows);
    setMarket(updateRows);
  }, []);
  const rows = scope === "mine" ? mine : market;
  const visible = rows.filter((row) =>
    row.title.toLowerCase().includes(search.trim().toLowerCase())
    && (filter === "all" || auctionState(row, now).toLowerCase() === filter),
  );
  const current = visible.find((row) => row.id === selected) || visible[0];

  async function publish(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const auction = await api("/seller/auctions", auctionDetails(event.currentTarget));
      setMine((rows) => [auction, ...rows]);
      setScope("mine");
      setFilter("all");
      setSearch("");
      setEditing(false);
      setSelected(auction.id);
      setRefresh((step) => step + 1);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="seller-studio">
      {error && <p role="alert" className="error">{error}</p>}
      <div className="seller-toolbar">
        <div className="seller-tabs" role="group" aria-label="Auction view">
          {["mine", "market"].map((tab) => (
            <button
              type="button"
              key={tab}
              aria-pressed={tab === scope}
              onClick={() => { setScope(tab); setSelected(""); setError(""); }}
            >
              {tab === "mine" ? "My auctions" : "Marketplace"}
            </button>
          ))}
        </div>
        <button type="button" aria-expanded={editing} onClick={() => setEditing(!editing)}>
          {editing ? "Hide form" : "+ New auction"}
        </button>
      </div>
      {editing && (
        <section className="seller-card seller-create">
          <h2>Create an auction</h2>
          <AuctionForm onSubmit={publish} busy={busy} />
        </section>
      )}
      <div className="seller-grid">
        <section className="seller-card seller-library" aria-label={scope === "mine" ? "My auctions" : "Marketplace auctions"}>
          <div className="seller-library-head">
            <h2>{scope === "mine" ? "Your listings" : "All listings"}</h2>
            <button type="button" className="quiet" onClick={() => { setError(""); setRefresh((step) => step + 1); }}>Refresh</button>
          </div>
          <div className="seller-filters">
            <input type="search" aria-label="Search auction titles" placeholder="Search titles" value={search} onChange={(e) => setSearch(e.target.value)} />
            <select aria-label="Filter by status" value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="all">All statuses</option>
              <option value="open">Open</option>
              <option value="scheduled">Scheduled</option>
              <option value="closing">Closing</option>
              <option value="closed">Closed</option>
            </select>
          </div>
          {rows.length > 0 && <p className="seller-list-count">{visible.length} of {rows.length}{rows.length === 100 ? " latest listings" : " listings"}</p>}
          <div className="seller-list">
            {visible.map((row) => (
              <button
                type="button"
                key={row.id}
                aria-pressed={row.id === current?.id}
                onClick={() => setSelected(row.id)}
              >
                <strong>{row.title}</strong>
                <span><Status value={auctionState(row, now)} />{row.stock === 1 ? "1 unit" : `${row.stock} units`}</span>
              </button>
            ))}
          </div>
          {visible.length === 0 && (
            <p>{loadedScope !== scope && !error ? "Loading auctions…" : rows.length ? "No listings match these filters." : "There are no auctions in this view yet."}</p>
          )}
        </section>
        {current && (
          <SellerAuction key={current.id} entry={current} owned={current.seller_id === user.id} api={api} now={now} money={money} onSnapshot={onSnapshot} />
        )}
      </div>
    </div>
  );
}
