let lastPrice = null;

async function load() {
    try {
        // whales
        const wr = await fetch("/whales?t=" + Date.now());
        const wj = await wr.json();

        // predictions
        const pr = await fetch("/prediction?t=" + Date.now());
        const pj = await pr.json();

        // price
        const prc = await fetch("/price?t=" + Date.now());
        const pcj = await prc.json();

        let out = "=== MEMPOOL WHALES ===\n\n";

        if (wj.whales) {
            for (const x of wj.whales) {
                out += `${x.btc.toFixed(2)} BTC   ${x.txid.slice(0, 12)}…\n`;
            }
        }

        let pred = "\n=== AI MARKET FORECAST ===\n";

        for (const horizon in pj) {
            const row = pj[horizon];
            const dir = row.pct > 0 ? "⬆" : "⬇";

            pred += `${horizon/60} min  ${dir}  ${row.pct.toFixed(2)}%   → $${row.target.toFixed(0)}\n`;
        }

        document.getElementById("list").innerText = out + pred;
        document.getElementById("info").innerText =
            pcj.price ? `BTC $${pcj.price.toFixed(0)}` : "BTC price…";

    } catch (e) {
        document.getElementById("info").innerText = "API error";
        console.error(e);
    }
}

load();
setInterval(load, 5000);