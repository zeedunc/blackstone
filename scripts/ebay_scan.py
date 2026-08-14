#!/usr/bin/env python3
"""Parse and classify eBay search results for GPU deal-hunting.

Consumes a saved eBay search-results page (markdown, as produced by Hermes
`web_extract` or `curl | pandoc`) and classifies each listing into:
working-buy-it-now / working-auction / parts-only / scam-bait.

Why file-based instead of live-fetch? eBay serves HTTP 403 to plain
urllib/curl requests (bot-wall). For automation, use either:

  * eBay's official Browse API  (https://developer.ebay.com/api-docs/buy/browse/overview.html)
  * a headless browser (e.g. Hermes browser_exec), or
  * Hermes `web_extract` on the search URL, then feed the saved file here.

Usage:
    # 1) fetch the page however you like (example):
    #    web_extract saves to e.g. cache/web/www.ebay.com-<hash>.md
    python ebay_scan.py --html path/to/ebay_search.md --json out.json --out out.md

    # 2) or attempt a live fetch (usually 403 for eBay — see note above):
    python ebay_scan.py "RTX 3090 24GB" --pages 1
"""

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Matches markdown links produced by web_extract:  [title](https://www.ebay.com/itm/<id>...)
ITEM_LINK_RE = re.compile(
    r'\[([^\]]+)\]\((https://www\.ebay\.com/itm/(\d+)[^)]*)\)')
PRICE_RE = re.compile(r'\$([\d,]+(?:\.\d{2})?)')
SELLER_RE = re.compile(
    r'\b([A-Za-z0-9_.\-]{2,})\s+([\d.]+)% positive(?:\s*\(([\d,]+)\))?')
LOC_RE = re.compile(r'Located in\s+([A-Za-z ,\.]+)')
BIDS_RE = re.compile(r'\b(\d+)\s*bids?\b')

CONDITIONS = ["Brand New", "New (Other)", "Seller Refurbished", "Refurbished",
              "Pre-Owned", "Open Box", "Parts Only", "New"]


def fetch(url: str) -> str:
    """Best-effort live fetch. eBay usually 403s plain HTTP; prefer --html."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def search_url(query: str, page: int = 1) -> str:
    params = {"_nkw": query, "_sop": "15"}  # _sop=15 -> price+shipping, lowest first
    if page > 1:
        params["_pgn"] = str(page)
    return "https://www.ebay.com/sch/i.html?" + urllib.parse.urlencode(params)


def clean_title(t: str) -> str:
    t = re.sub(r'Opens in a new window or tab.*$', '', t)
    t = re.sub(r'^New Listing', '', t).strip()
    return t


def parse(html: str) -> list[dict]:
    """Extract listings from a web_extract-style markdown page."""
    html = html.replace("\\_", "_").replace("\\*", "*").replace("\\-", "-")
    lines = [l.strip() for l in html.split("\n")]
    out = []
    for i, ln in enumerate(lines):
        m = ITEM_LINK_RE.search(ln)
        if not m:
            continue
        title = clean_title(m.group(1))
        item_id = m.group(3)
        window = []
        for j in range(i + 1, min(i + 20, len(lines))):
            if ITEM_LINK_RE.search(lines[j]) or "derosnopS" in lines[j]:
                break
            window.append(lines[j])
        joined = " ".join(window)

        pm = PRICE_RE.search(joined)
        price = float(pm.group(1).replace(",", "")) if pm else None
        cond = next((c for c in CONDITIONS if c in joined), None)

        seller = fb_pct = fb_cnt = None
        sm = SELLER_RE.search(joined)
        if sm:
            seller, fb_pct, fb_cnt = sm.group(1), sm.group(2), sm.group(3)
        lm = LOC_RE.search(joined)
        loc = lm.group(1).strip() if lm else None

        out.append({
            "id": item_id,
            "url": f"https://www.ebay.com/itm/{item_id}",
            "title": title,
            "price": price,
            "cond": cond,
            "seller": seller,
            "fb_pct": fb_pct,
            "fb_cnt": fb_cnt,
            "loc": loc,
            "bids": bool(BIDS_RE.search(joined)),
            "buyitnow": "Buy It Now" in joined,
        })
    seen = {}
    for o in out:
        seen[o["id"]] = o
    return sorted(seen.values(), key=lambda r: (r["price"] if r["price"] is not None else 9e9))


def classify(L: dict) -> dict:
    title, cond = L["title"], L["cond"] or ""
    price, loc = L["price"], L["loc"] or ""
    flags, verdict = [], None

    if re.search(r'3060\s*3070\s*3080\s*3090', title) or re.search(r'8\s*10\s*12\s*24GB', title):
        verdict = "scam-bait"; flags.append("multi-variant bait: price is for cheapest card, not the 3090")
    elif cond == "Parts Only" or re.search(r'not working|no display|for parts|not wor|repair', title, re.I):
        verdict = "parts-only"; flags.append("listed for parts / not working")
    elif loc == "China" and re.search(r'FE|Founders', title, re.I):
        verdict = "scam-bait"; flags.append("'Founders Edition' sold from China is a known scam pattern")
    elif price is not None and price < 650 and cond not in ("Parts Only",):
        verdict = "scam-bait"; flags.append(f"price ${price:,.0f} far below working-market floor")
    elif L["bids"] and not L["buyitnow"]:
        verdict = "working-auction"
    elif L["buyitnow"] and not L["bids"]:
        verdict = "working-bin"
    else:
        verdict = "working-other"

    if verdict.startswith("working"):
        if L["fb_pct"] in (None, "0", "0.0") or (L["fb_pct"] and float(L["fb_pct"]) < 99.0):
            flags.append(f"low feedback ({L['fb_pct']}%)")
        if L["fb_cnt"] and int(L["fb_cnt"].replace(",", "")) < 15:
            flags.append(f"few ratings ({L['fb_cnt']})")
        if loc == "China":
            flags.append("ships from China")

    L["verdict"], L["flags"] = verdict, flags
    return L


def to_markdown(listings: list[dict], query: str) -> str:
    sections = [
        ("✅ Best working deals — Buy It Now", ["working-bin"]),
        ("🎯 Auctions to watch", ["working-auction"]),
        ("🟡 Other working listings", ["working-other"]),
        ("🚫 Scam / bait — AVOID", ["scam-bait"]),
        ("🔧 Parts-only (not working) — excluded", ["parts-only"]),
    ]
    md = [f"# {query} — eBay Deal Scan\n",
          f"> Scanned {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · {len(listings)} listings\n"]
    for name, verdicts in sections:
        sel = [r for r in listings if r["verdict"] in verdicts]
        sel.sort(key=lambda r: (r["price"] if r["price"] is not None else 9e9))
        md.append(f"\n## {name}\n")
        md.append("| Price | Condition | Seller | Feedback | Type | Listing |")
        md.append("|---|---|---|---|---|---|")
        for r in sel:
            p = f"${r['price']:,.0f}" if r["price"] is not None else "?"
            fb = f"{r['fb_pct']}% ({r['fb_cnt']})" if r["fb_pct"] else "?"
            md.append(f"| {p} | {r['cond']} | {r['seller'] or '?'} | {fb} | "
                      f"{r['verdict']} | [{r['title'][:52]}]({r['url']}) |")
            for f in r["flags"]:
                md.append(f"| | | | | | ⚠ {f} |")
    return "\n".join(md) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?")
    ap.add_argument("--html", help="parse a saved eBay search page (markdown) instead of live fetch")
    ap.add_argument("--pages", type=int, default=1)
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    all_rows = []
    if args.html:
        html = open(args.html, encoding="utf-8").read()
        all_rows = [classify(L) for L in parse(html)]
        print(f"[*] parsed {len(all_rows)} listings from {args.html}", file=sys.stderr)
    else:
        if not args.query:
            ap.error("provide a query string or --html FILE")
        for page in range(1, args.pages + 1):
            url = search_url(args.query, page)
            print(f"[*] fetching page {page}: {url}", file=sys.stderr)
            try:
                html = fetch(url)
            except Exception as e:
                print(f"[!] fetch failed ({e}). eBay blocks plain HTTP (403). "
                      "Use --html with a web_extract-saved page, eBay's Browse API, "
                      "or a headless browser.", file=sys.stderr)
                sys.exit(2)
            rows = [classify(L) for L in parse(html)]
            all_rows.extend(rows)
            print(f"    parsed {len(rows)} listings", file=sys.stderr)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"query": args.query or "from-file", "listings": all_rows}, f, indent=2)
    md = to_markdown(all_rows, args.query or "eBay")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"[*] wrote {args.out}", file=sys.stderr)
    else:
        print(md)


if __name__ == "__main__":
    main()
