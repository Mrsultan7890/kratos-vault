# Kratos Vault

Kratos Vault is a local desktop workspace for organizing OSINT investigations. It combines case management, entities and links, media metadata, timelines, notes, reports, and optional analysis helpers.

> **Privacy notice:** The local vault is encrypted, but enabling Remote Lookups sends selected indicators to external services. Do not use real or sensitive investigation data until you have reviewed each provider's terms, privacy practices, and your authority to submit that data.

## Features

- Encrypted local SQLCipher vault; existing plaintext vaults are encrypted in place at first unlock.
- Encrypted case exports and full-vault backups using AES-256-GCM.
- Cases, entities, links, notes, media, timelines, and an audit log.
- Graph analysis, IOC extraction, NER, deduplication, risk scoring, and image analysis.
- Optional remote enrichment. It is **off by default** and requires an explicit, session-only opt-in in the top bar.

ML outputs are suggestions, not verified investigative facts. See [MODEL_CARD.md](MODEL_CARD.md) for training-data caveats and limitations.

## Requirements and installation

- Python 3.10 or later.
- A desktop environment supported by PyQt6.
- Chromium and a matching ChromeDriver are needed only for browser-based enrichment. Set `CHROME_PATH` and `CHROMEDRIVER_PATH` if they are not at `/usr/bin/chromium` and `/usr/bin/chromedriver`.

Create an isolated environment, install dependencies, and run the app:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

The ML packages (including PyTorch, spaCy, and Ultralytics) are large. The first run of some features may download model weights; these downloads are not part of Remote Lookups. Install the spaCy English model separately if you want its NER model:

```bash
python -m spacy download en_core_web_sm
```

At first launch, create a vault password of at least 12 characters. The password is not recoverable. Existing unencrypted `~/.kratos_vault/vault.db` files are migrated to encryption before the application opens them. Keep an independent encrypted export if you need recovery.

## Remote lookups and network behavior

Remote Lookups is disabled at startup and resets to off when the app closes. Enabling it allows the app to query providers used by the enrichers, which can include DNS/WHOIS, IP and domain intelligence, blockchain explorers, social platforms, and other public lookup services. Submitted values may include email addresses, phone numbers, IP addresses, URLs, domains, hashes, usernames, or image files. Provider availability, terms, and data retention can change.

The application does not claim to be offline. DNS queries use the system resolver and may not follow an HTTP proxy; some optional integrations use their own HTTP clients and may not honor `KV_PROXY`. Set `KV_PROXY` to route supported HTTP requests through a proxy, for example:

```bash
KV_PROXY=socks5h://127.0.0.1:9050 python main.py
```

SOCKS support requires PySocks. If it is unavailable, the application fails the proxied request rather than silently falling back to a direct connection. Browser enrichment uses the configured local Chromium/ChromeDriver binaries and does not download drivers automatically.

The URL header lookup blocks non-public addresses and does not follow redirects. This is a defense-in-depth check, not a substitute for reviewing URLs before enabling remote lookups.

## Data handling

- The main database, automatic database snapshots, and enrichment-status file are encrypted at rest.
- Browser screenshots are stored temporarily in an owner-only directory and removed after importing them into the encrypted vault.
- Losing the vault password means losing access to the vault and its snapshots.
- Case exports and full-vault exports use a separate password; use a strong password and store it separately.
- Import accepts encrypted files up to 512 MiB and validates the payload before writing. Full-vault imports are atomic.
- Reports exported as HTML or PDF are unencrypted. Store and share them accordingly.

## Development and tests

Run the focused automated suite:

```bash
python -m unittest discover -s tests -v
```

The CI workflow runs these tests on Linux. For a minimal test environment, install `PyQt6`, `cryptography`, `requests`, and `sqlcipher3-binary`.

## Licensing

The repository includes an MIT license draft. Confirm the copyright holder and project license before publishing. PyQt6 and other dependencies have their own licenses; review them before redistributing a bundled application.
# kratos-vault
