# 🪲 Kabuto

**A light little keyboard pad.** Six keys, Bluetooth, and macros you set up from
your phone. No cables to your computer, no drivers, no reflashing to change a key.

## ✨ What it does

- ⌨️ **Pairs like any Bluetooth keyboard:** Windows, macOS, Linux, iOS, Android
- 🎬 **Record & replay:** capture your keys with their real timing, then play them back
- 🎲 **Dynamic patterns:** fresh, never-quite-the-same sequences: your keys, HP & Mana timers, skills, presets
- 🗂️ **Layers & modes:** tap, toggle or hold, on up to 8 layers
- 📱 **Phone-friendly editor:** built into the pad, no app to install
- 📊 **Live HP, Mana & XP:** a tiny PC script reads your bars; see XP/hour and drink when low
- 🗺️ **Screen aware:** stops on death or disconnect, keeps off map edges, faces mobs
- 🏠 **On your Wi-Fi too:** open `kabuto.local` from any device, PIN-protected
- 🔄 **Updates from GitHub:** tap Install, done; roll back any time
- 💾 **Your patterns stay put:** reflashing never wipes them

## 🧰 You'll need

- An **ESP32-S3** board (e.g. DevKitC-1, ~£10–18)
- **6 switches** wired as a 2 × 3 matrix (pins in `src/config.h`)

## 🚀 Setup

```bash
pip install platformio
pio run -t upload
```

1. 📶 Join the **Kabuto-Setup** Wi-Fi (password `macropad123`)
2. 🌐 Open **http://192.168.4.1** and set up your keys
3. 🔵 Pair **Kabuto** from your computer's Bluetooth settings
4. 🎉 Press a key

Hold **BOOT** for 3 s to forget paired devices.

🎮 **Game laptop?** Plug the pad in by USB, `pip install mss pynput pyserial`
and run `python tools/screen_stats.py` for live HP, Mana, XP and screen
awareness. No Wi-Fi or PIN needed over USB.

## 📚 More

- 📖 [Guide](docs/GUIDE.md): wiring, recordings, patterns, backups, updates
- 📝 [Changelog](CHANGELOG.md): what's new
- 🤖 [AGENTS.md](AGENTS.md): how the code fits together, for contributors and AI helpers
