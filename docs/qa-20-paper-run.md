# 20-Paper Frontend QA Report

Date: 2026-11-15  
Run ID: `08d0cfe37fd3`  
Frontend: React production build, exercised in headless Chrome with Playwright  
Pipeline: `rla` live literature mode  
Run data: isolated temporary QA workspace

## Question and settings

**Topic:** AI for materials discovery

**Question:** “Which approaches combine machine learning with automated experiments to discover new materials, and what limits successful validation and scale-up?”

The UI exposed a maximum of 20 papers and submitted `paper_limit=20`. The provider wait ceiling was 300 seconds and the LLM request budget was 100. The structured and embedding models were Ollama `qwen3:4b` and `nomic-embed-text`; the answer model was Gemini `gemini-2.5-flash`.

## Run outcome

| Stage | Observed result |
|---|---|
| Frontend submission | HTTP 202; React displayed the run and live progress |
| Acquisition | 333 unique candidates after deduplication and one-hop snowballing; 60 candidates scored |
| Selected corpus | 20 papers |
| Extraction | 20/20 papers extracted |
| Resolution | 54 concept names became 47 concepts; 7 merged; 33 borderline pairs stayed separate after the 40-call judge budget was reached |
| Graph | 67 nodes, including 20 papers and 47 concepts; 133 edges reported; no citation edges and 77 derived edges reported |
| Answer | Saved; 12 of 15 selected subgraph nodes cited; 7 evidence records; no citations stripped |
| Final status | `completed_with_partial_sources`; pipeline stages succeeded, but two providers failed |

OpenAlex, arXiv, and Crossref returned results. Semantic Scholar requests failed; DBLP returned a bot-check HTML page. The UI accurately showed a partial run.

## Retrieved papers

This title-only review is a manual relevance triage, not a measured precision score. The full titles are recorded so the weak matches are visible.

| Paper ID | Retrieved title | Title-level fit for this question |
|---|---|---|
| `W2025444507` | Generalized Neural-Network Representation of High-Dimensional Potential-Energy Surfaces | Adjacent: atomistic modeling; experimental automation is not apparent from the title |
| `W2083415705` | Gaussian Approximation Potentials: The Accuracy of Quantum Mechanics, without the Electrons | Materials/molecular modeling |
| `W2766856748` | Crystal Graph Convolutional Neural Networks for an Accurate and Interpretable Prediction of Material Properties | Direct materials match |
| `W2949095042` | Graph Networks as a Universal Machine Learning Framework for Molecules and Crystals | Adjacent materials/chemistry method |
| `W3208687975` | Recent advances and applications of deep learning methods in materials science | Direct materials match |
| `W2971894235` | Machine Learning Interatomic Potentials as Emerging Tools for Materials Science | Direct materials match |
| `W2907492528` | A Comprehensive Survey on Graph Neural Networks | Weak match: broad graph-learning survey |
| `W2154851992` | DeepWalk: online learning of social representations | Weak match: social-network representations |
| `W2116341502` | The Graph Neural Network Model | Weak match: general graph-learning model |
| `W3152893301` | Graph neural networks: A review of methods and applications | Weak match: broad graph-learning review |
| `W1979769287` | Distilling Free-Form Natural Laws from Experimental Data | Adjacent: general scientific discovery, not specifically materials |
| `W2968923792` | Recent advances and applications of machine learning in solid-state materials science | Direct materials match |
| `W2029413789` | On representing chemical environments | Adjacent chemistry representation |
| `W2104489082` | Fast and Accurate Modeling of Molecular Atomization Energies with Machine Learning | Adjacent molecular modeling |
| `W2963784900` | Machine learning in materials informatics: recent applications and prospects | Direct materials match |
| `W2464725281` | A general-purpose machine learning framework for predicting properties of inorganic materials | Direct materials match |
| `W2742835787` | Materials discovery and design using machine learning | Direct materials match |
| `W3189164715` | Gaussian Process Regression for Materials and Molecules | Materials/molecular modeling |
| `W2585152223` | Machine learning of accurate energy-conserving molecular force fields | Adjacent molecular modeling |
| `W4360949780` | Small data machine learning in materials science | Direct materials match and a limitation source |

Four titles are broad graph-learning papers with weak fit. Several others concern materials prediction or atomistic modeling, but their titles do not establish that they discuss automated laboratories, closed-loop experiments, or scale-up validation.

## Answer quality

The answer cited ML-based materials screening and design, active learning, surrogate optimization, descriptors, and machine-learned molecular/material potentials. It identified small-data as a limitation. It also explicitly said the selected evidence did not show how ML was combined with automated experiments or how validation and scale-up were limited.

That restraint is appropriate: the answer did not invent support for missing topics. The result still only partially answers the question. Increasing the paper limit improved breadth and produced a supported discussion of materials ML, but it did **not** solve retrieval precision or coverage of automated experimentation and scale-up.

## Extraction-count note

The event stream for this run said “89 distinct concepts, 4 with a stated limitation.” That count included historical entries in the append-only extraction store and was misleading for this run. The current run actually resolved 54 names to 47 concepts. A follow-up code fix and regression test now calculate extraction summary counts from only the current papers; this run was not repeated after that reporting fix.

## Conclusion

The frontend can request 20 papers and the full pipeline can extract, resolve, graph, and answer at that size. The remaining product issue is retrieval quality: a 20-paper cap does not ensure the chosen papers directly address the user’s question. Query expansion and relevance selection need further work, and unsupported coverage should continue to be reported clearly.
