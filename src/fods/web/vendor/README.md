# Vendored D3 browser assets

These pinned browser UMD builds are served only from the application's same-origin static route:

- `d3-path-3.1.0.min.js` — dependency used by D3 shape path generation.
- `d3-shape-3.2.0.min.js` — D3 line generator used for curved dependency edges in the task DAG.

The rendering owner remains `shell.js`; D3 generates edge geometry and does not mutate the SVG DOM. Task positions come from the runtime-validated topological levels and plan dependencies. The frontend does not infer new edges.

Source package pages: [d3-path 3.1.0](https://www.npmjs.com/package/d3-path/v/3.1.0), [d3-shape 3.2.0](https://www.npmjs.com/package/d3-shape/v/3.2.0). License texts are included beside the assets. D3 line/curve API reference: [D3 Lines](https://d3js.org/d3-shape/line), [D3 Curves](https://d3js.org/d3-shape/curve).
