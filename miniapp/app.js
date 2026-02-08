fetch("/cluster")
.then(r => r.json())
.then(data => {
    const width = window.innerWidth
    const height = window.innerHeight

    const svg = d3.select("svg")

    const sim = d3.forceSimulation(data.nodes)
        .force("link", d3.forceLink(data.links).id(d=>d.id).distance(120))
        .force("charge", d3.forceManyBody().strength(-200))
        .force("center", d3.forceCenter(width/2, height/2))

    const link = svg.append("g")
        .selectAll("line")
        .data(data.links)
        .enter()
        .append("line")
        .attr("stroke", "#555")

    const node = svg.append("g")
        .selectAll("circle")
        .data(data.nodes)
        .enter()
        .append("circle")
        .attr("r", d => d.group === 0 ? 10 : 5)
        .attr("fill", d => d.group === 0 ? "red" : "cyan")

    sim.on("tick", () => {
        link
            .attr("x1", d => d.source.x)
            .attr("y1", d => d.source.y)
            .attr("x2", d => d.target.x)
            .attr("y2", d => d.target.y)

        node
            .attr("cx", d => d.x)
            .attr("cy", d => d.y)
    })
})