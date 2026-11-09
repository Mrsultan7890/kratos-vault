import os
import re
from datetime import datetime, timezone

import requests
from core.enrichers._net import new_session

SESSION = new_session({"User-Agent": "Mozilla/5.0"})

# Free APIs
BTC_API  = "https://blockchain.info/rawaddr/{}"
ETH_API  = ("https://api.etherscan.io/api?module=account&action=balance"
            "&address={}&tag=latest&apikey={}")
ETH_TX   = ("https://api.etherscan.io/api?module=account&action=txlist"
            "&address={}&startblock=0&endblock=99999999&sort=asc&apikey={}")


def _eth_apikey() -> str:
    return os.environ.get("ETHERSCAN_API_KEY", "").strip() or "YourApiKeyToken"


def _fmt_ts(ts) -> str:
    """Unix epoch (int/str) → 'YYYY-MM-DD HH:MM UTC'; pass through if not parseable."""
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError):
        return str(ts or "")


def run(value: str) -> dict:
    result = {
        "value": value, "found": False,
        "tags": ["crypto-osint"], "platforms": {}, "screenshots": [], "notes": ""
    }
    coin = _detect_coin(value)
    result["coin_type"] = coin
    result["tags"].append(coin.lower())

    if coin == "BTC":
        result["platforms"]["blockchain"] = _btc_lookup(value)
    elif coin == "ETH":
        result["platforms"]["etherscan"]  = _eth_lookup(value)

    for p in result["platforms"].values():
        if p.get("found"):
            result["found"] = True

    result["notes"] = _build_notes(result)
    return result


def _detect_coin(value: str) -> str:
    if re.match(r"^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$", value):
        return "BTC"
    if re.match(r"^bc1[a-z0-9]{39,59}$", value):
        return "BTC"
    if re.match(r"^0x[a-fA-F0-9]{40}$", value):
        return "ETH"
    return "UNKNOWN"


def _btc_lookup(address: str) -> dict:
    try:
        r = SESSION.get(BTC_API.format(address), timeout=15)
        if r.status_code != 200:
            return {"found": False, "error": f"HTTP {r.status_code}"}
        d = r.json()
        balance_btc = d.get("final_balance", 0) / 1e8
        total_recv  = d.get("total_received", 0) / 1e8
        total_sent  = d.get("total_sent", 0) / 1e8
        txs = d.get("txs", [])
        first_tx = _fmt_ts(txs[-1].get("time", "")) if txs else ""
        last_tx  = _fmt_ts(txs[0].get("time", ""))  if txs else ""
        return {
            "found":        True,
            "balance_btc":  round(balance_btc, 8),
            "total_recv":   round(total_recv, 8),
            "total_sent":   round(total_sent, 8),
            "tx_count":     d.get("n_tx", 0),
            "first_tx":     first_tx,
            "last_tx":      last_tx,
            "explorer_url": f"https://www.blockchain.com/explorer/addresses/btc/{address}",
        }
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}


def _eth_lookup(address: str) -> dict:
    try:
        key = _eth_apikey()
        # Balance
        r = SESSION.get(ETH_API.format(address, key), timeout=15)
        d = r.json()
        balance_wei = int(d.get("result", 0)) if d.get("status") == "1" else 0
        balance_eth = balance_wei / 1e18

        # Transactions
        r2 = SESSION.get(ETH_TX.format(address, key), timeout=15)
        d2 = r2.json()
        txs = d2.get("result", []) if isinstance(d2.get("result"), list) else []

        first_tx = _fmt_ts(txs[0].get("timeStamp", ""))  if txs else ""
        last_tx  = _fmt_ts(txs[-1].get("timeStamp", "")) if txs else ""

        return {
            "found":        True,
            "balance_eth":  round(balance_eth, 8),
            "tx_count":     len(txs),
            "first_tx":     first_tx,
            "last_tx":      last_tx,
            "explorer_url": f"https://etherscan.io/address/{address}",
        }
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}


def _build_notes(r: dict) -> str:
    lines = [f"=== Crypto OSINT: {r['value']} ===",
             f"  Coin Type   : {r.get('coin_type','')}"]
    b = r["platforms"].get("blockchain", {})
    if b.get("found"):
        lines += ["\n--- Bitcoin (blockchain.info) ---",
                  f"  Balance     : {b.get('balance_btc',0)} BTC",
                  f"  Total Recv  : {b.get('total_recv',0)} BTC",
                  f"  Total Sent  : {b.get('total_sent',0)} BTC",
                  f"  Tx Count    : {b.get('tx_count',0)}",
                  f"  First TX    : {b.get('first_tx','')}",
                  f"  Last TX     : {b.get('last_tx','')}",
                  f"  Explorer    : {b.get('explorer_url','')}"]
    e = r["platforms"].get("etherscan", {})
    if e.get("found"):
        lines += ["\n--- Ethereum (etherscan.io) ---",
                  f"  Balance     : {e.get('balance_eth',0)} ETH",
                  f"  Tx Count    : {e.get('tx_count',0)}",
                  f"  First TX    : {e.get('first_tx','')}",
                  f"  Last TX     : {e.get('last_tx','')}",
                  f"  Explorer    : {e.get('explorer_url','')}"]
    return "\n".join(lines)
