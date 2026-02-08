import requests
import time
from bs4 import BeautifulSoup

# URL кошелька Binance на WalletExplorer
WALLET_URL = "https://www.walletexplorer.com/wallet/Binance.com"

def btc_inflow_last_minutes(minutes=60):
    """
    Суммирует входящие BTC транзакции на Binance за последние minutes.
    """
    try:
        resp = requests.get(WALLET_URL, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Ищем таблицу последних транзакций
        table = soup.find("table", {"class": "transaction-table"})
        if not table:
            print("Transactions table not found")
            return 0

        total_btc = 0
        cutoff = time.time() - minutes * 60

        rows = table.find_all("tr")[1:]  # пропускаем заголовок
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 5:
                continue

            # Столбцы могут быть: Txid | Block | Time | In | Out | BTC
            time_str = cols[2].text.strip()
            btc_value_str = cols[5].text.strip().replace(",", "").replace(" BTC", "")

            # Преобразуем время в timestamp
            try:
                tx_time_struct = time.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                tx_timestamp = time.mktime(tx_time_struct)
                btc_value = float(btc_value_str)
            except Exception:
                continue

            # Берём только входящие транзакции
            if tx_timestamp >= cutoff and btc_value > 0:
                total_btc += btc_value

        return round(total_btc, 8)

    except Exception as e:
        print("WalletExplorer fetch error:", e)
        return 0