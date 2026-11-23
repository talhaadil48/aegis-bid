"""Generate the repository's architecture SVGs without external image assets."""

from html import escape
from pathlib import Path

DIAGRAMS = {
    "01_existing.svg": (
        "Existing FlashBid proposal",
        ["Browser", "FastAPI / WebSockets", "Redis Lua / Streams", "Single Redis authority"],
    ),
    "02_new_architecture.svg": (
        "AegisBid local implementation",
        ["Role dashboards", "API / SQL intake journal", "Fenced PostgreSQL worker", "JetStream / outbox / live"],
    ),
    "03_bacula_disaster_recovery.svg": (
        "Verified local recovery path",
        ["Consistent SQL dump", "Manifest / checksums", "Bacula Catalog / media", "Isolated restore / verifier"],
    ),
    "04_decision_sequence.svg": (
        "Bid decision lifecycle",
        ["Authenticated request UUID", "Durable intake: QUEUED", "Transaction: DECIDED", "Commit / ACK / reconcile"],
    ),
}


def main():
    directory = Path("figures")
    directory.mkdir(exist_ok=True)
    for name, (title, labels) in DIAGRAMS.items():
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="250" viewBox="0 0 1000 250" role="img"><title>{escape(title)}</title><rect width="1000" height="250" fill="#101721"/><text x="30" y="50" fill="#b6ef72" font-family="sans-serif" font-size="24">{escape(title)}</text>'
        ]
        for index, label in enumerate(labels):
            x = 20 + index * 245
            parts.append(
                f'<rect x="{x}" y="100" width="225" height="90" rx="8" fill="#1d2b3c" stroke="#60758c"/><text x="{x + 112}" y="151" text-anchor="middle" fill="white" font-family="sans-serif" font-size="14">{escape(label)}</text>'
            )
            if index < 3:
                parts.append(f'<path d="M {x + 225} 145 h 18 l -5 -5 m 5 5 l -5 5" stroke="#b6ef72" fill="none"/>')
        parts.append("</svg>")
        (directory / name).write_text("".join(parts))


if __name__ == "__main__":
    main()
