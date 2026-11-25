import { useEffect, useState } from 'react';

const API = '/api/dashboard';

function fmtDate(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

function AccountCard({ account }) {
  return (
    <article className="account-card">
      <h3>{account.name}</h3>
      <p className="balance">{account.balanceLabel}</p>
      {account.note && <p className="note">{account.note}</p>}
      <p className="meta">Updated {fmtDate(account.updatedAt)}</p>
    </article>
  );
}

function SectionCard({ section }) {
  return (
    <section className="section-card" id={section.key}>
      <header>
        <h2>{section.title}</h2>
        <span className={`status status-${section.status}`}>{section.status}</span>
      </header>
      {section.summary && <p className="summary">{section.summary}</p>}
      {section.items && section.items.length > 0 ? (
        <ul className="items">
          {section.items.map((item) => (
            <li key={item.id || item.itemKey} className="item">
              <div className="item-head">
                <span className="item-label">{item.label}</span>
                {item.tag && <span className="tag">{item.tag}</span>}
              </div>
              {item.detail && <p className="item-detail">{item.detail}</p>}
            </li>
          ))}
        </ul>
      ) : (
        <p className="empty">No items yet.</p>
      )}
      <p className="meta">Updated {fmtDate(section.updatedAt)}</p>
    </section>
  );
}

export default function App() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch(API)
      .then((r) => {
        if (!r.ok) throw new Error(`API returned ${r.status}`);
        return r.json();
      })
      .then((json) => setData(json.data))
      .catch((err) => setError(err.message));
  }, []);

  if (error) {
    return (
      <main className="app error">
        <h1>Pineapple Dashboard</h1>
        <p>Could not load the dashboard: {error}</p>
        <p>Is the backend running? See README.md — `npm run dev`.</p>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="app loading">
        <h1>Pineapple Dashboard</h1>
        <p>Loading…</p>
      </main>
    );
  }

  return (
    <main className="app">
      <header className="app-header">
        <h1>Pineapple Dashboard</h1>
        <p className="meta">Last updated {fmtDate(data.lastUpdatedAt)}</p>
      </header>

      {data.accounts && data.accounts.length > 0 && (
        <section className="accounts" aria-label="Accounts">
          {data.accounts.map((a) => (
            <AccountCard key={a.key} account={a} />
          ))}
        </section>
      )}

      {data.needs && data.needs.length > 0 && (
        <section className="needs" aria-label="Needs">
          <h2>Needs</h2>
          <ul>
            {data.needs.map((n) => (
              <li key={n.id}>
                <strong>{n.label}</strong>
                {n.detail && <span> — {n.detail}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="sections">
        {(data.sections || []).map((s) => (
          <SectionCard key={s.key} section={s} />
        ))}
      </div>

      <section className="activity" aria-label="Activity">
        <h2>Activity</h2>
        {data.activity && data.activity.length > 0 ? (
          <ol>
            {data.activity.map((a) => (
              <li key={a.id}>
                <time>{fmtDate(a.createdAt)}</time>
                <span>{a.text}</span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="empty">No activity yet.</p>
        )}
      </section>

      <footer className="app-footer">
        <p>
          Pineapple Dashboard — data is stored locally in <code>server/data/dashboard.json</code>.
          Update it via the API (see README.md) or the actions in <code>server/index.js</code>.
        </p>
      </footer>
    </main>
  );
}
