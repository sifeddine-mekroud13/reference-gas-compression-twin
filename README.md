# Reference Gas Compression Twin

A digital twin of a gas compressor, built entirely with open-source tools and running on one computer.

The plant is simulated: a fictional site ("Unit 100") where a 7 MW compressor pushes natural gas
from 29 to 76 bar into a pipeline. Everything around it is built the way a real plant would do it:
a control system, data collection, cybersecurity zones, a twin that tracks the machine's health,
and a web dashboard.

## What it does

- **Simulates the plant.** A physics model of the compressor, cooler and scrubber, including surge
  (a dangerous flow reversal), wear over time, and faulty sensors.
- **Controls it.** Pressure, speed and anti-surge control, trips and alarms, like a control room.
- **Collects the data.** Sensor readings go over OPC UA (the industrial standard, encrypted) into a
  time-series database. Nothing is lost if the database goes down.
- **Tracks machine health.** The twin compares how the compressor runs with how it should run,
  estimates wear, predicts when a wash is worth doing, and answers "what if" questions.
- **Keeps the plant secure.** The system is split into separate network zones. Office users can see
  plant data through a one-way link but can never send anything back.
- **Shows it all in a dashboard.** 3D view, process diagram, live values, alarms, trends and
  maintenance history, with a login and role-based access.
- **Detects problems early.** Machine-learning models spot abnormal behaviour and diagnose
  vibration faults.

## Run it

You need [Docker](https://docs.docker.com/get-docker/).

```bash
cp .env.example .env      # then replace each change-me value with your own password
docker compose up -d --build --wait
```

Open http://localhost:8081 and log in as `engineer1` or `operator1`, using the
`RGPF_DEMO_PASSWORD` you set in `.env`. Stop it with `docker compose stop`.

Everything runs on your own machine. "localhost" means this computer, not the internet.

## What's in the repo

| Folder | Contents |
|---|---|
| `engineering/` | The plant's design data: equipment, sensors, alarms |
| `libs/` | Physics, simulator and twin calculations |
| `services/` | The running programs: control system server, data collector, twin, API |
| `ui/` | The web dashboard |
| `analytics/` | Anomaly detection and fault diagnosis |
| `infra/` | Network, firewall and database setup |
| `docs/` | Design notes, decisions and test results |

## Limits

All data is simulated. The models have not been checked against a real machine, and nothing here
is certified against any standard. See [docs/verification.md](docs/verification.md) for what was
tested and what wasn't.

## License

Apache-2.0
