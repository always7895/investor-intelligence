import yfinance as yf
import pandas as pd
import json
import os
import time
import logging
from datetime import datetime, timedelta

from local_research_config import load_research_universe

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, 'config')
DATA_DIR = os.path.join(BASE_DIR, 'data', 'cache')
HISTORY_DIR = os.path.join(BASE_DIR, 'data', 'history')


def load_watchlist(path=None):
    return load_research_universe(path)


def fetch_stock_data(ticker_info, max_retries=3):
    ticker = ticker_info['ticker']
    for attempt in range(max_retries):
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="1mo")
            info = t.info
            fast = t.fast_info
            return {
                'ticker': ticker,
                'name': ticker_info['name'],
                'category': ticker_info['category'],
                'current_price': float(fast.last_price) if fast.last_price else None,
                'previous_close': float(fast.previous_close) if fast.previous_close else None,
                'market_cap': info.get('marketCap'),
                'revenue_ttm': info.get('totalRevenue'),
                'revenue_growth': info.get('revenueGrowth'),
                'earnings_growth': info.get('earningsGrowth'),
                'forward_pe': info.get('forwardPE'),
                'trailing_pe': info.get('trailingPE'),
                'ps_ratio': info.get('priceToSalesTrailing12Months'),
                'peg_ratio': info.get('pegRatio'),
                'gross_margin': info.get('grossMargins'),
                'operating_margin': info.get('operatingMargins'),
                'profit_margin': info.get('profitMargins'),
                'return_on_equity': info.get('returnOnEquity'),
                'debt_to_equity': info.get('debtToEquity'),
                'free_cash_flow': info.get('freeCashflow'),
                'total_cash': info.get('totalCash'),
                'total_debt': info.get('totalDebt'),
                '52_week_high': info.get('fiftyTwoWeekHigh'),
                '52_week_low': info.get('fiftyTwoWeekLow'),
                'beta': info.get('beta'),
                'shares_outstanding': info.get('sharesOutstanding'),
                'short_pct_float': info.get('shortPercentOfFloat'),
                'analyst_target_mean': info.get('targetMeanPrice'),
                'analyst_recommendation': info.get('recommendationKey'),
                'num_analysts': info.get('numberOfAnalystOpinions'),
                'institutional_pct': info.get('heldPercentInstitutions'),
                'insider_pct': info.get('heldPercentInsiders'),
                'next_earnings_date': str(info.get('lastEarningsDate', '')),
                'price_change_1d': None,
                'price_change_5d': None,
                'price_change_1m': None,
                'avg_volume_3m': info.get('averageVolume'),
                'volume': float(hist['Volume'].iloc[-1]) if len(hist) > 0 else None,
            }
        except Exception as e:
            logger.warning(f"Attempt {attempt+1} failed for {ticker}: {e}")
            time.sleep(2 * (attempt + 1))
    return {'ticker': ticker, 'name': ticker_info['name'], 'error': 'failed_after_retries'}


def calculate_moments(hist):
    if hist is None or len(hist) < 2:
        return None, None, None
    close = hist['Close']
    chg_1d = (close.iloc[-1] / close.iloc[-2] - 1) * 100 if len(close) >= 2 else None
    chg_5d = (close.iloc[-1] / close.iloc[-6] - 1) * 100 if len(close) >= 6 else None
    chg_1m = (close.iloc[-1] / close.iloc[0] - 1) * 100 if len(close) >= 21 else None
    return chg_1d, chg_5d, chg_1m


def fetch_all(watchlist_path=None):
    stocks = load_watchlist(watchlist_path)
    logger.info(f"Fetching data for {len(stocks)} stocks...")
    results = []
    for i, stock in enumerate(stocks):
        logger.info(f"  [{i+1}/{len(stocks)}] {stock['ticker']}")
        data = fetch_stock_data(stock)
        if 'error' not in data:
            t = yf.Ticker(stock['ticker'])
            hist = t.history(period="1mo")
            chg_1d, chg_5d, chg_1m = calculate_moments(hist)
            data['price_change_1d'] = chg_1d
            data['price_change_5d'] = chg_5d
            data['price_change_1m'] = chg_1m
        results.append(data)
        time.sleep(1)

    os.makedirs(DATA_DIR, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path = os.path.join(DATA_DIR, f'market_{timestamp}.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, default=str)

    latest_path = os.path.join(DATA_DIR, 'market_latest.json')
    with open(latest_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, default=str)

    logger.info(f"Market data saved to {out_path}")
    return results


def fetch_market_indices():
    indices = {
        '^GSPC': 'S&P 500',
        '^IXIC': 'NASDAQ',
        '^DJI': 'Dow Jones',
        '^VIX': 'VIX',
        'TNF': '10Y Treasury',
        'DX-Y.NYB': 'Dollar Index',
        'CL=F': 'WTI Crude',
    }
    results = {}
    for symbol, name in indices.items():
        try:
            t = yf.Ticker(symbol)
            hist = t.history(period="5d")
            if len(hist) >= 2:
                close = hist['Close']
                results[symbol] = {
                    'name': name,
                    'close': float(close.iloc[-1]),
                    'change_1d': float((close.iloc[-1] / close.iloc[-2] - 1) * 100),
                }
            time.sleep(0.5)
        except Exception as e:
            logger.warning(f"Index {symbol} failed: {e}")
    return results


if __name__ == '__main__':
    indices = fetch_market_indices()
    print("Market Indices:")
    for sym, data in indices.items():
        print(f"  {data['name']}: {data['close']:.2f} ({data['change_1d']:+.2f}%)")

    all_data = fetch_all()
    print(f"\nFetched {len(all_data)} stocks successfully")
    for d in all_data:
        if 'error' not in d:
            print(f"  {d['ticker']}: ${d['current_price']:.2f} | MCap: ${d['market_cap']/1e9:.1f}B | FwdPE: {d.get('forward_pe', 'N/A')}")
