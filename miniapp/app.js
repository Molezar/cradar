if (window.Telegram && window.Telegram.WebApp) {
    window.Telegram.WebApp.ready();
}

const API_URL = "/data";

// Форматирование чисел с разделителем тысяч
function formatNumber(num) {
    return Number(num).toLocaleString(undefined, {maximumFractionDigits: 2});
}

async function updateMetrics() {
    try {
        const resp = await fetch(API_URL + "?interval=1h&t=" + Date.now());
        const data = await resp.json();

        if (data.error) {
            document.getElementById("alert").innerText = `⚠️ ${data.error}`;
            return;
        }

        const {oi_total, oi_long, oi_short, funding_rate} = data;

        document.getElementById("alert").innerHTML =
            `💹 BTC Exchange Metrics (Binance last 1h):<br>` +
            `📈 Total OI: ${formatNumber(oi_total)} USD<br>` +
            `🟢 Long OI: ${formatNumber(oi_long)} USD<br>` +
            `🔴 Short OI: ${formatNumber(oi_short)} USD<br>` +
            `⚖️ Funding Rate: ${funding_rate}%`;
    } catch (e) {
        document.getElementById("alert").innerText = "⚠️ API error";
        console.error(e);
    }
}

// первый вызов
updateMetrics();

// обновление каждые 60 секунд
setInterval(updateMetrics, 60000);