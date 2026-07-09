import json
import ipaddress
import re
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import soundcard as sc


HOST = "0.0.0.0"
PORT = 8765
SAMPLE_RATE = 48000
FRAME_SIZE = 2048
FFT_SIZE = 4096
BANDS = 128
FPS_LIMIT = 30


state_lock = threading.Lock()
state = {
    "status": "starting",
    "device": "",
    "bars": [0.0] * BANDS,
    "rms": 0.0,
    "peak": 0.0,
    "fps": 0.0,
    "time": time.time(),
}


INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>DeskWave</title>
  <style>
    html, body {
      margin: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      background: #000;
      color: #e9fffb;
      font-family: Arial, Helvetica, sans-serif;
      touch-action: manipulation;
      user-select: none;
    }
    canvas {
      display: block;
      width: 100vw;
      height: 100vh;
      background: #000;
    }
    #badge {
      position: fixed;
      right: 10px;
      bottom: 8px;
      padding: 5px 8px;
      border: 1px solid rgba(220, 255, 248, 0.18);
      border-radius: 4px;
      background: rgba(0, 0, 0, 0.42);
      color: rgba(233, 255, 251, 0.7);
      font-size: 11px;
      line-height: 1;
      opacity: 0;
      transition: opacity 160ms ease;
      pointer-events: none;
    }
    body.show #badge {
      opacity: 1;
    }
  </style>
