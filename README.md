# blackstone

Finding the best deals on GPUs — starting with **24 GB VRAM** cards, focused on the **RTX 3090**.

The goal is a repeatable, transparent way to scan auction sites (eBay first), filter out
scams and broken "for parts" listings, and surface only *real, working, fairly-priced* GPUs.

## Why "blackstone"

A scratch repo for GPU deal-hunting tooling and results. Data is checked in as
timestamped snapshots so price movement is trackable over time.

## Repo layout

```
blackstone/
├── data/
│   └── deals/                 # timestamped deal scans (JSON + human-readable MD)
├── scripts/
│   └── ebay_scan.py           # fetch eBay search results + classify listings
├── docs/
│   └── buying-guide.md        # how to spot scams / verify a listing
└── README.md
```

## Current snapshot

- **2026-08-14 — RTX 3090 24GB** → [`data/deals/2026-08-14_rtx3090_24gb.md`](data/deals/2026-08-14_rtx3090_24gb.md)

Market summary from that scan (eBay US, lowest-price-first):

| Tier | Price range | Verdict |
|---|---|---|
| Scam / multi-variant bait | $470–560 | avoid |
| Parts-only / not working | $650–850 | not a working GPU |
| Working 3090 (auction, current bid) | $800–1,130 | real, final price rises |
| Working 3090 (Buy It Now) | $1,115–1,260 | tested, from established sellers |

## Usage

```bash
# Scan eBay for a card, classify, write results to data/deals/
python scripts/ebay_scan.py "RTX 3090 24GB"

# Optional flags
python scripts/ebay_scan.py "RTX 3090 24GB" --pages 2 --out data/deals/latest.md
```

**Note:** `scripts/ebay_scan.py` uses a plain HTTPS fetch with a browser User-Agent.
For anything beyond light, occasional use, switch to eBay's official
[Browse API](https://developer.ebay.com/api-docs/buy/browse/overview.html)
(needs an app key) or a headless browser, and respect rate limits / ToS.

## Roadmap

- [ ] Add RTX 3090 Ti, RTX 4090, and RX 7900 XTX (other 24 GB cards)
- [ ] Price-history tracking across scans (detect real drops vs. list inflation)
- [ ] Optional eBay Browse API backend + cron scheduling
- [ ] Sold/completed-price lookup for a "fair value" baseline (needs an eBay account)

## Red flags (quick version)

- A **working** 3090 listed under ~$850 — too good to be true.
- "3060/3070/3080/3090" in one title — the low price is for the cheapest card.
- "Founders Edition" shipped from China — known repack/counterfeit vector.
- 0-feedback sellers on $1k+ items.

Full checklist in [`docs/buying-guide.md`](docs/buying-guide.md).
