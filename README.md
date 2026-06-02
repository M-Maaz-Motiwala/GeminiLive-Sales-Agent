# Asterisk + FastAPI + Gemini Live calling agent

A minimal R&D rig that lets you register a SIP softphone (Zoiper desktop,
Linphone, etc.) on your laptop, dial an extension, and talk to a Google
Gemini Live model. Asterisk handles the SIP/RTP, ARI hands the call into a
`Stasis` app, and a FastAPI service ferries μ-law RTP between Asterisk and
the Gemini Live WebSocket.

## Architecture

```
Zoiper (host)  --SIP/RTP--> Asterisk(PJSIP, ARI)
                                |
                                |  Stasis(gemini-agent)
                                v
                          ExternalMedia (ulaw RTP)
                                |
                                v
                 FastAPI bridge (Python, this repo)
                                |
                                v  WebSocket, audio/pcm 16 kHz in / 24 kHz out
                          Gemini Live API
```

## What you need

- Docker + Docker Compose.
- A Gemini API key from <https://aistudio.google.com/apikey>.
- A SIP softphone. Zoiper Desktop is the easiest on Linux.

## Quickstart

```bash
cp .env.example .env
# edit .env and paste your GEMINI_API_KEY
docker compose up --build
```

On a successful start you should see:

- `gemini_bridge` logs `Bridge started. RTP listening on UDP 40000` and
  `Gemini Live connected`.
- `asterisk` logs `PJSIP Listening on Transport ...` and ARI starts on
  `0.0.0.0:8088`.

Check the bridge health endpoint:

```bash
curl -s http://localhost:8000/health | jq
```

## Configure Zoiper

Create a new SIP account in Zoiper with:

| Field      | Value           |
| ---------- | --------------- |
| Username   | `1000`          |
| Password   | `1000pass`      |
| Domain     | `127.0.0.1`     |
| Outbound   | (leave empty)   |
| Transport  | UDP             |
| Codecs     | G.711 μ-law (`PCMU`) only |

Optionally add a second profile for `1001` / `1001pass` if you want
to call extension-to-extension.

When Zoiper reports `Registered`, you are ready.

## What to dial

| Dial | What happens |
| ---- | ------------ |
| `700` | Sends the call into `Stasis(gemini-agent)`. The FastAPI bridge attaches an `externalMedia` leg, streams audio to/from Gemini Live, and you hear the model speak. |
| `600` | Asterisk `Echo()` test. Useful to check your softphone codec/mic. |
| `1000` | Rings Zoiper account 1000. |
| `1001` | Rings Zoiper account 1001. Use this from 1000 to verify two-way SIP/RTP audio before involving the AI. |

## Useful commands

```bash
# Tail bridge logs (USER:/GEMINI: transcript lines appear here)
docker logs -f gemini_bridge

# Tail Asterisk console
docker logs -f asterisk

# Drop into the Asterisk CLI
docker exec -it asterisk asterisk -rvvv

# Inside the CLI:
#   pjsip show endpoints
#   pjsip show contacts
#   ari show apps
#   core show channels
```

## Troubleshooting

### Zoiper can't register

- Verify Asterisk is listening: `docker exec asterisk asterisk -rx 'pjsip show transports'`.
- Make sure host port 5060/udp is not already taken (`sudo ss -ulpn | grep 5060`).
- Confirm credentials in `asterisk/pjsip.conf` match the Zoiper account.

### Call connects but no audio (one-way or no-way)

- Confirm the RTP port range is exposed: `docker port asterisk | grep 1000`.
- Confirm your softphone is using G.711 μ-law (`PCMU`). Other codecs are
  disallowed in `pjsip.conf`.
- Hit `http://localhost:8000/health` while on the call: `asterisk_rtp_addr`
  should be populated. If it stays null, Asterisk RTP is not reaching the
  bridge container.

### Bridge logs say `media= got an unexpected keyword argument`

- You are on an older `google-genai` SDK. Rebuild: `docker compose build --no-cache bridge`.

### Gemini connects then immediately disconnects, or `1008 ... not found for API version v1beta`

This means the `GEMINI_MODEL` value isn't valid for the AI Studio (api-key)
Live API. Use one of:

- `gemini-3.1-flash-live-preview` (default, recommended)
- `gemini-2.5-flash-native-audio-preview-12-2025`

Do **not** use `gemini-2.0-flash-live-preview-04-09` (Vertex AI only) or
`gemini-2.0-flash-live-001` (shut down Dec 9, 2025).

### "A call is already active" warning

- This demo is single-call by design. Hang up the existing call before
  starting a new one, or extend `CallState` per-channel for multi-call.

## File layout

```
.
├── docker-compose.yml
├── .env.example
├── asterisk/
│   ├── asterisk.conf
│   ├── modules.conf
│   ├── logger.conf
│   ├── http.conf
│   ├── ari.conf
│   ├── rtp.conf
│   ├── pjsip.conf
│   └── extensions.conf
└── bridge/
    ├── Dockerfile
    ├── requirements.txt
    └── app/
        ├── __init__.py
        └── main.py
```