</head>
<body>
  <canvas id="viz"></canvas>
  <div id="badge">connecting</div>
  <script>
    const canvas = document.getElementById("viz");
    const ctx = canvas.getContext("2d");
    const badge = document.getElementById("badge");
    const palettes = [
      { name: "mint pulse", bg: "#020506", a: "#58ffd9", b: "#12e883", c: "#ff3b68", line: "#e8fffb" },
      { name: "club glass", bg: "#050208", a: "#ff4fd8", b: "#5df3ff", c: "#fff06b", line: "#ffffff" },
      { name: "laser amber", bg: "#040403", a: "#ffdc62", b: "#ff5a2d", c: "#3fffe0", line: "#fff7dc" },
      { name: "deep ice", bg: "#01040a", a: "#65a7ff", b: "#59ffd1", c: "#ff6e9f", line: "#f6fbff" }
    ];
    let dpr = 1;
    let bars = new Array(128).fill(0);
    let target = new Array(128).fill(0);
    let particles = [];
    let lastPacket = 0;
    let theme = Number(localStorage.getItem("phoneSpectrumTheme") || 0) % palettes.length;
    let badgeTimer = null;
    let bassEnergy = 0;
    let midEnergy = 0;
    let trebleEnergy = 0;

    function resize() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.floor(innerWidth * dpr);
      canvas.height = Math.floor(innerHeight * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      makeParticles();
    }

    function makeParticles() {
      const count = Math.max(36, Math.min(95, Math.floor(innerWidth * innerHeight / 9000)));
      particles = Array.from({ length: count }, () => ({
        x: Math.random() * innerWidth,
        y: Math.random() * innerHeight,
        vx: (Math.random() - 0.5) * 0.16,
        vy: -0.06 - Math.random() * 0.18,
        r: 0.6 + Math.random() * 1.7,
        phase: Math.random() * Math.PI * 2
      }));
    }

    function flash(text) {
      badge.textContent = text;
      document.body.classList.add("show");
      clearTimeout(badgeTimer);
      badgeTimer = setTimeout(() => document.body.classList.remove("show"), 1200);
    }

    function switchTheme() {
      theme = (theme + 1) % palettes.length;
      localStorage.setItem("phoneSpectrumTheme", String(theme));
      flash(palettes[theme].name);
    }

    function openFullscreen() {
      const el = document.documentElement;
      if (el.requestFullscreen) el.requestFullscreen().catch(() => {});
    }

    function color(hex, alpha) {
      const n = Number.parseInt(hex.slice(1), 16);
      const r = (n >> 16) & 255;
      const g = (n >> 8) & 255;
      const b = n & 255;
      return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }

    function mean(values, start, end) {
      let sum = 0;
      for (let i = start; i < end; i++) sum += values[i] || 0;
      return sum / Math.max(1, end - start);
    }

    function drawBackground(w, h, p, alive) {
      ctx.fillStyle = p.bg;
      ctx.fillRect(0, 0, w, h);

      const pulse = alive ? Math.min(1, bassEnergy * 1.45) : 0.02;
      const glow = ctx.createRadialGradient(w / 2, h * 0.88, 0, w / 2, h * 0.88, Math.max(w, h) * 0.95);
      glow.addColorStop(0, color(p.b, 0.16 + pulse * 0.16));
      glow.addColorStop(0.34, color(p.a, 0.08 + pulse * 0.07));
      glow.addColorStop(0.72, color(p.c, 0.025));
      glow.addColorStop(1, "rgba(0, 0, 0, 0)");
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, w, h);

      ctx.save();
      ctx.globalAlpha = 0.16;
      ctx.strokeStyle = color(p.line, 0.45);
      ctx.lineWidth = 1;
      for (let y = h * 0.18; y < h; y += h * 0.16) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }
      for (let x = 0; x < w; x += Math.max(32, w / 18)) {
        ctx.beginPath();
        ctx.moveTo(x, h * 0.14);
        ctx.lineTo(x, h);
        ctx.stroke();
      }
      ctx.restore();

      ctx.save();
      ctx.globalAlpha = 0.18;
      for (let y = 0; y < h; y += 3) {
        ctx.fillStyle = "rgba(255, 255, 255, 0.12)";
        ctx.fillRect(0, y, w, 1);
      }
      ctx.restore();
    }

    function drawParticles(w, h, p, alive) {
      const speed = 0.35 + bassEnergy * 1.8;
      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      for (const dot of particles) {
        dot.phase += 0.025 + trebleEnergy * 0.05;
        dot.x += dot.vx * speed + Math.sin(dot.phase) * 0.05;
        dot.y += dot.vy * speed;
        if (dot.y < -8) {
          dot.y = h + 8;
          dot.x = Math.random() * w;
        }
        if (dot.x < -8) dot.x = w + 8;
        if (dot.x > w + 8) dot.x = -8;

        const alpha = alive ? 0.12 + trebleEnergy * 0.5 : 0.06;
        ctx.fillStyle = color(p.a, alpha);
        ctx.beginPath();
        ctx.arc(dot.x, dot.y, dot.r + bassEnergy * 2.2, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    }

    function drawWaveLine(w, h, p, alive) {
      const n = bars.length;
      const top = h * 0.18;
      const amp = h * (0.035 + midEnergy * 0.08);
      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      ctx.lineWidth = 1.2;
      ctx.shadowBlur = 16;
      ctx.shadowColor = p.a;
      ctx.strokeStyle = color(p.line, alive ? 0.82 : 0.24);
      ctx.beginPath();
      for (let i = 0; i < n; i++) {
        const x = (i / (n - 1)) * w;
        const curve = Math.sin(i * 0.34 + performance.now() * 0.004) * amp * 0.35;
        const y = top + curve + (0.5 - bars[i]) * amp;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      ctx.restore();
    }

    function drawBars(w, h, p, alive) {
      const n = bars.length;
      const pitch = w / n;
      const barW = Math.max(1.5, Math.min(5, pitch * 0.45));
      const base = h * 0.86;
      const maxH = h * 0.62;
      const capH = Math.max(1.5, h * 0.012);

      const fill = ctx.createLinearGradient(0, base - maxH, 0, base);
      fill.addColorStop(0.00, p.line);
      fill.addColorStop(0.16, p.a);
      fill.addColorStop(0.56, p.b);
      fill.addColorStop(1.00, p.c);

      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      ctx.shadowBlur = 18 + bassEnergy * 26;
      ctx.shadowColor = p.b;
      ctx.fillStyle = fill;
      for (let i = 0; i < n; i++) {
        const v = alive ? Math.max(0.012, Math.min(1, bars[i])) : 0.01;
        const shaped = Math.pow(v, 0.74);
        const bh = shaped * maxH;
        const x = i * pitch + (pitch - barW) / 2;
        ctx.fillRect(x, base - bh, barW, bh);

        ctx.globalAlpha = 0.52 + shaped * 0.36;
        ctx.fillStyle = p.line;
        ctx.fillRect(x, base - bh - capH * 0.72, barW, capH);
        ctx.globalAlpha = 1;
        ctx.fillStyle = fill;
      }
      ctx.restore();
    }

    function drawBloomRings(w, h, p, alive) {
      const pulse = alive ? bassEnergy : 0.02;
      const cx = w * 0.5;
      const cy = h * 0.64;
      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      for (let i = 0; i < 3; i++) {
        const radius = (0.16 + i * 0.12 + pulse * 0.16) * Math.min(w, h);
        ctx.strokeStyle = color(i === 0 ? p.c : p.a, 0.16 - i * 0.035 + pulse * 0.09);
        ctx.lineWidth = 1.1 + pulse * 3;
        ctx.beginPath();
        ctx.ellipse(cx, cy, radius * 1.9, radius * 0.34, 0, 0, Math.PI * 2);
        ctx.stroke();
      }
      ctx.restore();
    }

    function draw() {
      const w = innerWidth;
      const h = innerHeight;
      const now = performance.now();
      const alive = now - lastPacket < 1800;

      for (let i = 0; i < bars.length; i++) {
        const rise = target[i] > bars[i] ? 0.42 : 0.1;
        bars[i] += (target[i] - bars[i]) * rise;
      }
      bassEnergy += (mean(bars, 0, Math.floor(bars.length * 0.13)) - bassEnergy) * 0.18;
      midEnergy += (mean(bars, Math.floor(bars.length * 0.18), Math.floor(bars.length * 0.54)) - midEnergy) * 0.14;
      trebleEnergy += (mean(bars, Math.floor(bars.length * 0.6), bars.length) - trebleEnergy) * 0.16;

      const p = palettes[theme];
      drawBackground(w, h, p, alive);
      drawParticles(w, h, p, alive);
      drawBloomRings(w, h, p, alive);
      drawBars(w, h, p, alive);

      requestAnimationFrame(draw);
    }

    function connect() {
      const es = new EventSource("/events");
      es.onopen = () => flash("online");
      es.onmessage = (event) => {
        const packet = JSON.parse(event.data);
        target = packet.bars || target;
        lastPacket = performance.now();
      };
      es.onerror = () => {
        flash("reconnecting");
        es.close();
        setTimeout(connect, 900);
      };
    }

    window.addEventListener("resize", resize);
    window.addEventListener("orientationchange", () => setTimeout(resize, 250));
    document.body.addEventListener("click", () => {
      openFullscreen();
      switchTheme();
    });
    resize();
    flash(palettes[theme].name);
    connect();
    draw();
  </script>
</body>
</html>
"""


def local_ip():
    blocked_adapter_words = (
        "mihomo",
        "clash",
        "verge",
        "tun",
        "tap",
        "vpn",
        "vmware",
        "virtualbox",
        "hyper-v",
        "wsl",
        "docker",
        "zerotier",
        "tailscale",
        "wireguard",
    )

    def usable_lan_ip(ip):
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if address.is_loopback or address.is_link_local or address.is_multicast:
            return False
        if address in ipaddress.ip_network("198.18.0.0/15"):
            return False
        return address.is_private

    def score_candidate(adapter_name, ip, has_gateway):
        name = adapter_name.lower()
        if any(word in name for word in blocked_adapter_words):
            return -100

        score = 0
        if has_gateway:
            score += 50
        else:
            score -= 20

        if ip.startswith("192.168."):
            score += 30
        elif ip.startswith("10."):
            score += 20
        else:
            try:
                address = ipaddress.ip_address(ip)
                if address in ipaddress.ip_network("172.16.0.0/12"):
                    score += 20
            except ValueError:
                pass
        return score

    try:
        output = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "Get-NetIPConfiguration | "
                    "Where-Object { $_.IPv4Address -and $_.IPv4DefaultGateway } | "
                    "ForEach-Object { "
                    "'{0}|{1}' -f $_.InterfaceAlias, $_.IPv4Address.IPAddress "
                    "}"
                ),
            ],
            text=True,
            encoding="utf-8",
            errors="ignore",
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        candidates = []
        for line in output.splitlines():
            if "|" not in line:
                continue
            adapter_name, ip = [part.strip() for part in line.split("|", 1)]
            if usable_lan_ip(ip):
                candidates.append((score_candidate(adapter_name, ip, True), ip))
        if candidates:
            candidates.sort(reverse=True)
            if candidates[0][0] > -100:
                return candidates[0][1]
    except (OSError, subprocess.SubprocessError):
        pass

    try:
        output = subprocess.check_output(
            ["ipconfig"],
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=3,
        )
        candidates = []
        for block in re.split(r"\n\s*\n", output):
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if not lines:
                continue

            adapter_name = lines[0].rstrip(":")
            ipv4_matches = re.findall(r"IPv4[^:\n]*:\s*([0-9]+(?:\.[0-9]+){3})", block)
            gateway_match = re.search(r"(?:Gateway|网关)[^:\n]*:\s*([0-9]+(?:\.[0-9]+){3})", block)
            has_gateway = gateway_match is not None

            for ip in ipv4_matches:
                if usable_lan_ip(ip):
                    candidates.append((score_candidate(adapter_name, ip, has_gateway), ip))

        if candidates:
            candidates.sort(reverse=True)
            return candidates[0][1]
    except (OSError, subprocess.SubprocessError):
        pass

    try:
        hostname = socket.gethostname()
        candidates = socket.getaddrinfo(hostname, None, socket.AF_INET)
        for item in candidates:
            ip = item[4][0]
            if usable_lan_ip(ip):
                return ip
    except OSError:
        pass
    return "127.0.0.1"


def make_band_edges():
    low = 35
    high = 16000
    edges = np.geomspace(low, high, BANDS + 1)
    freqs = np.fft.rfftfreq(FFT_SIZE, 1 / SAMPLE_RATE)
    bins = np.searchsorted(freqs, edges)
    bins = np.clip(bins, 1, len(freqs) - 1)
    return [(int(bins[i]), max(int(bins[i + 1]), int(bins[i]) + 1)) for i in range(BANDS)]


def publish(**kwargs):
    with state_lock:
        state.update(kwargs)
        state["time"] = time.time()


def audio_worker():
    band_edges = make_band_edges()
    smooth = np.zeros(BANDS, dtype=np.float32)
    auto_gain = 0.25
    frame_count = 0
    fps_started = time.perf_counter()

    try:
        speaker = sc.default_speaker()
        loopback = sc.get_microphone(speaker.name, include_loopback=True)
        publish(status="running", device=speaker.name)

        with loopback.recorder(
            samplerate=SAMPLE_RATE,
            channels=speaker.channels,
            blocksize=FRAME_SIZE * 4,
        ) as recorder:
            while True:
                audio = recorder.record(numframes=FRAME_SIZE)
                if audio.size == 0:
                    continue

                mono = audio.mean(axis=1).astype(np.float32, copy=False)
                mono = mono - float(np.mean(mono))
                rms = float(np.sqrt(np.mean(np.square(mono))) + 1e-12)
                peak = float(np.max(np.abs(mono)) + 1e-12)

                window = np.hanning(len(mono)).astype(np.float32)
                spectrum = np.abs(np.fft.rfft(mono * window, FFT_SIZE))
                levels = np.array(
                    [np.mean(spectrum[start:end]) for start, end in band_edges],
                    dtype=np.float32,
                )
                levels = np.log1p(levels * 45.0)
                current = float(np.percentile(levels, 96))
                auto_gain = max(current, auto_gain * 0.985)
                target = np.clip(levels / (auto_gain + 1e-6), 0.0, 1.0)
                target = np.power(target, 0.78)

                attack = target > smooth
                smooth[attack] = smooth[attack] * 0.52 + target[attack] * 0.48
                smooth[~attack] = smooth[~attack] * 0.84 + target[~attack] * 0.16

                frame_count += 1
                elapsed = time.perf_counter() - fps_started
                fps = frame_count / elapsed if elapsed > 0 else 0.0

                publish(
                    status="running",
                    bars=[round(float(x), 4) for x in smooth],
                    rms=round(rms, 6),
                    peak=round(peak, 6),
                    fps=round(fps, 1),
                )
    except Exception as exc:
        publish(status="error", device=str(exc))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def send_text(self, status, content, content_type):
        data = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            self.send_text(200, INDEX_HTML, "text/html; charset=utf-8")
            return

        if self.path == "/health":
            with state_lock:
                payload = json.dumps(state, ensure_ascii=False)
            self.send_text(200, payload, "application/json; charset=utf-8")
            return

        if self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            delay = 1.0 / FPS_LIMIT
            while True:
                try:
                    with state_lock:
                        payload = json.dumps(state, ensure_ascii=False)
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(delay)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
            return

        self.send_text(404, "not found", "text/plain; charset=utf-8")


def main():
    threading.Thread(target=audio_worker, daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    ip = local_ip()
    print("DeskWave is running.")
    print(f"Computer: http://127.0.0.1:{PORT}")
    print(f"Phone:    http://{ip}:{PORT}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
