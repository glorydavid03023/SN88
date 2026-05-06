# SN88 Tao/Alpha Strategy Bot

This bot generates a daily Tao/Alpha strategy for **Bittensor SN88 Investing** and writes it to:

```bash
$INVESTING_DIR/Investing/strat/$HOTKEY_SS58
```

Then it touches the file so the SN88 miner detects the timestamp and auto-resubmits.

Best daily run time for Tao/Alpha is **23:50 UTC**, because SN88 Tao/Alpha daily scoring is around **00:00 UTC**.

---

## What the bot does

```text
Taostats subnet data
      ↓
score every subnet
      ↓
filter weak/illiquid/risky subnets
      ↓
pick top N
      ↓
calculate weights with max-position cap
      ↓
write SN88 strategy file
      ↓
touch file to trigger miner resubmit
```

The output strategy format is:

```python
{
    "_": 0,
    51: 0.2000,
    64: 0.1800,
    44: 0.1500
}
```

`"_": 0` means Tao/Alpha strategy.

---

## Important note about Taostats endpoint

Taostats docs confirm that an API key is required and that API requests use an `authorization` header. The docs also describe subnet page metrics such as price, 1H, 24H, 1W, flow, volume, liquidity, emission, and market cap.

Because the exact Taostats subnet-list API endpoint can differ by account/API version, this bot uses:

```env
TAOSTATS_SUBNETS_ENDPOINT=/api/dtao/subnet/latest/v1
```

If your key/account gives a different endpoint in Taostats docs, change that value in `.env`.

The bot also tries several fallback endpoint shapes automatically.

---

## Setup

Copy this folder to your VPS, ideally inside or near your investing repo:

```bash
cd /root
# example folder location
cd sn88_strategy_bot
```

Create venv:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create config:

```bash
cp .env.example .env
nano .env
```

Set these values:

```env
TAOSTATS_API_KEY=your_key_here
INVESTING_DIR=/root/investing
HOTKEY_SS58=your_hotkey_ss58_here
SUBNET_DATA_SOURCE=taostats
```

---

## Test with CSV first

Before using your API key, test local CSV mode:

```bash
python -m bot.run_daily --source csv --dry-run
```

This should print a generated strategy without writing the real strategy file.

---

## Test with Taostats dry-run

```bash
python -m bot.run_daily --source taostats --dry-run
```

If the endpoint fails, edit:

```env
TAOSTATS_SUBNETS_ENDPOINT=your_endpoint_here
```

---

## Real run

```bash
python -m bot.run_daily
```

This will write:

```bash
$INVESTING_DIR/Investing/strat/$HOTKEY_SS58
```

and touch it.

---

## Install daily cron

Run:

```bash
./scripts/install_cron.sh
```

It installs:

```cron
CRON_TZ=UTC
50 23 * * * cd /path/to/sn88_strategy_bot && /path/to/sn88_strategy_bot/.venv/bin/python -m bot.run_daily >> /path/to/sn88_strategy_bot/logs/cron.log 2>&1
```

That means daily submit at **23:50 UTC**.

---

## Check logs

Bot logs:

```bash
tail -n 100 /root/investing/logs/sn88_strategy_bot.log
```

Cron logs:

```bash
tail -n 100 ./logs/cron.log
```

Miner logs:

```bash
pm2 logs investing-miner --lines 100
```

---

## Tune strategy rules

Edit `.env`:

```env
TOP_N=10
MIN_LIQUIDITY_TAO=5000
MAX_WEIGHT=0.20
MIN_WEIGHT=0.03
MAX_1H_PUMP=35
```

Scoring weights:

```env
W_7D=0.45
W_1D=0.25
W_1H=0.10
W_LIQUIDITY=0.10
W_FLOW=0.10
W_EMISSION=0.10
W_DRAWDOWN=0.25
```

Simple meaning:

- 7D change = main trend
- 1D change = confirmation
- 1H change = timing / risk warning
- liquidity = lower slippage risk
- flow = demand pressure
- emission = dividend/economic strength
- drawdown = risk penalty

---

## Safety tips

1. Do not commit `.env` because it contains your API key.
2. Start with `--dry-run`.
3. Check generated strategy before real submission.
4. Keep your SN88 miner running with PM2.
5. Do not rebalance too aggressively if it causes slippage.
