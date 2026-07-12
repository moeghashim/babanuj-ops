#!/usr/bin/env python3
"""operations-sync.py — Operations.md → Command Center operations + AI daily briefs.

Parses ~/babanuj-ops/Operations.md (the operator's manual action log), UPSERTs each
row into the `operations` table, and asks Claude to write the "event of the day"
brief for each day → `operation_summaries`. The dashboard then shows one chart
marker per day (the brief + that day's actions) and the detailed ops panel. (#19)

Operations.md is the SOURCE OF TRUTH: rows no longer in the file are deleted.

Briefs are PROVIDER-AGNOSTIC — pick Anthropic, OpenAI, or xAI (Grok). If no
provider/key is configured, operations still sync — only the AI briefs are
skipped (so the pipeline never hard-depends on any one vendor). A day's brief is
regenerated only when that day's actions changed (ops_hash).

    OPS_BRIEF_PROVIDER  anthropic | openai | grok  (default: first key present)
    OPS_BRIEF_MODEL     override the provider's default model
    keys                ANTHROPIC_API_KEY / OPENAI_API_KEY / XAI_API_KEY (or GROK_API_KEY)

USAGE
    DATABASE_URL=postgres://bcc:bcc@localhost:5433/bcc \
        OPS_BRIEF_PROVIDER=openai OPENAI_API_KEY=sk-... \
        python3 operations-sync.py [--file Operations.md] [--dry-run] [--verbose]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

# pg_sync lives in ./lib — same import shape as the other extractors.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from lib import pg_sync as _pg_sync
    _PG_IMPORT_ERR = None
except Exception as ex:  # pragma: no cover
    _pg_sync = None
    _PG_IMPORT_ERR = ex

HOME = os.path.expanduser("~")
DEFAULT_FILE = os.path.join(HOME, "babanuj-ops", "Operations.md")
SOURCE = "operations"
VALID_IMPACT = {"good", "warn", "bad", "neutral"}

# ---- Pluggable brief backend: Anthropic / OpenAI / xAI (Grok) --------------
# All via raw HTTP (like the other extractors — no vendor SDKs). Pick with
# OPS_BRIEF_PROVIDER; each reads its own API key and has a default model that
# OPS_BRIEF_MODEL overrides. Defaults are current as of 2026-07 — if you switch
# vendors, confirm the model id in the provider's catalog:
#   Anthropic  https://docs.anthropic.com/en/docs/about-claude/models
#   OpenAI     https://platform.openai.com/docs/models   (e.g. set a gpt-5.x id)
#   xAI Grok   https://docs.x.ai/developers/models
PROVIDERS = {
    "anthropic": {"key_env": "ANTHROPIC_API_KEY", "kind": "anthropic",
                  "url": "https://api.anthropic.com/v1/messages",
                  "default_model": "claude-opus-4-8"},
    "openai":    {"key_env": "OPENAI_API_KEY", "kind": "openai",
                  "url": "https://api.openai.com/v1/chat/completions",
                  "default_model": "gpt-4o", "token_param": "max_completion_tokens"},
    "grok":      {"key_env": "XAI_API_KEY", "kind": "openai",
                  "url": "https://api.x.ai/v1/chat/completions",
                  "default_model": "grok-4.5", "token_param": "max_tokens"},
}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def vlog(verbose, *a):
    if verbose:
        log(*a)


def slugify(text):
    out = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return out or "op"


def parse_operations_md(path):
    """Parse the markdown table → list of op dicts (file order preserved)."""
    rows = []
    with open(path) as f:
        for line in f:
            s = line.strip()
            if not s.startswith("|"):
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) < 6:
                continue
            d = cells[0]
            # data rows start with an ISO date; this skips the header + separator.
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
                continue
            impact = (cells[5] or "neutral").lower()
            marker = cells[6].lower() if len(cells) > 6 else "no"
            rows.append({
                "date": d,
                "platform": cells[1].lower(),
                "type": cells[2],
                "title": cells[3],
                "detail": cells[4],
                "impact": impact if impact in VALID_IMPACT else "neutral",
                "is_marker": marker in ("yes", "y", "true", "1"),
                "id": f"op-{d}-{slugify(cells[3])}",
            })
    return rows


def _provider_key(name):
    """API key for a provider (grok accepts XAI_API_KEY or GROK_API_KEY)."""
    key = os.environ.get(PROVIDERS[name]["key_env"])
    if not key and name == "grok":
        key = os.environ.get("GROK_API_KEY")
    return key


def resolve_provider():
    """Pick the brief provider from env → dict, or None if none is configured.

    OPS_BRIEF_PROVIDER forces one; otherwise the first provider with a key set
    wins (anthropic → openai → grok). OPS_BRIEF_MODEL overrides the model.
    """
    name = os.environ.get("OPS_BRIEF_PROVIDER", "").strip().lower()
    if name and name not in PROVIDERS:
        log(f"[operations] unknown OPS_BRIEF_PROVIDER={name!r} "
            f"(valid: {', '.join(PROVIDERS)}) — skipping AI daily briefs")
        return None
    if not name:
        name = next((c for c in ("anthropic", "openai", "grok") if _provider_key(c)), "")
    if not name:
        return None
    key = _provider_key(name)
    if not key:
        env = PROVIDERS[name]["key_env"] + (" / GROK_API_KEY" if name == "grok" else "")
        log(f"[operations] {env} unset — skipping AI daily briefs")
        return None
    p = PROVIDERS[name]
    return {"name": name, "key": key, "kind": p["kind"], "url": p["url"],
            "model": os.environ.get("OPS_BRIEF_MODEL") or p["default_model"],
            "token_param": p.get("token_param", "max_tokens")}


def _http_json(url, headers, payload, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:300]}") from None


def day_brief(provider, day, ops):
    """Ask the configured LLM for the 1-2 sentence 'event of the day' brief (or None)."""
    lines = [f"- [{o['platform']}/{o['type']}] {o['title']}: {o['detail']}" for o in ops]
    prompt = (
        "You write the \"event of the day\" line for an e-commerce operator's "
        "dashboard. The brand is Babanuj, a Middle-Eastern sweets brand selling on "
        "its Website (Shopify), Amazon, and via ads (Amazon/Google/Meta). Summarize "
        "the day's operator actions below into ONE or TWO crisp sentences a busy "
        "founder can read at a glance: what changed and the thread connecting the "
        "moves. No preamble, no bullet points, no date prefix.\n\n"
        f"Actions on {day}:\n" + "\n".join(lines)
    )
    if provider["kind"] == "anthropic":
        resp = _http_json(provider["url"], {
            "x-api-key": provider["key"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }, {"model": provider["model"], "max_tokens": 250,
            "messages": [{"role": "user", "content": prompt}]})
        if resp.get("stop_reason") == "refusal":
            return None
        text = "".join(b.get("text", "") for b in (resp.get("content") or [])
                       if b.get("type") == "text").strip()
        return text or None

    # OpenAI-compatible chat/completions (OpenAI + xAI Grok)
    resp = _http_json(provider["url"], {
        "Authorization": f"Bearer {provider['key']}",
        "content-type": "application/json",
    }, {"model": provider["model"],
        "messages": [{"role": "user", "content": prompt}],
        provider["token_param"]: 250})
    choices = resp.get("choices") or []
    if not choices:
        return None
    msg = choices[0].get("message") or {}
    if msg.get("refusal"):            # OpenAI surfaces safety refusals here
        return None
    return (msg.get("content") or "").strip() or None


def main():
    ap = argparse.ArgumentParser(description="Operations.md → Command Center Postgres.")
    ap.add_argument("--file", default=DEFAULT_FILE)
    ap.add_argument("--dry-run", action="store_true", help="parse + print, no writes")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    ops = parse_operations_md(a.file)
    log(f"[operations] parsed {len(ops)} rows from {a.file}")
    by_day = {}
    for o in ops:
        by_day.setdefault(o["date"], []).append(o)

    # LLM provider is OPTIONAL — operations sync without it; only briefs need it.
    provider = resolve_provider()
    if provider:
        log(f"[operations] AI briefs via {provider['name']} · model {provider['model']}")
    else:
        log("[operations] no LLM provider configured — skipping AI daily briefs "
            "(set OPS_BRIEF_PROVIDER + that provider's API key)")

    if a.dry_run:
        print(json.dumps({"rows": len(ops), "days": sorted(by_day),
                          "ai_briefs": provider is not None, "sample": ops[:3]}, indent=2))
        log("[dry-run] no writes.")
        return

    if _pg_sync is None:
        log(f"[operations] pg_sync import failed: {_PG_IMPORT_ERR!r}"); sys.exit(1)
    pg = _pg_sync.PgSync.from_env(verbose=a.verbose)
    if pg is None:
        log("[operations] DATABASE_URL not set — nothing written"); sys.exit(1)

    counts = {"operations": 0, "summaries": 0, "summaries_unchanged": 0}

    # 1) existing brief hashes, so we only re-summarize days whose actions changed.
    existing = {}
    try:
        with pg:
            with pg.connect().cursor() as cur:
                cur.execute("select date::text, ops_hash from operation_summaries")
                existing = {r[0]: r[1] for r in cur.fetchall()}
    except Exception as ex:
        log(f"[operations] could not read existing summaries ({ex}); regenerating all")

    # 2) generate briefs for changed days (Claude calls — NO DB transaction held).
    briefs = {}  # day -> (summary, ops_hash, op_count)
    for day, day_ops in sorted(by_day.items()):
        h = hashlib.sha256(
            "|".join(o["id"] + o["title"] + o["detail"] for o in day_ops).encode()
        ).hexdigest()
        if existing.get(day) == h:
            counts["summaries_unchanged"] += 1
            continue
        if provider is None:
            continue
        try:
            brief = day_brief(provider, day, day_ops)
        except Exception as ex:
            log(f"[operations] brief for {day} failed: {ex}"); continue
        if brief:
            briefs[day] = (brief, h, len(day_ops))
            vlog(a.verbose, f"[operations] {day} ({len(day_ops)}): {brief}")

    # 3) one transaction: operations (source-of-truth) + briefs + bookkeeping.
    try:
        with pg:
            for o in ops:
                pg.upsert_operation(
                    op_id=o["id"], occurred_at=o["date"] + "T12:00:00Z",
                    platform=o["platform"], type_=o["type"], title=o["title"],
                    detail=o["detail"], impact=o["impact"], is_marker=o["is_marker"])
                counts["operations"] += 1
            pg.delete_operations_except([o["id"] for o in ops])
            for day, (brief, h, n) in briefs.items():
                pg.upsert_operation_summary(date=day, summary=brief, op_count=n, ops_hash=h)
                counts["summaries"] += 1
            pg.log_sync_run(SOURCE, ok=True)
        print(json.dumps({"ok": True, "upserts": counts}, indent=2))
    except Exception as ex:
        log(f"[operations] write FAILED: {ex}")
        try:
            with pg:
                pg.log_sync_run(SOURCE, ok=False)
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
