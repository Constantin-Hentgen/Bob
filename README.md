<p align="center">
  <img src="assets/bob.png" alt="Bob, the trail-running robot" width="160">
</p>

<h1 align="center">Bob</h1>

<p align="center">
  A self-hosted AI running coach on Telegram: plans your sessions in your own calendar, knows your training data and the weather, tracks what you eat, and learns your preferences as you chat.
</p>

<p align="center">
  <a href="https://github.com/Constantin-Hentgen/Bob/actions/workflows/ci.yml"><img src="https://github.com/Constantin-Hentgen/Bob/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/Constantin-Hentgen/Bob/releases/latest"><img src="https://img.shields.io/github/v/release/Constantin-Hentgen/Bob" alt="Latest release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/Constantin-Hentgen/Bob" alt="MIT license"></a>
  <img src="https://img.shields.io/badge/python-3.12%2B-blue" alt="Python 3.12+">
</p>

```text
You ▸ Décale ma sortie longue de samedi à dimanche matin, il va pleuvoir
Bob ▸ C'est calé dimanche 9h, il fera sec 👌
Bob ▸ Vas-y tranquille, t'as encore de la fatigue dans les jambes 😮‍💨
```

> [!NOTE]
> The coach speaks **French** by default, or **English** with `BOT_LANGUAGE=en` ([Configuration](https://github.com/Constantin-Hentgen/Bob/wiki/Configuration#bot-language)).

## Features

- 📅 **Plans in your CalDAV calendar** (Radicale, Nextcloud, Baïkal, Fastmail, iCloud…), backward from your goals; every write is checked on the server
- 🏃 **Uses your Dreeve data**: load, whole run history, a debrief and check-in after each run
- 🌧️ **Weather alerts** per session and training place
- 🥗 **Meals and nutrition**: meal ideas, shopping checklist, food log computed from the Ciqual table
- 🗺️ **Running loops** around home or work, as maps and GPX files
- 🎙️ **Voice notes** transcribed locally, 🧠 **memory** of your preferences, 🌍 French or English, single-user and self-hosted
- 🤖 **Bring your own model**: Anthropic, OpenAI, DeepSeek, Mistral, OpenRouter, Groq, Gemini, or a local Ollama / LM Studio / vLLM server

## Installation

Requirements: Docker with Compose, an LLM that can call tools (an API key from Anthropic, OpenAI, DeepSeek, Mistral… or a local server), a Telegram bot from [@BotFather](https://t.me/BotFather) and a calendar dedicated to running on any CalDAV server. See [Compatibility](https://github.com/Constantin-Hentgen/Bob/wiki/Compatibility).

1. Get the code and create your configuration:
   ```bash
   git clone https://github.com/Constantin-Hentgen/Bob.git && cd Bob
   cp .env.example .env
   ```
2. Fill in `.env`: at least `LLM_PROVIDER` + `LLM_API_KEY` (+ `LLM_MODEL` for most providers), `TELEGRAM_BOT_TOKEN`, `CALDAV_URL`, `CALDAV_USER`, `CALDAV_PASS`, and `BOT_LANGUAGE=en` for English ([all options](https://github.com/Constantin-Hentgen/Bob/wiki/Configuration)).
3. Build and start it:
   ```bash
   docker compose up -d --build
   ```

## Quickstart

Message your bot: while `TELEGRAM_CHAT_ID` is empty it only replies with your chat ID. Put that ID in `.env`, run `docker compose up -d` again, then introduce yourself to the coach (« Semi de Paris le 7 mars, je vise 1h45 ») and try `/help`. Details in [Getting Started](https://github.com/Constantin-Hentgen/Bob/wiki/Getting-Started).

## Documentation

The **[wiki](https://github.com/Constantin-Hentgen/Bob/wiki)** covers everything after installation:

- [Configuration](https://github.com/Constantin-Hentgen/Bob/wiki/Configuration): every environment variable, with its type and default
- [Deployment](https://github.com/Constantin-Hentgen/Bob/wiki/Deployment): Docker Compose, Portainer, updates and backups
- [Commands](https://github.com/Constantin-Hentgen/Bob/wiki/Commands) and [Coaching](https://github.com/Constantin-Hentgen/Bob/wiki/Coaching): what you can ask and what the coach does on its own
- [Weather Alerts](https://github.com/Constantin-Hentgen/Bob/wiki/Weather-Alerts), [Meals and Nutrition](https://github.com/Constantin-Hentgen/Bob/wiki/Meals-and-Nutrition), [Running Routes](https://github.com/Constantin-Hentgen/Bob/wiki/Running-Routes)
- [Error Messages](https://github.com/Constantin-Hentgen/Bob/wiki/Error-Messages) and [Known Limitations](https://github.com/Constantin-Hentgen/Bob/wiki/Known-Limitations): when something goes wrong
- [How It Works](https://github.com/Constantin-Hentgen/Bob/wiki/How-It-Works), [Integrations](https://github.com/Constantin-Hentgen/Bob/wiki/Integrations), [Privacy and Safeguards](https://github.com/Constantin-Hentgen/Bob/wiki/Privacy-and-Safeguards), [Contributing](https://github.com/Constantin-Hentgen/Bob/wiki/Contributing)

Release notes: [CHANGELOG.md](CHANGELOG.md) and [Releases](https://github.com/Constantin-Hentgen/Bob/releases).

## License

[MIT](LICENSE). Nutrition data: Anses. 2020. Table de composition nutritionnelle des aliments Ciqual, [Licence Ouverte](https://www.etalab.gouv.fr/licence-ouverte-open-licence). Map data © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors.
