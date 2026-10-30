# Third-Party Notices

Deriva bundles the following third-party material, and downloads the models listed at the end.

## APQC Process Classification Framework® (PCF)

`deriva/adapters/database/data/function_models/pcf-8.0-cross-industry.csv` is an excerpt (levels 1 and 2) of APQC's Process Classification Framework® (PCF) Cross-Industry, Excel Version 8.0. Deriva uses it as the default business function model that application services are classified into. The file carries the notice below at its top.

> ©2026 APQC. ALL RIGHTS RESERVED. This Process Classification Framework® (“PCF”) is the copyrighted intellectual property of APQC. APQC encourages the wide distribution, discussion, and use of the PCF for classifying and defining organizational processes. Accordingly, APQC hereby grants you a perpetual, worldwide, royalty-free license to use, copy, publish, modify, and create derivative works of the PCF, provided that all copies of the PCF and any derivative works contain a copy of this notice.

The full PCF and the industry-specific versions are available from APQC at <https://www.apqc.org/pcf>.

## Downloaded at runtime

The BusinessConcept extraction step downloads these language models on first use into `workspace/cache/nlp` (`DERIVA_NLP_MODELS_DIR`) and checks each against its pinned SHA-256 (`deriva/adapters/nlp/models.py`). They are not part of Deriva's packages; each comes under its own terms, as its package states them.

| Model | Source | SHA-256 | Licence (as the package states it) |
| --- | --- | --- | --- |
| spaCy `en_core_web_sm` 3.8.0 | <https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl> | `1932429db727d4bff3deed6b34cfc05df17794f4a52eeb26cf8928f7c1a0fb85` | MIT (training data: OntoNotes 5, licensed by Explosion; WordNet 3.0 License) |
| spaCy `de_core_news_sm` 3.8.0 | <https://github.com/explosion/spacy-models/releases/download/de_core_news_sm-3.8.0/de_core_news_sm-3.8.0-py3-none-any.whl> | `fec69fec52b1780f2d269d5af7582a5e28028738bd3190532459aeb473bfa3e7` | MIT (training data: TIGER Corpus, licensed by Explosion; WikiNER, CC BY 4.0) |
| spaCy `fr_core_news_sm` 3.8.0 | <https://github.com/explosion/spacy-models/releases/download/fr_core_news_sm-3.8.0/fr_core_news_sm-3.8.0-py3-none-any.whl> | `7d6ad14cd5078e53147bfbf70fb9d433c6a3865b695fda2657140bbc59a27e29` | LGPL-LR (training data: UD French Sequoia, LGPL-LR; WikiNER, CC BY 4.0) |
| Argos Translate `translate-de_en` 1.3 | <https://argos-net.com/v1/translate-de_en-1_3.argosmodel> | `becc2b0011f8249fcb89be9ecb75ba0d876b1fab93c28ee6ff0420936897d637` | The package states no licence; see the Argos Translate package index |
| Argos Translate `translate-fr_en` 1.9 | <https://argos-net.com/v1/translate-fr_en-1_9.argosmodel> | `3b3052fee6bb1e8e8e632a26a723eb2a2c7710dfe73ba61ffd9b83e85d4f14c1` | Derived from an OPUS-MT model (Tiedemann and Thottingal, EAMT 2020), licensed CC BY 4.0 |
