# DeskWave

DeskWave turns a spare phone into a Wi-Fi audio spectrum display for your desktop.

It captures the audio currently playing on a Windows PC through WASAPI loopback, serves a lightweight local web visualizer, and lets any phone on the same Wi-Fi show the spectrum in real time.

Preview screenshot location: `screenshots/desk-wave-preview.png`

Add your own screenshot there before publishing, then insert it near the top of this README:

```markdown
![DeskWave preview](screenshots/desk-wave-preview.png)
```

## Features

- Real-time system audio spectrum from a Windows PC.
- Phone display through a normal mobile browser.
- No phone microphone required.
- 128 frequency bands.
- Full-width thin-bar visualizer.
- Multiple color themes, switchable by tapping the page.
- Fullscreen-friendly layout for landscape phones.
- Simple Python server with minimal dependencies.

## How It Works

```text
PC music/video playback
        |
        v
Windows WASAPI loopback capture
        |
        v
Python spectrum server
        |
        v
Wi-Fi / local network
        |
        v
Phone browser visualizer
```

## Requirements

- Windows 10 or Windows 11.
- Python 3.8 or newer.
- A default audio output device on the PC.
- Phone and PC connected to the same Wi-Fi or LAN.

The PC does not need external speakers. A headset, Bluetooth headphones, monitor HDMI/DP audio, or a virtual audio device is enough. Windows loopback capture needs a default playback device to exist.

## Installation

Clone the repository:

```powershell
git clone https://github.com/your-name/deskwave.git
cd deskwave
```

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

If you use a specific Conda environment, run it with that Python:

```powershell
& 'C:\Tools\anaconda3\envs\pytorch\python.exe' -m pip install -r requirements.txt
```

## Usage

Start the server:

```powershell
python server.py
```

Or with your Conda Python:

```powershell
& 'C:\Tools\anaconda3\envs\pytorch\python.exe' server.py
```

The terminal will print two URLs:

```text
Computer: http://127.0.0.1:8765
Phone:    http://192.168.x.x:8765
```

Open the `Phone` URL on your phone browser. Put the phone in landscape mode and place it under your monitor.

Tap the page to request fullscreen and switch visual themes.

## Screenshot

Recommended screenshot location:

```text
screenshots/desk-wave-preview.png
```

For a GitHub README, use a wide landscape screenshot from your phone or desktop browser. A 16:9 or long phone-screen crop works well.

## Troubleshooting

### The phone cannot open the page

- Make sure the phone and PC are on the same Wi-Fi.
- Allow Python through Windows Firewall when prompted.
- Try the PC page first: `http://127.0.0.1:8765`.
- Some guest, school, or office Wi-Fi networks block device-to-device access.

### The page opens, but there is no spectrum

Open this on the PC:

```text
http://127.0.0.1:8765/health
```

Check the `status` field:

- `running`: audio capture is working. Try increasing the player volume.
- `error`: usually means no default playback device is available, or the audio device is locked by another application.

### The browser still shows an old design

Force-refresh the page or add a version query:

```text
http://192.168.x.x:8765/?v=2
```

### Port 8765 is already in use

Edit `server.py`:

```python
PORT = 8765
```

Change it to another port, for example:

```python
PORT = 8877
```

## Project Structure

```text
.
├── server.py
├── requirements.txt
├── screenshots/
│   └── .gitkeep
├── LICENSE
└── README.md
```

## License

MIT License. See [LICENSE](LICENSE).
