# OmniRoute

**Dynamic Edge-to-Cloud AI Router** — Intelligent middleware that routes AI inference requests between cloud APIs and local edge models in real time, optimizing for cost, speed, and reliability.

## What Is It?

OmniRoute is a developer middleware that sits between your application and multiple AI backends. Instead of hardcoding whether to use a cloud API or a local model, OmniRoute dynamically decides the optimal route for every request based on live system telemetry.

```
Your App  -->  OmniRoute  -->  Cloud (Groq API)
                           -->  Edge  (Local MLX / YOLOv8)
```

## Key Features

- **Unified `/v1/process` endpoint** — single API for both text generation and object detection
- **Real-time telemetry** — monitors ping latency, battery state, and RAM availability every 2 seconds
- **Intelligent routing engine** — priority-based decision tree with configurable thresholds
- **Automatic cloud-to-edge fallback** — if cloud fails, transparently retries on local models
- **SSE streaming** — real-time token-by-token text generation via `/v1/stream`
- **Cost estimation** — tracks money saved by routing to edge
- **Force route override** — manual toggle for demo/testing purposes
- **Live dashboard** — telemetry sparklines, latency charts, routing logs

## Routing Logic

Decisions follow a priority-ordered waterfall:

| Priority | Condition | Route | Rationale |
|----------|-----------|-------|-----------|
| 1 | Manual override set | Forced route | User/demo toggle |
| 2 | Device offline | **Edge** | No network available |
| 3 | Ping > 150ms | **Edge** | Cloud would be too slow |
| 4 | Battery < 20% and unplugged | **Cloud** | Preserve device battery |
| 5 | Available RAM < 2GB | **Cloud** | Not enough memory for local models |
| 6 | Ping < 50ms | **Cloud** | Fast network, cloud gives better quality |
| 7 | Ping 50-150ms (gray zone) | **Cloud** | Prefer cloud, edge fallback on failure |

All thresholds are configurable via environment variables.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + Uvicorn |
| Cloud Text | Groq API (Llama 3.3 70B) |
| Cloud Vision | Groq API (Llama 4 Scout 17B) |
| Edge Text | Apple MLX (Llama 3.2 1B 4-bit) |
| Edge Vision | YOLOv8 Nano + OpenCV |
| Telemetry | psutil + ICMP ping |
| Frontend | Vanilla HTML/CSS/JS |

## Project Structure

```
OmniRoute/
├── backend/
│   ├── app.py              # FastAPI app, endpoints, lifecycle, fallback logic
│   ├── router.py           # Routing decision engine
│   ├── telemetry.py        # Background telemetry daemon (ping, battery, RAM)
│   ├── schemas.py          # Pydantic request/response models
│   └── inference/
│       ├── cloud_text.py   # Groq LLM text generation
│       ├── cloud_vision.py # Groq vision object detection
│       ├── edge_text.py    # MLX local LLM on Apple Silicon
│       └── edge_vision.py  # YOLOv8n local object detection
├── frontend/
│   ├── index.html          # Dashboard UI
│   ├── style.css           # Styling
│   └── app.js              # Frontend logic, telemetry polling, SSE, charts
├── .env                    # API keys (GROQ_API_KEY)
├── requirements.txt        # Python dependencies
└── yolov8n.pt              # YOLOv8 Nano weights
```

## Getting Started

### Prerequisites

- **Python 3.11-3.13** (3.14 has compatibility issues with pydantic-core)
- **macOS with Apple Silicon** (required for MLX edge inference)
- **Groq API key** — get one at [console.groq.com](https://console.groq.com)

### Installation

```bash
# Clone the repo
git clone https://github.com/your-username/OmniRoute.git
cd OmniRoute

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set your Groq API key
echo "GROQ_API_KEY=your_key_here" > .env
```

### Run

```bash
uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload
```

Open [http://localhost:8000](http://localhost:8000) to access the dashboard.

## API Reference

### POST /v1/process

Unified inference endpoint. Routes automatically based on telemetry.

**Request:**

```json
{
  "type": "text",
  "payload": "Explain quantum computing in simple terms",
  "force_route": null
}
```

**Response:**

```json
{
  "success": true,
  "type": "text",
  "route": "cloud",
  "reasoning": "Low latency (12ms < 50ms); Device is plugged in",
  "result": "Quantum computing uses quantum bits...",
  "latency_ms": 847.3,
  "cost_saved_usd": 0.0
}
```

**Fields:**

| Field | Description |
|-------|-------------|
| `type` | `"text"` or `"vision"` |
| `payload` | Text prompt or base64-encoded image |
| `force_route` | `null` (auto), `"cloud"`, or `"edge"` |

### POST /v1/stream

SSE streaming endpoint for text generation (real-time token delivery).

### GET /v1/telemetry

Returns the current telemetry snapshot and routing decision.

### GET /v1/stats

Returns cost estimation, request counts, and latency history.

### POST /v1/force-route?route=auto|cloud|edge

Sets a global route override for demo purposes.

### GET /v1/health

Health check. Returns status, version, and uptime.

## Configuration

All thresholds can be tuned via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `GROQ_API_KEY` | required | Groq API key for cloud inference |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Cloud text model |
| `GROQ_VISION_MODEL` | `meta-llama/llama-4-scout-17b-16e-instruct` | Cloud vision model |
| `MLX_MODEL` | `mlx-community/Llama-3.2-1B-Instruct-4bit` | Edge text model (Apple MLX) |
| `PING_CLOUD_THRESHOLD` | `50` | Below this ping (ms), route to cloud |
| `PING_EDGE_THRESHOLD` | `150` | Above this ping (ms), route to edge |
| `BATTERY_LOW_THRESHOLD` | `20` | Below this battery % (unplugged), route to cloud |
| `RAM_LOW_THRESHOLD` | `2.0` | Below this available RAM (GB), route to cloud |

## How It Works

1. **Request arrives** at `/v1/process` or `/v1/stream`
2. **Telemetry engine** provides the latest system snapshot (polled every 2s)
3. **Router** evaluates the snapshot against thresholds
4. **Inference** is dispatched to the chosen backend
5. If cloud fails, **automatic edge fallback** kicks in
6. **Response** includes the route taken, reasoning, latency, and cost savings

## License

MIT
