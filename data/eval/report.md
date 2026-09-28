==========================================================================
rla eval - graph vs RAG-over-abstracts
==========================================================================
corpus 63 papers | extracted 26 | held out 37
graph 90 nodes / 35 edges | 12 questions | judge: heuristic

Retrieved-evidence comparison (mean over questions)
--------------------------------------------------------------------------
dimension              graph     rag   delta  favours
citation_validity      1.000       -       -  not comparable
citation_support       1.000       -       -  not comparable
completeness               -       -       -  not comparable (judged)

Gap validity against held-out papers
--------------------------------------------------------------------------
6 gap(s): 5 refuted, 1 confirmed, 0 no signal, 0 not testable
refuted rate over testable gaps: 83% (higher means the gap analysis is doing worse)

  [refuted] Digital Twin
      2024  Integration of Decentralized Graph-Based Multi-Agent Reinfor  (11.3)
  [refuted] Digital Twin Edge Network
      2024  Integration of Decentralized Graph-Based Multi-Agent Reinfor  (12.6)
      2024  Cooperative Edge Caching Based on Elastic Federated and Mult  (5.1)
      2026  Transformer-GAT Assisted MADDPG for Task Offloading and Reso  (4.9)
  [refuted] Graph Attention Networks
      2025  Enhanced Integration of Single-Cell Multi-Omics Data Using G  (5.1)
      2025  Multi-Class Traffic Assignment Using Multi-View Heterogeneou  (5.1)
      2026  A multi-agent reinforcement learning with multi-task learnin  (4.9)
  [refuted] Graph Attention-based Multi-Agent Reinforcement Learning
      2026  A multi-agent reinforcement learning with multi-task learnin  (4.4)
      2026  Graph-Attention and Multi-Agent Reinforcement Learning for T  (4.0)
      2025  Multi-agent Collaborative Decision-making Mechanism Combinin  (4.0)
  [refuted] Mobile Edge Computing
      2026  Transformer-GAT Assisted MADDPG for Task Offloading and Reso  (14.2)
      2024  Optimizing Age of Information in Vehicular Edge Computing wi  (6.8)
      2026  A multi-agent reinforcement learning with multi-task learnin  (4.0)
  [confirmed] Multi-Agent Reinforcement Learning

Extraction accuracy
--------------------------------------------------------------------------
  NOT MEASURED
  - reference set 'p8-reference' has 0% hand-labelled items

Limitations of this run
--------------------------------------------------------------------------
  - Node/edge precision and recall are NOT reported. The reference set is not hand-labelled, so a number computed against it would measure the generator against itself. See the reference-set section.
  - No LLM judge ran: the Gemini free tier is a per-model daily cap and it is spent. Correctness and completeness are therefore not scored at all. The citation numbers are mechanical and are labelled as such; they are not substitutes for a judge's opinion.
  - The two arms never surfaced the same paper for any question. That is a finding about the two retrieval strategies, not a quality result.
  - The baseline is retrieval-only. It retrieves and shows abstracts; it does not generate an answer, because generating one needs the same LLM budget that is unavailable. The graph arm is likewise given its subgraph as text. This is a comparison of retrieved evidence, not of answer quality.
==========================================================================