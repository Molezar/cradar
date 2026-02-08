if (window.Telegram && window.Telegram.WebApp) {
    window.Telegram.WebApp.ready();
}

const API_URL = "/data";

async function updateInflow() {
    try {
        const resp = await fetch(API_URL + "?t=" + Date.now());
        const data = await resp.json();

        document.getElementById("alert").innerText =
            `📥 BTC inflow last ${data.btc_inflow} BTC`;
    } catch (e) {
        document.getElementById("alert").innerText = "⚠️ API error";
        console.error(e);
    }
}

updateInflow();
setInterval(updateInflow, 60000);