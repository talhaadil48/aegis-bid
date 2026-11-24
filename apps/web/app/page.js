"use client";
import { useEffect, useState, useRef } from "react";
import { AuctionForm, auctionDetails } from "./auction-form";
import SellerStudio from "./seller-studio";

async function api(path, body) {
  const res = await fetch("/v1" + path, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => null);
  if (!res.ok)
    throw Error(
      typeof data?.detail === "string"
        ? data.detail
        : data?.detail
          ? JSON.stringify(data.detail)
          : "The request failed. Please try again.",
    );
  return data;
}
const money = (c) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(
    c / 100,
  );
const accountTypes = {
  bidder: "Bidder",
  seller: "Seller",
  auditor: "Auditor",
  admin: "Administrator",
};

function AccountType({ managed = false }) {
  const types = managed ? Object.keys(accountTypes) : ["bidder", "seller"];
  return (
    <label>
      Account type
      <select name="role" defaultValue="bidder">
        {types.map((role) => (
          <option key={role} value={role}>{accountTypes[role]}</option>
        ))}
      </select>
    </label>
  );
}

function AccountFields({ creating = false }) {
  return (
    <>
      <label>
        Username
        <input
          name="username"
          required
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          minLength={creating ? 3 : undefined}
          maxLength={creating ? 32 : 80}
          pattern={creating ? "[A-Za-z0-9_\\-]+" : undefined}
          aria-describedby={creating ? "username-hint" : undefined}
        />
      </label>
      {creating && (
        <p className="muted" id="username-hint">
          Use 3–32 letters, numbers, underscores or hyphens.
        </p>
      )}
      <label>
        Password
        <input
          name="password"
          type="password"
          required
          autoComplete={creating ? "new-password" : "current-password"}
          minLength={creating ? 12 : undefined}
          maxLength={128}
          aria-describedby={creating ? "password-hint" : undefined}
        />
      </label>
      {creating && (
        <>
          <p className="muted" id="password-hint">Use at least 12 characters.</p>
          <label>
            Confirm password
            <input
              name="confirmPassword"
              type="password"
              required
              autoComplete="new-password"
              maxLength={128}
            />
          </label>
        </>
      )}
    </>
  );
}

function accountDetails(form) {
  const { confirmPassword, ...details } = Object.fromEntries(new FormData(form));
  if (confirmPassword !== undefined && details.password !== confirmPassword)
    throw Error("Passwords do not match.");
  return details;
}

