window.Telegram.WebApp.ready();

const API_URL = "https://b241660030b141d7-194-242-96-14.serveousercontent.com/data";  // ← сюда свою ссылку

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

updateInflow();
setInterval(updateInflow, 60000);