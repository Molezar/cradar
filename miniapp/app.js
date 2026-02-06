window.Telegram.WebApp.ready();

// Используем относительный путь, чтобы fetch обращался к серверу внутри того же контейнера
const API_URL = "/data";  

async function updateInflow() {
    try {
        const resp = await fetch(API_URL + "?t=" + Date.now()); // анти-кеш
        const data = await resp.json();

        document.getElementById("alert").innerText =
            `📥 BTC inflow last 60 min: ${data.btc_inflow} BTC`;
    } catch (e) {
        document.getElementById("alert").innerText = "⚠️ API error";
    }
}

// Первый вызов и обновление каждые 60 секунд
updateInflow();
setInterval(updateInflow, 60000);