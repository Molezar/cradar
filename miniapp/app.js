async function load() {
    try {
        const r = await fetch("/data?t=" + Date.now());
        const j = await r.json();

        document.getElementById("info").innerText =
            `Cold wallet: ${j.cold_wallet}\nCluster size: ${j.cluster_size}`;

        document.getElementById("list").innerText =
            j.addresses.join("\n");

    } catch (e) {
        document.getElementById("info").innerText = "API error";
        console.error(e);
    }
}

load();