export default function Home() {
  const [user, setUser] = useState(null),
    [sessionLoading, setSessionLoading] = useState(true),
    [authMode, setAuthMode] = useState("login"),
    [setupAvailable, setSetupAvailable] = useState(false),
    [list, setList] = useState([]),
    [selected, setSelected] = useState(""),
    [auction, setAuction] = useState(null),
    [history, setHistory] = useState([]),
    [metrics, setMetrics] = useState(null),
    [backups, setBackups] = useState(null),
    [evidence, setEvidence] = useState(null),
    [winners, setWinners] = useState(null),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [live, setLive] = useState("Connecting"),
    [amount, setAmount] = useState(""),
    [now, setNow] = useState(Date.now()),
    [busy, setBusy] = useState(false);
  const retry = useRef(null);
  async function load() {
    const rows = await api("/auctions");
    setList(rows);
    if (!selected && rows.length) setSelected(rows[0].id);
  }
  useEffect(() => {
    api("/auth/me")
      .then(setUser)
      .catch(() =>
        api("/auth/setup").then((data) => setSetupAvailable(data.available)).catch(() => {}),
      )
      .finally(() => setSessionLoading(false));
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    if (!user || user.role === "seller") return;
    load().catch((e) => setError(e.message));
    const t = setInterval(() => {
      api("/me/bids")
        .then(setHistory)
        .catch(() => {});
      if (user.role === "admin") {
        api("/admin/metrics")
          .then(setMetrics)
          .catch(() => {});
        api("/admin/backups")
          .then(setBackups)
          .catch(() => {});
      }
    }, 2000);
    return () => clearInterval(t);
  }, [user]);
  useEffect(() => {
    if (!user || !selected) return;
    let done = false,
      socket,
      timer;
    function connect() {
      api("/auctions/" + selected)
        .then(setAuction)
        .catch((e) => setError(e.message));
      socket = new WebSocket(
        `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/v1/live/auctions/${selected}`,
      );
      socket.onopen = () => setLive("Live");
      socket.onmessage = (e) => {
        const next = JSON.parse(e.data);
        setAuction((old) => (!old || next.version >= old.version ? next : old));
      };
      socket.onclose = () => {
        setLive("Reconnecting");
        if (!done) timer = setTimeout(connect, 2000);
      };
    }
    connect();
    return () => {
      done = true;
      clearTimeout(timer);
      socket?.close();
    };
  }, [user, selected]);
  useEffect(() => {
    if (auction?.status === "CLOSED")
      api("/auctions/" + selected + "/winners")
        .then(setWinners)
        .catch(() => {});
    else setWinners(null);
  }, [auction?.status, selected]);
  async function act(fn) {
    setError("");
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function authenticate(e) {
    e.preventDefault();
    const form = e.currentTarget;
    await act(async () => {
      setUser(await api("/auth/" + authMode, accountDetails(form)));
    });
  }
  function switchAuth(mode) {
    setError("");
    setAuthMode(mode);
  }
  async function provision(e) {
    e.preventDefault();
    const form = e.currentTarget;
    setNotice("");
    await act(async () => {
      const account = await api("/admin/users", accountDetails(form));
      form.reset();
      setNotice(`Created ${accountTypes[account.role].toLowerCase()} account for ${account.username}.`);
    });
  }
  async function submit(e) {
    e.preventDefault();
    await act(async () => {
      const cents = Number(amount);
      if (!Number.isSafeInteger(cents) || cents < 1)
        throw Error("Enter an integer amount in cents");
      let pending = retry.current;
      if (
        pending &&
        (pending.auction !== selected || pending.amount !== cents)
      ) {
        const old = await api("/bid-requests/" + pending.id);
        if (old.state === "QUEUED")
          throw Error(
            "Previous offer is pending. Reconcile it before changing the amount.",
          );
        pending = null;
      }
      if (!pending) {
        pending = { id: crypto.randomUUID(), auction: selected, amount: cents };
        retry.current = pending;
        localStorage.setItem(
          "aegis-pending-" + user.id,
          JSON.stringify(pending),
        );
      }
      const result = await api("/auctions/" + selected + "/bids", {
        request_id: pending.id,
        amount_cents: cents,
      });
      setNotice(result.state + " · " + result.request_id);
      setHistory(await api("/me/bids"));
      retry.current = null;
      localStorage.removeItem("aegis-pending-" + user.id);
    });
  }
  useEffect(() => {
    if (user) {
      try {
        retry.current = JSON.parse(
          localStorage.getItem("aegis-pending-" + user.id),
        );
      } catch {}
    }
  }, [user]);
  async function create(e) {
    e.preventDefault();
    const form = e.currentTarget;
    await act(async () => {
      const a = await api("/seller/auctions", auctionDetails(form));
      await load();
      setSelected(a.id);
      setNotice("Auction created");
    });
  }
  return (
    <div className="shell">
      <aside>
        <a className="brand" href="/">
          A<span> / </span>AEGISBID<small>OMEGA AUCTION NETWORK</small>
        </a>
        <div className="rail-label">WORKSPACE</div>
        <div className="active">
          {user
            ? {
                bidder: "Auction floor",
                admin: "Operations room",
                seller: "Seller studio",
                auditor: "Audit laboratory",
              }[user.role]
            : "Welcome"}
        </div>
        <p className="aside-note">
          Every offer.
          <br />
          One durable decision.
        </p>
        <footer>
          PostgreSQL authority
          <br />
          Pay your own bid
        </footer>
      </aside>
      <main>
        <header>
          <div>
            <span className="eyebrow">
              AEGISBID / {user?.role?.toUpperCase() || "ACCESS"}
            </span>
            <h1>
              {user
                ? {
                    bidder: "The auction floor",
                    admin: "Your operations, in view.",
                    seller: "Seller studio",
                    auditor: "Verify the outcome.",
                  }[user.role]
                : "Bidding built on trust."}
            </h1>
          </div>
          {user && (
            <button
              className="quiet"
              onClick={() =>
                act(async () => {
                  await api("/auth/logout", {});
                  window.location.reload();
                })
              }
            >
              {user.username} · Sign out
            </button>
          )}
        </header>
        {error && (
          <div role="alert" className="error">
            {error}
          </div>
        )}
        {notice && (
          <div role="status" className="notice">
            {notice}
          </div>
        )}
        {sessionLoading ? (
          <p role="status">Checking your session…</p>
        ) : !user ? (
          <section className="login">
            <div>
              <span className="eyebrow">VERIFIABLE BY DESIGN</span>
              <h2>
                Fast auctions.
                <br />
                Lasting confidence.
              </h2>
              <p>
                Track your offer from durable intake to final decision.
                Reconnect at any time and retrieve the same result.
              </p>
            </div>
            <form key={authMode} onSubmit={authenticate}>
              <h3>
                {{
                  login: "Sign in",
                  register: "Create an account",
                  setup: "Set up the first administrator",
                }[authMode]}
              </h3>
              {authMode === "register" && (
                <AccountType />
              )}
              {authMode === "register" && (
                <p className="muted">Bidders place offers. Sellers publish auctions.</p>
              )}
              {authMode === "setup" && (
                <label>
                  Setup key
                  <input name="setup_key" type="password" required maxLength={256} autoComplete="off" />
                </label>
              )}
              <AccountFields creating={authMode !== "login"} />
              <button disabled={busy}>
                {{ login: "Sign in", register: "Create account", setup: "Create administrator" }[authMode]}
              </button>
              <button
                type="button"
                className="quiet auth-switch"
                disabled={busy}
                onClick={() => switchAuth(authMode === "login" ? "register" : "login")}
              >
                {authMode === "login" ? "Create an account" : "Back to sign in"}
              </button>
              {authMode === "login" && setupAvailable && (
                <button
                  type="button"
                  className="quiet auth-switch"
                  disabled={busy}
                  onClick={() => switchAuth("setup")}
                >
                  Set up administrator
                </button>
              )}
            </form>
          </section>
        ) : user.role === "seller" ? (
          <SellerStudio api={api} user={user} now={now} money={money} />
        ) : (
          <>
            {user.role === "admin" && (
              <section className="panel">
                <h2>Accounts</h2>
                <form className="account-form" onSubmit={provision}>
                  <AccountType managed />
                  <AccountFields creating />
                  <button disabled={busy}>Create account</button>
                </form>
              </section>
            )}
            {metrics && user.role === "admin" && (
              <>
                <div className="stats">
                  {[
                    ["Decisions", metrics.total],
                    ["Accepted", metrics.accepted],
                    ["Queued", metrics.queue_depth],
                    [
                      "Bids / sec",
                      metrics.bids_per_second_last_minute?.toFixed(2),
                    ],
                    [
                      "p95 decision",
                      metrics.latency_seconds?.[1] != null
                        ? (metrics.latency_seconds[1] * 1000).toFixed(0) + " ms"
                        : "No data",
                    ],
                    ["Live clients", metrics.open_connections_this_process],
                  ].map(([k, v]) => (
                    <article key={k}>
                      <span>{k}</span>
                      <strong>{v}</strong>
                    </article>
                  ))}
                </div>
                <section className="panel">
                  <h3>Worker leadership</h3>
                  <div className="scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>Auction</th>
                          <th>Holder</th>
                          <th>Epoch</th>
                          <th>Expires</th>
                        </tr>
                      </thead>
                      <tbody>
                        {metrics.leases.map((l) => (
                          <tr key={l.auction_id}>
                            <td>{l.auction_id.slice(0, 8)}</td>
                            <td>{l.holder_id}</td>
                            <td>{l.epoch}</td>
                            <td>
                              {new Date(
                                l.lease_expires_at,
                              ).toLocaleTimeString()}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p>
                    Latency measures durable admission to committed decision.
                    Connections cover this API process.
                  </p>
                </section>
              </>
            )}
            <div className="section-heading">
              <h2>Auctions</h2>
              <button className="quiet" onClick={() => act(load)}>
                Refresh
              </button>
            </div>
            <div className="auction-grid">
              <nav className="auction-list">
                {list.length === 0 && (
                  <p>No auctions yet. Sellers can create the first one.</p>
                )}
                {list.map((a) => (
                  <button
                    key={a.id}
                    className={a.id === selected ? "chosen" : "quiet"}
                    onClick={() => {
                      setSelected(a.id);
                      setEvidence(null);
                    }}
                  >
                    <small>
                      {a.status} · {a.stock} units
                    </small>
                    {a.title}
                  </button>
                ))}
              </nav>
              {auction && (
                <section className="auction panel">
                  <div className="section-heading">
                    <span className="pill">{auction.status}</span>
                    <span className="muted">
                      {live} · v{auction.version}
                    </span>
                  </div>
                  <h2>{auction.title}</h2>
                  <p className="muted">
                    Limited allocation · {auction.stock} winners · Pay your own
                    bid
                  </p>
                  <div className="price">
                    <span>Current highest offer</span>
                    <strong>{money(auction.high_cents)}</strong>
                  </div>
                  <div className="stats compact">
                    <article>
                      <span>Minimum next</span>
                      <strong>{money(auction.minimum_next_cents)}</strong>
                    </article>
                    <article>
                      <span>Time remaining</span>
                      <strong>
                        {Math.max(
                          0,
                          Math.ceil((new Date(auction.closes_at) - now) / 1000),
                        )}
                        s
                      </strong>
                    </article>
                  </div>
                  {user.role === "bidder" && auction.status === "OPEN" && (
                    <form onSubmit={submit} className="bid-form">
                      <label>
                        Your offer in cents
                        <input
                          type="number"
                          step="1"
                          min={auction.minimum_next_cents}
                          value={amount}
                          onChange={(e) => setAmount(e.target.value)}
                          placeholder={String(auction.minimum_next_cents)}
                          required
                        />
                      </label>
                      <button disabled={busy}>Queue offer</button>
                      <p className="muted">
                        Queued offers await a committed decision. The server
                        deadline determines eligibility.
                      </p>
                    </form>
                  )}
                  {user.role === "admin" &&
                    auction.status === "OPEN" && (
                      <button
                        className="quiet"
                        onClick={() =>
                          act(async () => {
                            await api(
                              "/admin/auctions/" + selected + "/close",
                              {},
                            );
                            setNotice(
                              "Closing after pending offers are decided",
                            );
                          })
                        }
                      >
                        End auction
                      </button>
                    )}
                  {winners && (
                    <div>
                      <h3>Final allocation</h3>
                      {winners.winners.map((w) => (
                        <p key={w.rank}>
                          #{w.rank} · {money(w.amount_cents)}{" "}
                          {w.is_you ? "· Your winning offer" : ""}
                        </p>
                      ))}
                    </div>
                  )}
                  {["admin", "auditor"].includes(user.role) && (
                    <button
                      onClick={() =>
                        act(async () =>
                          setEvidence(await api("/audit/auctions/" + selected)),
                        )
                      }
                    >
                      Load audit evidence
                    </button>
                  )}
                  {evidence && (
                    <div>
                      <p>
                        Independent verifier input · {evidence.events?.length}{" "}
                        events
                      </p>
                      <button
                        className="quiet"
                        onClick={() => {
                          const a = document.createElement("a");
                          a.href = URL.createObjectURL(
                            new Blob([JSON.stringify(evidence, null, 2)], {
                              type: "application/json",
                            }),
                          );
                          a.download = `audit-${selected}.json`;
                          a.click();
                          URL.revokeObjectURL(a.href);
                        }}
                      >
                        Download evidence
                      </button>
                    </div>
                  )}
                </section>
              )}
            </div>
            {user.role === "bidder" && (
              <section className="panel">
                <h2>Your bid history</h2>
                <div className="scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Request</th>
                        <th>Offer</th>
                        <th>Status</th>
                        <th>Decision</th>
                      </tr>
                    </thead>
                    <tbody>
                      {history.map((h) => (
                        <tr key={h.request_id}>
                          <td>
                            <button
                              className="text"
                              onClick={() =>
                                act(async () => {
                                  const r = await api(
                                    "/bid-requests/" + h.request_id,
                                  );
                                  setNotice(
                                    r.state +
                                      " · " +
                                      (r.decision?.reason ||
                                        "Awaiting decision"),
                                  );
                                })
                              }
                            >
                              {h.request_id.slice(0, 8)}
                            </button>
                          </td>
                          <td>{money(h.amount_cents)}</td>
                          <td>
                            <span className="pill">{h.state}</span>
                          </td>
                          <td>{h.reason || "Awaiting worker"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
            {user.role === "admin" && (
              <section className="panel">
                <h2>Create an auction</h2>
                <AuctionForm onSubmit={create} busy={busy} />
              </section>
            )}
            {user.role === "admin" && (
              <section className="panel">
                <h2>AegisVault · Recovery</h2>
                {!backups?.jobs?.length ? (
                  <p>
                    No backup jobs recorded yet. A successful export is separate
                    from a Bacula backup and verified restore.
                  </p>
                ) : (
                  <pre>{JSON.stringify(backups, null, 2)}</pre>
                )}
                <h3>Chaos Switchboard</h3>
                <p>
                  Available only when the server enables disposable-environment
                  testing.
                </p>
                <div className="actions">
                  {[
                    "pause-queue-consumer",
                    "resume-queue-consumer",
                    "kill-worker",
                    "restart-gateway",
                    "disconnect-client",
                  ].map((s) => (
                    <button
                      className="quiet"
                      key={s}
                      onClick={() =>
                        act(async () =>
                          setNotice(
                            JSON.stringify(
                              await api("/admin/chaos/scenarios", {
                                scenario: s,
                              }),
                            ),
                          ),
                        )
                      }
                    >
                      {s.replaceAll("-", " ")}
                    </button>
                  ))}
                </div>
              </section>
            )}
          </>
        )}
        <footer className="page-footer">
          AEGISBID OMEGA <span>Durable intake. Auditable decisions.</span>
        </footer>
      </main>
    </div>
  );
}
