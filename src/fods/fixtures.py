"""Small, fixed multi-source snapshot for repeatable keyless demos."""

FIXTURE_PAPERS = {
    "semantic_scholar": [
        {
            "id": "doi:10.1109/graph-attention-demo",
            "title": "Graph Attention Networks",
            "year": 2018,
            "authors": ["Petar Velickovic", "Guillem Cucurull"],
            "abstract": (
                "Graph Attention Networks use masked self-attentional layers to assign different "
                "weights to neighboring nodes. The model combines local graph neighborhoods with "
                "attention-based message passing and was evaluated on graph benchmarks."
            ),
            "venue": "ICLR",
            "doi": "10.1109/graph-attention-demo",
            "url": "https://example.org/papers/gat-2018",
            "sources": ["semantic_scholar"],
            "citation_count": 500,
        },
        {
            "id": "doi:10.1109/graph-transformer-demo",
            "title": "Graph Transformers: A Generalization of Transformers to Graphs",
            "year": 2021,
            "abstract": (
                "Graph Transformers extend attention beyond local neighborhoods using structural "
                "encodings and global interactions between nodes. The paper discusses "
                "computational cost and graph structure bias."
            ),
            "url": "https://example.org/papers/graph-transformers-2021",
            "sources": ["semantic_scholar"],
            "citation_count": 180,
        },
    ],
    "openalex": [
        {
            "id": "openalex:W-GAT-2018",
            "title": "Graph Attention Networks",
            "year": 2018,
            "abstract": (
                "Graph attention assigns learned importance to adjacent nodes. "
                "Neighborhood attention supports inductive node representation learning and "
                "avoids requiring the full graph "
                "during inference."
            ),
            "doi": "10.1109/graph-attention-demo",
            "url": "https://example.org/papers/gat-2018",
            "sources": ["openalex"],
            "citation_count": 512,
        },
        {
            "id": "openalex:W-GNN-2017",
            "title": "Semi-Supervised Classification with Graph Convolutional Networks",
            "year": 2017,
            "abstract": (
                "Graph convolutional networks learn node representations by aggregating "
                "information from local neighborhoods. The method provides a scalable baseline "
                "for semi-supervised "
                "graph learning."
            ),
            "url": "https://example.org/papers/gcn-2017",
            "sources": ["openalex"],
            "citation_count": 900,
        },
    ],
    "arxiv": [
        {
            "id": "arxiv:2106.05234",
            "title": "Graph Transformers: A Generalization of Transformers to Graphs",
            "year": 2021,
            "abstract": (
                "This work studies graph transformers that model global attention alongside "
                "structural graph information. It highlights trade-offs between expressivity, "
                "structural bias, "
                "and computational complexity."
            ),
            "arxiv_id": "2106.05234",
            "url": "https://arxiv.org/abs/2106.05234",
            "sources": ["arxiv"],
            "citation_count": 210,
        },
        {
            "id": "arxiv:2305.15087",
            "title": "Efficient Graph Attention with Sparse Neighborhoods",
            "year": 2023,
            "abstract": (
                "Sparse neighborhood attention reduces the cost of graph attention on large "
                "graphs. Experiments show that locality and sampling choices affect accuracy and "
                "runtime."
            ),
            "arxiv_id": "2305.15087",
            "url": "https://arxiv.org/abs/2305.15087",
            "sources": ["arxiv"],
            "citation_count": 48,
        },
    ],
}
