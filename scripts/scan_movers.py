import yfinance as yf
import pandas as pd
import json
import os
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data', 'cache')

SP500_TICKERS = [
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'AVGO', 'TSLA',
    'BRK-B', 'JPM', 'V', 'JNJ', 'WMT', 'PG', 'MRK', 'COST', 'HD',
    'DIS', 'NFLX', 'AMD', 'QCOM', 'INTC', 'CRM', 'ORCL', 'ADBE',
    'BA', 'CAT', 'VZ', 'UNH', 'XOM', 'CVX', 'GS', 'MS', 'BAC',
    'PFE', 'ABBV', 'LMT', 'TXN', 'MCD', 'RTX', 'PEP', 'KO',
    'CSCO', 'PM', 'ACN', 'LIN', 'TMO', 'ABT', 'GE', 'AMGN',
    'IBM', 'LOW', 'INTU', 'TJX', 'ISRG', 'AMGN', 'SPGI', 'BLK',
    'AXP', 'EBAY', 'T', 'PYPL', 'MMC', 'ADP', 'GILD', 'HON',
    'SHW', 'PCLF', 'LRCX', 'CL', 'SBUX', 'AMT', 'STZ', 'PLD',
    'CMCSA', 'COP', 'VZ', 'ORCL', 'UPS', 'RTX', 'QCOM', 'AMGN',
]


def scan_sp500_movers():
    logger.info("Scanning S&P 500 for notable movers...")
    tickers = list(set(SP500_TICKERS))
    movers = []

    try:
        data = yf.download(tickers, period="5d", group_by='ticker', progress=False, threads=True)
        for ticker in tickers:
            try:
                if isinstance(data.columns, pd.MultiIndex):
                    df = data[ticker].dropna()
                else:
                    df = data.dropna()
                if len(df) < 3:
                    continue
                close = df['Close']
                volume = df['Volume']
                chg_1d = (close.iloc[-1] / close.iloc[-2] - 1) * 100
                avg_vol = volume.iloc[:-1].mean()
                vol_ratio = volume.iloc[-1] / avg_vol if avg_vol > 0 else 1

                if abs(chg_1d) > 5 and vol_ratio > 1.5:
                    movers.append({
                        'ticker': ticker,
                        'change_pct': round(chg_1d, 2),
                        'volume_ratio': round(vol_ratio, 2),
                        'close': float(close.iloc[-1]),
                        'reason': 'Volume spike + significant price move'
                    })
            except:
                continue
    except Exception as e:
        logger.error(f"Batch download failed: {e}")
        # Fallback: individual fetch
        for ticker in tickers[:30]:
            try:
                t = yf.Ticker(ticker)
                hist = t.history(period="5d")
                if len(hist) >= 3:
                    close = hist['Close']
                    chg_1d = (close.iloc[-1] / close.iloc[-2] - 1) * 100
                    avg_vol = hist['Volume'].iloc[:-1].mean()
                    vol_ratio = hist['Volume'].iloc[-1] / avg_vol if avg_vol > 0 else 1
                    if abs(chg_1d) > 5 and vol_ratio > 1.5:
                        movers.append({
                            'ticker': ticker,
                            'change_pct': round(chg_1d, 2),
                            'volume_ratio': round(vol_ratio, 2),
                            'close': float(close.iloc[-1]),
                            'reason': 'Volume spike + significant price move'
                        })
            except:
                continue

    movers.sort(key=lambda x: abs(x['change_pct']), reverse=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path = os.path.join(DATA_DIR, f'movers_{timestamp}.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(movers[:20], f, indent=2)

    latest_path = os.path.join(DATA_DIR, 'movers_latest.json')
    with open(latest_path, 'w', encoding='utf-8') as f:
        json.dump(movers[:20], f, indent=2)

    logger.info(f"Found {len(movers)} notable movers")
    return movers[:20]


def scan_watchlist_moves():
    market_file = os.path.join(DATA_DIR, 'market_latest.json')
    if not os.path.exists(market_file):
        return []
    with open(market_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    notable = []
    for d in data:
        if 'error' in d:
            continue
        chg_1d = d.get('price_change_1d')
        if chg_1d is not None and abs(chg_1d) > 4:
            notable.append({
                'ticker': d['ticker'],
                'name': d['name'],
                'change_pct': round(chg_1d, 2),
                'price': d.get('current_price'),
                'note': 'Significant move in watchlist'
            })
    notable.sort(key=lambda x: abs(x['change_pct']), reverse=True)
    return notable


if __name__ == '__main__':
    movers = scan_sp500_movers()
    print(f"\nNotable Movers ({len(movers)}):")
    for m in movers[:10]:
        print(f"  {m['ticker']}: {m['change_pct']:+.2f}% (Vol {m['volume_ratio']:.1f}x avg) @ ${m['close']:.2f}")

    watch_moves = scan_watchlist_moves()
    if watch_moves:
        print(f"\nWatchlist Notable Moves:")
        for w in watch_moves:
            print(f"  {w['ticker']} ({w['name']}): {w['change_pct']:+.2f}%")
